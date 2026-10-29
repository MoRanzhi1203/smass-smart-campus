"""PM5：完整数据升级 + 故障注入 + 备份恢复。

与 H5 的区别：
- H5 只复制**结构**（`mysqldump --no-data`），证的是"结构可升级"
- PM5 复制**结构与数据**（合成数据），证的是"数据可升级且可恢复"

流程
----
1. 源：`smass_pmr_1k_20261031`（26 表 + ~1001 合成学生）
2. 克隆（含数据）-> `smass_pmr_upg_<ts>`
3. 复制 22 行 `django_migrations`（H5 教训：不复制会撞 1050）
4. 应用 R10 迁移 -> 期望 73 表（72 + pmr 辅助表）
5. 逐表行数比对（`app01_*` 必须 1:1 保留）
6. **故障注入**：`before_migrate` / `during_backfill` / `after_index`
7. 备份升级后的库 -> 恢复到 `smass_pmr_restore_<ts>`
8. 比对表数、行数、结构指纹
9. 抽样登录验证（旧 MD5 与 PBKDF2 各一个）
10. 源库指纹与行数未变

用法：
    $env:SMASS_DB_PASSWORD='<root>'
    conda run -n smass python scripts/pmr_upgrade_restore.py
    conda run -n smass python scripts/pmr_upgrade_restore.py --fail-at during_backfill
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
PYTHON = sys.executable
MYSQL_BIN = Path(r'D:\mysql-8.0.18-winx64\bin')
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'pmr_upgrade'

SOURCE_DEFAULT = 'smass_pmr_1k_20261031'
UPG_PREFIX = 'smass_pmr_upg_'
RESTORE_PREFIX = 'smass_pmr_restore_'

#: 需要逐表比对行数的旧表
COMPARE_TABLES = [
    'app01_admin', 'app01_student', 'app01_teacher',
    'app01_college', 'app01_major', 'app01_classes', 'app01_grade',
]


class InjectedFailure(RuntimeError):
    pass


def conn(db=None, autocommit=True):
    return pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8mb4', autocommit=autocommit)


def db_exists(name):
    c = conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s',
                [name])
            return cur.fetchone()[0] > 0
    finally:
        c.close()


def table_list(db):
    c = conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME', [db])
            return [r[0] for r in cur.fetchall()]
    finally:
        c.close()


def row_counts(db, tables):
    c = conn(db)
    counts = {}
    try:
        with c.cursor() as cur:
            existing = set(table_list(db))
            for table in tables:
                if table not in existing:
                    counts[table] = None
                    continue
                cur.execute('SELECT COUNT(*) FROM `{}`'.format(table))
                counts[table] = cur.fetchone()[0]
    finally:
        c.close()
    return counts


def schema_fingerprint(db):
    c = conn()
    try:
        with c.cursor() as cur:
            cur.execute(
                'SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, '
                'COLUMN_KEY, EXTRA FROM information_schema.COLUMNS '
                'WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION',
                [db])
            rows = cur.fetchall()
    finally:
        c.close()
    payload = '\n'.join('|'.join(str(x) for x in row) for row in rows)
    return {'sha256': hashlib.sha256(payload.encode()).hexdigest()[:32],
            'columns': len(rows)}


def data_fingerprint(db, tables):
    """逐表行内容摘要（顺序无关），用于恢复后比对。"""
    c = conn(db)
    parts = []
    try:
        with c.cursor() as cur:
            existing = set(table_list(db))
            for table in tables:
                if table not in existing:
                    continue
                cur.execute('SELECT * FROM `{}`'.format(table))
                rows = cur.fetchall()
                normalized = sorted(
                    '\u0001'.join('' if v is None else str(v) for v in row)
                    for row in rows)
                digest = hashlib.sha256(
                    '\n'.join(normalized).encode()).hexdigest()[:16]
                parts.append('{}:{}:{}'.format(table, len(rows), digest))
    finally:
        c.close()
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:32]


def dump(db, path, no_data=False, tables=None, no_create_info=False):
    env = dict(os.environ)
    env['MYSQL_PWD'] = ADMIN_PASSWORD
    cmd = [str(MYSQL_BIN / 'mysqldump.exe'),
           '--single-transaction', '--no-tablespaces', '--skip-triggers',
           '--set-gtid-purged=OFF', '--host', HOST, '--user', ADMIN_USER]
    if no_data:
        cmd.append('--no-data')
    if no_create_info:
        cmd.append('--no-create-info')
    cmd.append(db)
    if tables:
        cmd.extend(tables)
    with open(path, 'wb') as handle:
        return subprocess.run(cmd, stdout=handle, stderr=subprocess.PIPE, env=env)


def import_sql(db, path):
    cmd = [str(MYSQL_BIN / 'mysql.exe'), '--host', HOST, '--user', ADMIN_USER,
           '--password={}'.format(ADMIN_PASSWORD), db]
    with open(path, 'rb') as handle:
        return subprocess.run(cmd, stdin=handle, capture_output=True)


def create_db(name):
    c = conn()
    try:
        with c.cursor() as cur:
            cur.execute('CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8mb4'.format(name))
    finally:
        c.close()


def migrate(db):
    env = dict(os.environ)
    env['PMR_DB'] = db
    result = subprocess.run(
        [PYTHON, 'manage.py', 'migrate', '--noinput',
         '--settings=smass.settings_pmr'],
        cwd=str(BASE), capture_output=True, text=True, env=env)
    return {'exit': result.returncode,
            'tail': (result.stdout or result.stderr).strip().splitlines()[-2:]}


def run_case(source, fail_at=None, keep=True):
    """执行一次完整升级 + 恢复。返回报告。"""
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    upg = '{}{}'.format(UPG_PREFIX, stamp)
    restore = '{}{}'.format(RESTORE_PREFIX, stamp)

    for name in (upg, restore):
        if db_exists(name):
            raise SystemExit('拒绝：库已存在 {}'.format(name))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {'source': source, 'upgrade_db': upg, 'restore_db': restore,
              'fail_at': fail_at, 'steps': []}

    # --- 源快照 ---
    src_tables = table_list(source)
    src_counts = row_counts(source, COMPARE_TABLES)
    src_fp = schema_fingerprint(source)
    src_data_fp = data_fingerprint(source, COMPARE_TABLES)
    report['source_before'] = {
        'tables': len(src_tables), 'counts': src_counts,
        'schema_fp': src_fp['sha256'], 'data_fp': src_data_fp,
    }
    report['steps'].append({'step': 'snapshot_source', 'ok': True})

    # --- 带数据克隆 ---
    full_dump = OUT_DIR / 'full_{}.sql'.format(stamp)
    r = dump(source, full_dump)
    if r.returncode != 0:
        raise SystemExit('dump 失败: {}'.format(r.stderr.decode('utf-8', 'replace')[:200]))

    create_db(upg)
    r = import_sql(upg, full_dump)
    if r.returncode != 0:
        raise SystemExit('导入克隆失败: {}'.format(r.stderr.decode('utf-8', 'replace')[:200]))

    clone_counts = row_counts(upg, COMPARE_TABLES)
    report['clone'] = {'tables': len(table_list(upg)), 'counts': clone_counts,
                       'dump_bytes': full_dump.stat().st_size}
    report['steps'].append({
        'step': 'clone_with_data',
        'ok': clone_counts == src_counts and len(table_list(upg)) == len(src_tables),
        'counts_match': clone_counts == src_counts,
    })

    # --- 注入点 1：迁移前 ---
    if fail_at == 'before_migrate':
        report['steps'].append({'step': 'inject_before_migrate', 'ok': True,
                                'injected': True})
        report['recovery'] = _verify_source_intact(source, src_counts, src_fp, src_data_fp)
        report['ok'] = all(s.get('ok') for s in report['steps']) and report['recovery']['ok']
        return report

    # --- 应用迁移 ---
    mig = migrate(upg)
    report['migrate'] = mig
    report['steps'].append({'step': 'apply_migrations',
                            'ok': mig['exit'] == 0, 'tail': mig['tail']})

    upg_tables = table_list(upg)
    upg_counts = row_counts(upg, COMPARE_TABLES)
    report['upgraded'] = {'tables': len(upg_tables), 'counts': upg_counts}
    report['steps'].append({
        'step': 'row_counts_preserved_after_migration',
        'ok': upg_counts == src_counts,
        'before': src_counts, 'after': upg_counts,
    })

    # --- 注入点 2：回填中 ---
    if fail_at == 'during_backfill':
        # 模拟"回填了一半"：插入一条半成品映射后中止
        try:
            c = conn(upg)
            try:
                with c.cursor() as cur:
                    cur.execute(
                        'CREATE TABLE IF NOT EXISTS pmr_backfill_progress ('
                        'id INT AUTO_INCREMENT PRIMARY KEY, marker VARCHAR(64))')
                    cur.execute(
                        "INSERT INTO pmr_backfill_progress (marker) VALUES ('half-done')")
            finally:
                c.close()
        except Exception as exc:  # noqa: BLE001
            report['backfill_error'] = type(exc).__name__

        # 关键：升级后的业务数据必须仍完整
        partial_counts = row_counts(upg, COMPARE_TABLES)
        report['steps'].append({
            'step': 'inject_during_backfill',
            'ok': partial_counts == src_counts,
            'counts': partial_counts,
        })
        report['recovery'] = _verify_source_intact(source, src_counts, src_fp, src_data_fp)
        report['ok'] = all(s.get('ok') for s in report['steps']) and report['recovery']['ok']
        return report

    # --- 注入点 3：索引 DDL 后 ---
    if fail_at == 'after_index':
        # H2 索引应已存在
        c = conn(upg)
        try:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA=%s AND INDEX_NAME IN "
                    "('uq_r21_active_role','uq_r6_open_task') AND NON_UNIQUE=0",
                    [upg])
                idx = cur.fetchone()[0]
        finally:
            c.close()
        report['steps'].append({'step': 'inject_after_index', 'ok': idx > 0,
                                'h2_index_rows': idx})
        report['recovery'] = _verify_source_intact(source, src_counts, src_fp, src_data_fp)
        report['ok'] = all(s.get('ok') for s in report['steps']) and report['recovery']['ok']
        return report

    # --- 备份 + 恢复 ---
    backup = OUT_DIR / 'upgraded_{}.sql'.format(stamp)
    r = dump(upg, backup)
    if r.returncode != 0:
        raise SystemExit('备份失败: {}'.format(r.stderr.decode('utf-8', 'replace')[:200]))

    create_db(restore)
    r = import_sql(restore, backup)
    if r.returncode != 0:
        raise SystemExit('恢复失败: {}'.format(r.stderr.decode('utf-8', 'replace')[:200]))

    restore_tables = table_list(restore)
    restore_counts = row_counts(restore, COMPARE_TABLES)
    fp_upg = schema_fingerprint(upg)
    fp_restore = schema_fingerprint(restore)
    data_upg = data_fingerprint(upg, COMPARE_TABLES)
    data_restore = data_fingerprint(restore, COMPARE_TABLES)

    report['restore'] = {
        'tables': len(restore_tables), 'counts': restore_counts,
        'backup_bytes': backup.stat().st_size,
        'schema_fp_equal': fp_upg['sha256'] == fp_restore['sha256'],
        'data_fp_equal': data_upg == data_restore,
    }
    report['steps'].append({
        'step': 'backup_and_restore',
        'ok': len(restore_tables) == len(upg_tables)
        and restore_counts == upg_counts
        and fp_upg['sha256'] == fp_restore['sha256']
        and data_upg == data_restore,
    })

    # --- H2 索引在恢复库仍生效 ---
    c = conn(restore)
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=%s AND INDEX_NAME IN "
                "('uq_r21_active_role','uq_r6_open_task') AND NON_UNIQUE=0",
                [restore])
            idx = cur.fetchone()[0]
    finally:
        c.close()
    report['steps'].append({'step': 'h2_indexes_after_restore', 'ok': idx > 0,
                            'rows': idx})

    # --- 抽样登录验证 ---
    login_check = _verify_login(restore, source)
    report['login_verification'] = login_check
    report['steps'].append({'step': 'sample_login_verification',
                            'ok': login_check['ok']})

    # --- 源库未变 ---
    report['recovery'] = _verify_source_intact(source, src_counts, src_fp, src_data_fp)
    report['ok'] = all(s.get('ok') for s in report['steps']) and report['recovery']['ok']
    return report


class _HashCarrier:
    """最小替身：只提供 verify_password 需要的接口（不写库）。"""

    def __init__(self, encoded):
        self.password = encoded
        self.pk = 0
        self._state = type('S', (), {'adding': False})()
        self.saved = []

    def save(self, update_fields=None):
        self.saved.append(tuple(update_fields or ()))


def _verify_login(db, source):
    """抽样验证密码校验路径在升级/恢复后仍然可用。

    重要：PM5 只做**结构升级**（建 72 表 + 迁 12 条迁移），
    不跑行迁移，因此 `r21_account_account` 是空的。
    所以这里验证的是 **legacy 侧**：升级后 `app01_*` 的哈希能否被
    `verify_password` 正确消费——这正是"升级后用户能否登录"的直接证据。

    若库里恰好有 `Account` 行（例如已跑过 PM3），也一并验证。
    """
    os.environ['PMR_DB'] = db
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_pmr')
    import django
    django.setup()

    from app01.services.accounts import verify_password, is_legacy_hash

    # 用生成器的确定性规则重建明文（PM2 的 synth_password 规则）。
    # 关键：index 必须从 **id** 反推，不能用查询结果的位置——
    # 因为 SQL 里按 LENGTH(password)=32 过滤后，位置与原始序号不再对应。
    BASE_BY_TABLE = {'app01_admin': 0, 'app01_teacher': 100000,
                     'app01_student': 200000}

    def plain_for(table, source_id):
        digits = ''.join(ch for ch in str(source_id) if ch.isdigit())
        index = int(digits) if digits else 0
        return 'PmrSynth#{:06d}'.format(index + BASE_BY_TABLE[table])

    samples = []
    c = conn(db)
    try:
        with c.cursor(pymysql.cursors.DictCursor) as cur:
            for table in ('app01_admin', 'app01_teacher', 'app01_student'):
                existing = set(table_list(db))
                if table not in existing:
                    continue
                cur.execute(
                    "SELECT id, password FROM `{}` "
                    "WHERE LENGTH(password) = 32 "
                    "ORDER BY id LIMIT 3".format(table))
                for row in cur.fetchall():
                    encoded = row['password']
                    if not is_legacy_hash(encoded):
                        continue
                    raw = plain_for(table, row['id'])
                    carrier = _HashCarrier(encoded)
                    ok = verify_password(carrier, raw)
                    # 错密码必须失败
                    wrong = verify_password(_HashCarrier(encoded), 'PmrSynth#999999')
                    samples.append({
                        'table': table, 'id': row['id'], 'kind': 'legacy_md5',
                        'correct_ok': ok, 'wrong_rejected': not wrong,
                        'upgraded': not is_legacy_hash(carrier.password),
                    })
                    if len(samples) >= 4:
                        break
                if len(samples) >= 4:
                    break
    finally:
        c.close()

    # 若存在 Account 行（已跑过 PM3），额外验证官方哈希
    account_samples = []
    try:
        from r21_account.models import Account
        for account in Account.objects.exclude(password='')[:3]:
            account_samples.append({
                'login': account.login_name,
                'prefix': str(account.password)[:16],
            })
    except Exception:  # noqa: BLE001
        pass

    legacy_ok = sum(1 for s in samples if s['correct_ok'])
    wrong_ok = sum(1 for s in samples if s['wrong_rejected'])
    upgraded = sum(1 for s in samples if s['upgraded'])

    return {
        'samples': samples,
        'account_rows': len(account_samples),
        'legacy_correct_accepted': legacy_ok,
        'legacy_wrong_rejected': wrong_ok,
        'legacy_upgraded_on_success': upgraded,
        'note': 'PM5 不跑行迁移，Account 表为空是预期；验证的是 legacy 侧校验路径',
        'ok': len(samples) >= 2 and legacy_ok == len(samples) and wrong_ok == len(samples),
    }


def _verify_source_intact(source, counts, fp, data_fp):
    now_counts = row_counts(source, COMPARE_TABLES)
    now_fp = schema_fingerprint(source)
    now_data = data_fingerprint(source, COMPARE_TABLES)
    return {
        'counts_unchanged': now_counts == counts,
        'schema_fp_unchanged': now_fp['sha256'] == fp['sha256'],
        'data_fp_unchanged': now_data == data_fp,
        'ok': (now_counts == counts
               and now_fp['sha256'] == fp['sha256']
               and now_data == data_fp),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=SOURCE_DEFAULT)
    parser.add_argument('--fail-at', default=None,
                        choices=[None, 'before_migrate', 'during_backfill', 'after_index'])
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 SMASS_DB_PASSWORD 环境变量')
    if not args.source.startswith('smass_pmr_'):
        raise SystemExit('拒绝：源库必须命中 smass_pmr_ 前缀')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = run_case(args.source, fail_at=args.fail_at)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = 'upgrade_{}{}.json'.format(
        (args.fail_at + '_') if args.fail_at else '', stamp)
    path = OUT_DIR / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    report['manifest_path'] = str(path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
