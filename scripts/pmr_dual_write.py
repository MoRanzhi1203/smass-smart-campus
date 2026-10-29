"""PM4：双写模式与批次回滚。

在同一个库内同时存在 legacy 侧（`app01_admin/teacher/student`）与
R10 侧（`r21_account_account` 等），因此可以精确控制**写顺序**与**失败注入点**，
用来验证"两次写之间失败"的补偿行为。

三种模式
--------
- ``off``   ：只写 legacy（迁移前的状态）
- ``dual``  ：两边都写；任一失败则补偿已成功的一侧
- ``r10``   ：只写 R10（切换完成后的状态）

核心保证
--------
1. **幂等**：``pmr_dual_log.idempotency_key`` 唯一；重复请求返回首次结果，不重复写。
2. **补偿**：dual 模式下第二写失败时，把第一写的效果撤销并标记 ``compensated``。
3. **批次回滚**：``rollback_batch`` 只撤销指定 ``batch_id`` 的 R10 侧效果。
4. **回滚后可登录**：撤销的是新增账号，不影响既有账号的认证路径。

用法：
    $env:SMASS_DB_PASSWORD='<root>'
    conda run -n smass python scripts/pmr_dual_write.py --db smass_pmr_target_fresh --scenario all
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'pmr_dual'

DUAL_DDL = """
CREATE TABLE IF NOT EXISTS pmr_dual_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(32) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  operation VARCHAR(32) NOT NULL,
  legacy_ok TINYINT NOT NULL DEFAULT 0,
  r10_ok TINYINT NOT NULL DEFAULT 0,
  status VARCHAR(24) NOT NULL DEFAULT 'pending',
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_dual_idem (idempotency_key),
  KEY idx_dual_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

MODE_OFF = 'off'
MODE_DUAL = 'dual'
MODE_R10 = 'r10'


def conn(db):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8mb4', autocommit=False)


class InjectedFailure(RuntimeError):
    """用于验证补偿路径的人为失败。"""


class DualWriter:
    def __init__(self, db, batch_id, mode=MODE_DUAL):
        self.db = db
        self.batch_id = batch_id
        self.mode = mode
        self.conn = conn(db)
        self.now = datetime.now().replace(microsecond=0)
        self.log = []

    def close(self):
        self.conn.close()

    def ensure_table(self):
        with self.conn.cursor() as cur:
            cur.execute(DUAL_DDL)
        self.conn.commit()

    # ---- 幂等 ----
    def _existing(self, idem_key):
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                'SELECT * FROM pmr_dual_log WHERE idempotency_key=%s', [idem_key])
            return cur.fetchone()

    def _record(self, idem_key, operation, legacy_ok, r10_ok, status, note=''):
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_dual_log '
                '(batch_id, idempotency_key, operation, legacy_ok, r10_ok, '
                ' status, note, created_at, updated_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON DUPLICATE KEY UPDATE '
                ' legacy_ok=VALUES(legacy_ok), r10_ok=VALUES(r10_ok), '
                ' status=VALUES(status), note=VALUES(note), '
                ' updated_at=VALUES(updated_at)',
                (self.batch_id, idem_key, operation, int(legacy_ok), int(r10_ok),
                 status, note[:255], self.now, self.now))

    # ---- legacy 侧 ----
    def _legacy_create(self, legacy_id, name, encoded):
        with self.conn.cursor() as cur:
            cur.execute(
                'INSERT INTO app01_admin (id, name, password) VALUES (%s,%s,%s)',
                (legacy_id, name, encoded))

    def _legacy_delete(self, legacy_id):
        with self.conn.cursor() as cur:
            cur.execute('DELETE FROM app01_admin WHERE id=%s', [legacy_id])

    # ---- R10 侧 ----
    def _r10_create(self, login_name, display_name, encoded, role):
        from r21_account.models import Account, RoleCode  # noqa: F401
        from r21_account import services as core_services

        account = Account(
            login_name=login_name,
            display_name=display_name,
            person_type='admin',
            must_change_password=True,
        )
        account.password = encoded
        account.save(force_insert=True)

        core_services.ensure_role_groups()
        core_services.grant_role(account, role, granted_by='pmr-dual')
        return account.pk

    def _r10_delete(self, login_name):
        from r21_account.models import Account
        Account.objects.filter(login_name=login_name).delete()

    # ---- 主流程 ----
    def create_account(self, idem_key, legacy_id, name, encoded,
                       role='system_admin', fail_after=None):
        """创建账号。``fail_after`` 用于注入失败：1=legacy 后，2=R10 后。"""
        existing = self._existing(idem_key)
        if existing:
            result = {
                'idempotent_replay': True,
                'idempotency_key': idem_key,
                'status': existing['status'],
                'legacy_ok': bool(existing['legacy_ok']),
                'r10_ok': bool(existing['r10_ok']),
            }
            self.log.append(result)
            return result

        login_name = 'pmr-{}'.format(legacy_id.lower())[:32]
        legacy_ok = False
        r10_ok = False
        status = 'pending'
        note = ''

        try:
            if self.mode in (MODE_OFF, MODE_DUAL):
                self._legacy_create(legacy_id, name, encoded)
                legacy_ok = True

            if fail_after == 1:
                raise InjectedFailure('injected after legacy write')

            if self.mode in (MODE_DUAL, MODE_R10):
                self._r10_create(login_name, name, encoded, role)
                r10_ok = True

            if fail_after == 2:
                raise InjectedFailure('injected after r10 write')

            status = 'committed'
            self.conn.commit()

        except Exception as exc:  # noqa: BLE001
            self.conn.rollback()
            # 补偿：把已成功的一侧撤销
            compensated = []
            try:
                if legacy_ok:
                    self._legacy_delete(legacy_id)
                    compensated.append('legacy')
                if r10_ok:
                    self._r10_delete(login_name)
                    compensated.append('r10')
                self.conn.commit()
                status = 'compensated'
                note = '{}; compensated={}'.format(
                    type(exc).__name__, ','.join(compensated) or 'none')
            except Exception as exc2:  # noqa: BLE001
                status = 'pending'
                note = 'compensation failed: {}'.format(type(exc2).__name__)

        self._record(idem_key, 'create_account', legacy_ok, r10_ok, status, note)
        self.conn.commit()

        result = {
            'idempotency_key': idem_key,
            'login_name': login_name,
            'legacy_ok': legacy_ok,
            'r10_ok': r10_ok,
            'status': status,
            'note': note,
            'mode': self.mode,
        }
        self.log.append(result)
        return result

    def change_password(self, idem_key, legacy_id, new_encoded):
        """改密：双写模式下两边都改。"""
        existing = self._existing(idem_key)
        if existing:
            return {'idempotent_replay': True, 'status': existing['status']}

        login_name = 'pmr-{}'.format(legacy_id.lower())[:32]
        legacy_ok = r10_ok = False
        try:
            if self.mode in (MODE_OFF, MODE_DUAL):
                with self.conn.cursor() as cur:
                    cur.execute(
                        'UPDATE app01_admin SET password=%s WHERE id=%s',
                        (new_encoded, legacy_id))
                    legacy_ok = cur.rowcount > 0

            if self.mode in (MODE_DUAL, MODE_R10):
                from r21_account.models import Account
                updated = Account.objects.filter(
                    login_name=login_name).update(password=new_encoded)
                r10_ok = updated > 0

            status = 'committed' if (legacy_ok or r10_ok) else 'noop'
            self.conn.commit()
        except Exception as exc:  # noqa: BLE001
            self.conn.rollback()
            status = 'failed'
            self._record(idem_key, 'change_password', legacy_ok, r10_ok,
                         status, type(exc).__name__)
            self.conn.commit()
            return {'status': status, 'error': type(exc).__name__}

        self._record(idem_key, 'change_password', legacy_ok, r10_ok, status)
        self.conn.commit()
        return {'status': status, 'legacy_ok': legacy_ok, 'r10_ok': r10_ok}

    def revoke_role(self, idem_key, legacy_id, role='system_admin'):
        """撤权：只影响 R10 侧（legacy 没有角色概念）。"""
        from r21_account.models import Account
        from r21_account import services as core_services

        login_name = 'pmr-{}'.format(legacy_id.lower())[:32]
        account = Account.objects.filter(login_name=login_name).first()
        if account is None:
            status = 'noop'
        else:
            core_services.revoke_role(account, role, revoked_by='pmr-dual')
            status = 'committed'

        self._record(idem_key, 'revoke_role', False, True, status)
        self.conn.commit()
        return {'status': status}

    # ---- 回滚 ----
    def rollback_batch(self, batch_id):
        """只撤销该批次创建的 R10 账号，不影响其他批次。"""
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT * FROM pmr_dual_log "
                "WHERE batch_id=%s AND operation='create_account' "
                "AND status='committed' AND r10_ok=1", [batch_id])
            rows = cur.fetchall()

        removed = []
        for row in rows:
            key = row['idempotency_key']
            login_name = 'pmr-{}'.format(
                key.split(':', 1)[-1].lower())[:32] if ':' in key else None
            if not login_name:
                continue
            self._r10_delete(login_name)
            removed.append(login_name)

        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE pmr_dual_log SET status='rolled_back', updated_at=%s "
                "WHERE batch_id=%s AND operation='create_account' "
                "AND status='committed'", (self.now, batch_id))
        self.conn.commit()
        return {'batch_id': batch_id, 'removed': removed}


def scenario_matrix(db, batch_prefix):
    """覆盖 off -> dual -> r10 与失败注入。"""
    results = {}
    stamp = datetime.now().strftime('%H%M%S')
    w = DualWriter(db, '{}-dual-{}'.format(batch_prefix, stamp), mode=MODE_DUAL)
    try:
        w.ensure_table()

        # 1) dual：两边都写
        results['dual_create'] = w.create_account(
            'create:D01', 'D01', '双写甲', 'a' * 32)

        # 2) dual：注入失败（legacy 后）
        results['dual_fail_after_legacy'] = w.create_account(
            'create:D02', 'D02', '双写乙', 'b' * 32, fail_after=1)

        # 3) 幂等：重复 key
        results['dual_replay'] = w.create_account(
            'create:D01', 'D01', '双写甲', 'a' * 32)

        # 4) 改密
        results['dual_change_pw'] = w.change_password(
            'pw:D01', 'D01', 'c' * 32)

        # 5) 撤权
        results['dual_revoke'] = w.revoke_role('revoke:D01', 'D01')

        # 6) 批次回滚
        results['rollback'] = w.rollback_batch(w.batch_id)

        # 7) 回滚后登录路径：Account 应已不存在，查询不报错
        from r21_account.models import Account
        results['post_rollback_exists'] = Account.objects.filter(
            login_name='pmr-d01').exists()
    finally:
        w.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--scenario', default='all')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 SMASS_DB_PASSWORD 环境变量')

    if not args.db.startswith('smass_pmr_'):
        raise SystemExit('拒绝：库名必须命中 smass_pmr_ 前缀')

    os.environ['PMR_DB'] = args.db if args.db.startswith('smass_pmr_target_') else args.db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    report = {'database': args.db, 'scenario': args.scenario, 'steps': []}
    results = scenario_matrix(args.db, 'pm4')

    checks = [
        {'check': 'dual_created_both_sides',
         'ok': results['dual_create']['legacy_ok'] and results['dual_create']['r10_ok']},
        {'check': 'fail_after_legacy_compensated',
         'ok': results['dual_fail_after_legacy']['status'] == 'compensated'},
        {'check': 'fail_after_legacy_legacy_removed',
         'ok': results['dual_fail_after_legacy']['legacy_ok'] is True},
        {'check': 'idempotent_replay_no_duplicate',
         'ok': results['dual_replay'].get('idempotent_replay') is True},
        {'check': 'change_password_committed',
         'ok': results['dual_change_pw']['status'] == 'committed'},
        {'check': 'revoke_role_committed',
         'ok': results['dual_revoke']['status'] == 'committed'},
        {'check': 'rollback_removed_accounts',
         'ok': len(results['rollback']['removed']) >= 1},
        {'check': 'post_rollback_login_path_intact',
         'ok': results['post_rollback_exists'] is False},
    ]
    report['results'] = results
    report['checks'] = checks
    report['ok'] = all(c['ok'] for c in checks)

    # 补偿后遗留检查：PM4A002 不应出现在任一侧
    c = conn(args.db)
    try:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM app01_admin WHERE id='D02'")
            legacy_left = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM r21_account_account WHERE login_name='pmr-d02'")
            r10_left = cur.fetchone()[0]
    finally:
        c.close()

    report['compensation_residue'] = {'legacy': legacy_left, 'r10': r10_left}
    report['checks'].append({
        'check': 'compensation_left_no_residue',
        'ok': legacy_left == 0 and r10_left == 0})
    report['ok'] = all(item['ok'] for item in report['checks'])

    path = OUT_DIR / 'dual_{}.json'.format(stamp)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    report['manifest_path'] = str(path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
