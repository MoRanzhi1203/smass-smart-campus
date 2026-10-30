#!/usr/bin/env python
"""S05：**真正跨库**双写仿真（两个独立 MySQL 数据库）。

与 PM4（同库双表）的区别
------------------------
PM4 在同一个数据库里同时放 legacy 与 R10 表，只能验证"写顺序与补偿逻辑"，
**不能**代表生产环境的跨库/跨系统写入。本脚本为两侧各建一个独立数据库：

- ``smass_pmr_cross_legacy_*``：只有 ``app01_admin``（旧系统）
- ``smass_pmr_cross_r10_*``：只有 ``r21_account_account``（新系统）
- 控制日志与补偿队列放在 R10 库（``pmr_cross_log`` / ``pmr_compensation_queue``）

跨库写入没有分布式事务，因此本脚本显式验证：

1. 双写成功（两侧各一行）；
2. 单侧失败（第二写失败后补偿第一写）；
3. 补偿失败（进入持久化队列，受控重放后收敛）；
4. 进程异常退出（子进程写完一侧后 ``os._exit``，父进程对账修复）；
5. 不确定提交结果（提交后进程退出，重启后按幂等键判定）；
6. 幂等重放（同键不产生第二行）；
7. 一致性恢复（对账扫描 + 修复后零漂移）。

用法::

    python scripts/pmr_cross_db_dual_write.py --scenario all --json
    python scripts/pmr_cross_db_dual_write.py --legacy-db A --r10-db B --scenario all

所有库名必须命中 ``smass_pmr_cross_`` 前缀，拒绝指向正式库。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

HOST = os.environ.get('DB_HOST', 'localhost')
PORT = int(os.environ.get('DB_PORT', '3306'))
ADMIN_USER = os.environ.get('DB_USER', 'root')
ADMIN_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('SMASS_DB_PASSWORD', '')

LEGACY_PREFIX = 'smass_pmr_cross_legacy_'
R10_PREFIX = 'smass_pmr_cross_r10_'

LEGACY_DDL = """
CREATE TABLE IF NOT EXISTS app01_admin (
  id VARCHAR(3) NOT NULL PRIMARY KEY,
  name VARCHAR(16) NOT NULL,
  password VARCHAR(128) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

R10_DDL = """
CREATE TABLE IF NOT EXISTS r21_account_account (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  password VARCHAR(128) NOT NULL,
  login_name VARCHAR(32) NOT NULL UNIQUE,
  display_name VARCHAR(32) NOT NULL,
  person_type VARCHAR(16) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  is_superuser TINYINT(1) NOT NULL DEFAULT 0,
  is_staff TINYINT(1) NOT NULL DEFAULT 0,
  must_change_password TINYINT(1) NOT NULL DEFAULT 1,
  scope_college VARCHAR(100) NOT NULL DEFAULT '',
  deactivated_at DATETIME(6) NULL,
  deactivated_reason VARCHAR(64) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

LOG_DDL = """
CREATE TABLE IF NOT EXISTS pmr_cross_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(48) NOT NULL,
  idempotency_key VARCHAR(96) NOT NULL UNIQUE,
  operation VARCHAR(32) NOT NULL,
  legacy_ok TINYINT(1) NOT NULL DEFAULT 0,
  r10_ok TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(24) NOT NULL DEFAULT 'pending',
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS pmr_compensation_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  idempotency_key VARCHAR(96) NOT NULL,
  side VARCHAR(8) NOT NULL,
  payload VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  last_error VARCHAR(128) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL,
  resolved_at DATETIME(6) NULL,
  KEY idx_queue_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


class InjectedFailure(RuntimeError):
    """人为注入的写入/补偿失败。"""


def guard(name: str, prefix: str) -> str:
    if not name.startswith(prefix):
        raise SystemExit('拒绝：库名必须命中 {}，当前 {!r}'.format(prefix, name))
    return name


def admin_conn(database=None):
    return pymysql.connect(host=HOST, port=PORT, user=ADMIN_USER,
                           password=ADMIN_PASSWORD, database=database,
                           charset='utf8mb4', autocommit=True)


def db_conn(database):
    return pymysql.connect(host=HOST, port=PORT, user=ADMIN_USER,
                           password=ADMIN_PASSWORD, database=database,
                           charset='utf8mb4', autocommit=False)


def create_db(name: str) -> None:
    c = admin_conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                'CREATE DATABASE IF NOT EXISTS `{}` '
                'CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci'.format(name))
    finally:
        c.close()


def drop_db(name: str) -> None:
    c = admin_conn()
    try:
        with c.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS `{}`'.format(name))
    finally:
        c.close()


def init_schema(legacy_db: str, r10_db: str) -> None:
    lc = db_conn(legacy_db)
    try:
        with lc.cursor() as cur:
            cur.execute(LEGACY_DDL)
        lc.commit()
    finally:
        lc.close()

    rc = db_conn(r10_db)
    try:
        with rc.cursor() as cur:
            cur.execute(R10_DDL)
            cur.execute(LOG_DDL)
            cur.execute(QUEUE_DDL)
        rc.commit()
    finally:
        rc.close()


def make_pair(stamp: str | None = None) -> tuple[str, str]:
    import uuid
    stamp = stamp or '{}_{}'.format(
        datetime.now().strftime('%Y%m%d_%H%M%S'), uuid.uuid4().hex[:6])
    return (LEGACY_PREFIX + stamp, R10_PREFIX + stamp)


class CrossDbDualWriter:
    """两个独立连接上的写入；没有跨库事务，失败后靠补偿与队列收敛。"""

    def __init__(self, legacy_db: str, r10_db: str, batch_id: str):
        guard(legacy_db, LEGACY_PREFIX)
        guard(r10_db, R10_PREFIX)
        self.legacy_db = legacy_db
        self.r10_db = r10_db
        self.batch_id = batch_id
        self.legacy = db_conn(legacy_db)
        self.r10 = db_conn(r10_db)
        self.now = datetime.now().replace(microsecond=0)

    def close(self):
        for c in (self.legacy, self.r10):
            try:
                c.close()
            except Exception:
                pass

    def _refresh(self):
        """结束当前事务快照，确保跨进程写入后能读到最新状态。"""
        for c in (self.legacy, self.r10):
            try:
                c.commit()
            except Exception:
                pass

    # ---- 日志 / 队列 ----
    def _log_row(self, idem_key):
        with self.r10.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute('SELECT * FROM pmr_cross_log WHERE idempotency_key=%s',
                        [idem_key])
            return cur.fetchone()

    def _write_log(self, idem_key, operation, legacy_ok, r10_ok, status, note=''):
        with self.r10.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_cross_log '
                '(batch_id, idempotency_key, operation, legacy_ok, r10_ok, '
                ' status, note, created_at, updated_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON DUPLICATE KEY UPDATE legacy_ok=VALUES(legacy_ok), '
                ' r10_ok=VALUES(r10_ok), status=VALUES(status), '
                ' note=VALUES(note), updated_at=VALUES(updated_at)',
                (self.batch_id, idem_key, operation, int(legacy_ok), int(r10_ok),
                 status, note[:255], self.now, self.now))
        self.r10.commit()

    def _enqueue(self, idem_key, side, payload, error):
        with self.r10.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_compensation_queue '
                '(idempotency_key, side, payload, status, attempts, last_error, '
                ' created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (idem_key, side, payload[:64], 'pending', 1,
                 str(error)[:128], self.now))
        self.r10.commit()

    # ---- 单侧写入 ----
    def _legacy_create(self, legacy_id, name, encoded):
        with self.legacy.cursor() as cur:
            cur.execute('INSERT INTO app01_admin (id, name, password) '
                        'VALUES (%s,%s,%s)', (legacy_id, name[:16], encoded))
        self.legacy.commit()

    def _legacy_delete(self, legacy_id):
        with self.legacy.cursor() as cur:
            cur.execute('DELETE FROM app01_admin WHERE id=%s', [legacy_id])
        self.legacy.commit()

    def _r10_create(self, login_name, name, encoded):
        with self.r10.cursor() as cur:
            cur.execute(
                'INSERT INTO r21_account_account '
                '(password, login_name, display_name, person_type, is_active, '
                ' is_superuser, is_staff, must_change_password, created_at, updated_at) '
                'VALUES (%s,%s,%s,%s,1,0,0,1,%s,%s)',
                (encoded, login_name[:32], name[:32], 'admin', self.now, self.now))
        self.r10.commit()

    def _r10_delete(self, login_name):
        with self.r10.cursor() as cur:
            cur.execute('DELETE FROM r21_account_account WHERE login_name=%s',
                        [login_name])
        self.r10.commit()

    # ---- 主流程 ----
    def create_account(self, idem_key, legacy_id, name, encoded,
                       fail_after=None, fail_compensation=False):
        """写两侧。``fail_after``：1=legacy 后；2=R10 后（用于模拟不确定提交）。"""
        existing = self._log_row(idem_key)
        if existing and existing['status'] in ('committed', 'compensated'):
            return {
                'idempotent_replay': True,
                'status': existing['status'],
                'legacy_ok': bool(existing['legacy_ok']),
                'r10_ok': bool(existing['r10_ok']),
            }

        login_name = 'pmr-{}'.format(str(legacy_id).lower())[:32]
        legacy_ok = r10_ok = False
        status = 'pending'
        note = ''

        try:
            self._legacy_create(legacy_id, name, encoded)
            legacy_ok = True
            if fail_after == 1:
                raise InjectedFailure('injected after legacy commit')

            self._r10_create(login_name, name, encoded)
            r10_ok = True
            if fail_after == 2:
                raise InjectedFailure('injected after r10 commit')

            status = 'committed'
        except Exception as exc:  # noqa: BLE001
            status, note = self._compensate(
                idem_key, legacy_id, login_name, legacy_ok, r10_ok,
                exc, fail_compensation)
        finally:
            self._write_log(idem_key, 'create_account', legacy_ok, r10_ok,
                            status, note)

        return {
            'idempotency_key': idem_key,
            'login_name': login_name,
            'legacy_ok': legacy_ok,
            'r10_ok': r10_ok,
            'status': status,
            'note': note,
        }

    def _compensate(self, idem_key, legacy_id, login_name, legacy_ok, r10_ok,
                    exc, fail_compensation):
        compensated = []
        note = type(exc).__name__
        try:
            if legacy_ok:
                if fail_compensation:
                    raise InjectedFailure('injected compensation failure')
                self._legacy_delete(legacy_id)
                compensated.append('legacy')
            if r10_ok:
                self._r10_delete(login_name)
                compensated.append('r10')
            return 'compensated', '{}; compensated={}'.format(
                note, ','.join(compensated) or 'none')
        except Exception as exc2:  # noqa: BLE001
            # 把未完成的补偿持久化，等待受控重放。
            if legacy_ok:
                self._enqueue(idem_key, 'legacy', legacy_id, exc2)
            if r10_ok:
                self._enqueue(idem_key, 'r10', login_name, exc2)
            return 'compensation_pending', '{}; compensation failed: {}'.format(
                note, type(exc2).__name__)

    # ---- 重放 / 对账 ----
    def replay_compensation(self, limit: int = 100) -> dict:
        """重试队列中的补偿动作；成功则标记 resolved。"""
        self._refresh()
        with self.r10.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT * FROM pmr_compensation_queue WHERE status='pending' "
                'ORDER BY id LIMIT %s', [limit])
            rows = cur.fetchall()

        resolved, failed = [], []
        for row in rows:
            try:
                if row['side'] == 'legacy':
                    self._legacy_delete(row['payload'])
                else:
                    self._r10_delete(row['payload'])
                with self.r10.cursor() as cur:
                    cur.execute(
                        "UPDATE pmr_compensation_queue SET status='resolved', "
                        'resolved_at=%s WHERE id=%s', (self.now, row['id']))
                self.r10.commit()
                resolved.append(row['id'])
            except Exception as exc:  # noqa: BLE001
                with self.r10.cursor() as cur:
                    cur.execute(
                        'UPDATE pmr_compensation_queue SET attempts=attempts+1, '
                        'last_error=%s WHERE id=%s',
                        (str(exc)[:128], row['id']))
                self.r10.commit()
                failed.append(row['id'])

        if resolved:
            with self.r10.cursor() as cur:
                cur.execute(
                    "UPDATE pmr_cross_log SET status='compensated', updated_at=%s "
                    "WHERE idempotency_key IN ("
                    " SELECT idempotency_key FROM pmr_compensation_queue "
                    " WHERE id IN ({}) )".format(
                        ','.join(['%s'] * len(resolved))),
                    [self.now, *resolved])
            self.r10.commit()

        return {'resolved': resolved, 'failed': failed}

    def drift(self) -> dict:
        """按登录名比较两侧账号集合，返回三类漂移。"""
        self._refresh()
        with self.legacy.cursor() as cur:
            cur.execute('SELECT id FROM app01_admin')
            legacy_ids = {'pmr-{}'.format(r[0].lower()[:32]) for r in cur.fetchall()}
        with self.r10.cursor() as cur:
            cur.execute("SELECT login_name FROM r21_account_account "
                        "WHERE login_name LIKE 'pmr-%'")
            r10_ids = {r[0] for r in cur.fetchall()}
        return {
            'legacy_only': sorted(legacy_ids - r10_ids),
            'r10_only': sorted(r10_ids - legacy_ids),
            'both': sorted(legacy_ids & r10_ids),
            'drift_count': len(legacy_ids ^ r10_ids),
        }

    def repair_drift(self) -> dict:
        """受控修复：遗留单侧账号按"未提交"补偿删除（不猜测业务意图）。"""
        self._refresh()
        report = self.drift()
        removed_legacy, removed_r10 = [], []
        for login_name in report['legacy_only']:
            legacy_id = login_name[len('pmr-'):]
            with self.legacy.cursor() as cur:
                cur.execute('DELETE FROM app01_admin WHERE id=%s', [legacy_id])
            self.legacy.commit()
            removed_legacy.append(login_name)
        for login_name in report['r10_only']:
            self._r10_delete(login_name)
            removed_r10.append(login_name)
        after = self.drift()
        return {
            'removed_legacy': removed_legacy,
            'removed_r10': removed_r10,
            'drift_after': after['drift_count'],
        }

    def resolve_unknown(self, idem_key, legacy_id, think_committed: bool) -> dict:
        """不确定提交：按两侧实际状态判定，并补写日志（不重复写）。"""
        self._refresh()
        login_name = 'pmr-{}'.format(str(legacy_id).lower())[:32]
        with self.legacy.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM app01_admin WHERE id=%s', [legacy_id])
            legacy_exists = cur.fetchone()[0] > 0
        with self.r10.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM r21_account_account '
                        'WHERE login_name=%s', [login_name])
            r10_exists = cur.fetchone()[0] > 0

        if legacy_exists and r10_exists and think_committed:
            status = 'committed'
        elif legacy_exists or r10_exists:
            status = 'drift_detected'
        else:
            status = 'not_committed'
        self._write_log(idem_key, 'resolve_unknown', legacy_exists, r10_exists,
                        status)
        return {
            'idempotency_key': idem_key,
            'legacy_exists': legacy_exists,
            'r10_exists': r10_exists,
            'status': status,
        }


# --------------------------------------------------------------------------
# 进程异常退出：用子进程在写完一侧后 os._exit
# --------------------------------------------------------------------------
def child_write(legacy_db: str, r10_db: str, idem_key: str, legacy_id: str,
                after: str = 'legacy') -> None:
    """在子进程中写一侧后硬退出，模拟进程崩溃。"""
    w = CrossDbDualWriter(legacy_db, r10_db, 'child-kill')
    try:
        w._legacy_create(legacy_id, '崩溃测试', 'x' * 32)
        if after == 'r10':
            w._r10_create('pmr-{}'.format(legacy_id.lower()), '崩溃测试', 'x' * 32)
        os._exit(9)
    finally:
        w.close()


def scenario_all(legacy_db: str, r10_db: str, child: bool = True) -> dict:
    init_schema(legacy_db, r10_db)
    stamp = datetime.now().strftime('%H%M%S')
    w = CrossDbDualWriter(legacy_db, r10_db, 's05-' + stamp)
    checks = []

    def add(name, ok, detail=None):
        checks.append({'check': name, 'ok': bool(ok),
                       'detail': detail if detail is not None else ''})

    try:
        # 1) 双写成功
        r1 = w.create_account('create:A01', 'A01', '双写甲', 'a' * 32)
        add('dual_both_sides', r1['status'] == 'committed'
            and r1['legacy_ok'] and r1['r10_ok'], r1)

        # 2) R10 侧失败 → 补偿 legacy
        r2 = w.create_account('create:A02', 'A02', '双写乙', 'b' * 32,
                              fail_after=1)
        add('second_write_failure_compensated', r2['status'] == 'compensated', r2)

        # 3) 补偿失败 → 持久化队列 → 重放收敛
        r3 = w.create_account('create:A03', 'A03', '双写丙', 'c' * 32,
                              fail_after=1, fail_compensation=True)
        add('compensation_failure_queued',
            r3['status'] == 'compensation_pending', r3)
        with w.r10.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pmr_compensation_queue "
                        "WHERE status='pending'")
            queued = cur.fetchone()[0]
        add('queue_persisted', queued >= 1, {'queued': queued})
        replay = w.replay_compensation()
        add('compensation_replayed', bool(replay['resolved']) and not replay['failed'],
            replay)
        add('no_residue_after_replay',
            not w._legacy_row_exists('A03') if hasattr(w, '_legacy_row_exists') else
            w.drift()['drift_count'] == 0, w.drift())

        # 4) 幂等重放
        r4 = w.create_account('create:A01', 'A01', '双写甲', 'a' * 32)
        add('idempotent_replay', r4.get('idempotent_replay') is True, r4)

        # 5) 进程异常退出（写完 legacy 后 kill）
        if child:
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), '--child-write',
                 '--legacy-db', legacy_db, '--r10-db', r10_db,
                 '--legacy-id', 'K01'],
                env=os.environ.copy(), check=False,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            drift = w.drift()
            add('kill_detected_drift', 'pmr-k01' in drift['legacy_only'], drift)
            repaired = w.repair_drift()
            add('kill_drift_repaired', repaired['drift_after'] == 0, repaired)

        # 6) 不确定提交（两侧提交后进程退出，未写日志）→ 重启后按实际状态判定
        if child:
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), '--child-write',
                 '--legacy-db', legacy_db, '--r10-db', r10_db,
                 '--legacy-id', 'A06', '--after', 'r10'],
                env=os.environ.copy(), check=False,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        resolved = w.resolve_unknown('create:A06', 'A06', think_committed=True)
        add('unknown_commit_resolved_as_committed',
            resolved['status'] == 'committed', resolved)

        # 7) 最终一致性
        final = w.drift()
        add('final_zero_drift', final['drift_count'] == 0, final)
    finally:
        w.close()

    return {'legacy_db': legacy_db, 'r10_db': r10_db,
            'checks': checks, 'ok': all(c['ok'] for c in checks)}


def main() -> int:
    ap = argparse.ArgumentParser(description='S05 跨库双写仿真')
    ap.add_argument('--legacy-db', default='')
    ap.add_argument('--r10-db', default='')
    ap.add_argument('--scenario', default='all')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--keep', action='store_true', help='保留演练库')
    ap.add_argument('--child-write', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--legacy-id', default='K01', help=argparse.SUPPRESS)
    ap.add_argument('--after', default='legacy', help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child_write:
        child_write(args.legacy_db, args.r10_db, 'child', args.legacy_id,
                    after=args.after)
        return 0

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 DB_PASSWORD 或 SMASS_DB_PASSWORD 环境变量')

    legacy_db, r10_db = args.legacy_db, args.r10_db
    created = False
    if not legacy_db or not r10_db:
        legacy_db, r10_db = make_pair()
        created = True

    guard(legacy_db, LEGACY_PREFIX)
    guard(r10_db, R10_PREFIX)
    create_db(legacy_db)
    create_db(r10_db)

    report = scenario_all(legacy_db, r10_db)

    out = Path(os.environ.get('TEMP', '.')) / 'pmr_cross_db'
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / 's05_{}.json'.format(datetime.now().strftime('%Y%m%d_%H%M%S'))
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    report['manifest_path'] = str(manifest)

    if created and not args.keep:
        drop_db(legacy_db)
        drop_db(r10_db)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report['checks']:
            print('{} {} {}'.format('PASS' if item['ok'] else 'FAIL',
                                    item['check'], item['detail']))
        print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
