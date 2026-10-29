"""PM2：合成旧数据集生成器（schema-compatible / adversarial / 无 PII）。

设计要点
--------
1. **形状真实**：从 `smass` 只导出**结构**（`mysqldump --no-data`），不复制任何行。
2. **内容全合成**：姓名、证件号、手机号均由确定性生成器产出，
   且刻意使用**明显非真实**的格式（`SYNTH...`），避免任何被误认为真实 PII 的可能。
3. **密码三态**：单次 MD5 / 双重 MD5 / PBKDF2，全部现场用合成明文计算。
4. **对抗用例**：空哈希、31 位哈希、大写哈希、重复学号、孤儿班级引用。
5. **确定性**：同一 seed 产出同一内容（用 `random.Random(seed)`，不用全局 random）。
6. **前缀守卫**：库名必须 `smass_pmr_` 开头且不存在，否则拒绝。

用法：
    $env:SMASS_DB_PASSWORD='<root>'
    conda run -n smass python scripts/pmr_synthetic_fixture.py --scale tiny
    conda run -n smass python scripts/pmr_synthetic_fixture.py --scale 1k --seed 20261031
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# 仅加载 Django 配置以便使用 make_password；本脚本不通过 ORM 访问数据库。
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r10')
import django  # noqa: E402

django.setup()

HOST = 'localhost'
ADMIN_USER = 'root'
ADMIN_PASSWORD = os.environ.get('SMASS_DB_PASSWORD', '')
MYSQL_BIN = Path(r'D:\mysql-8.0.18-winx64\bin')
OUT_DIR = Path(os.environ.get('TEMP', '.')) / 'pmr_fixtures'

SOURCE_DB = 'smass'
DB_PREFIX = 'smass_pmr_'

#: 旧密钥（与 app01/services/accounts.py 一致；仅用于生成合成旧哈希）
LEGACY_MD5_SECRET_KEY = (
    'django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE')

SCALES = {
    'tiny': 10,
    'medium': 100,
    '1k': 1000,
    '10k': 10000,
}

#: 密码格式分布（按比例分配）
FORMAT_WEIGHTS = [
    ('legacy_md5_single', 0.50),
    ('legacy_md5_double', 0.20),
    ('pbkdf2', 0.30),
]

#: 对抗用例（在 SQL 层批量插入后单独补）
ADVERSARIAL_CASES = [
    ('empty_hash', ''),
    ('short_hash', 'a' * 31),
    ('long_hash', 'a' * 33),
    ('uppercase_hash', 'A' * 32),
    ('non_hex_hash', 'z' * 32),
]


def legacy_md5(raw, secret=LEGACY_MD5_SECRET_KEY):
    return hashlib.md5(secret.encode('utf-8') + raw.encode('utf-8')).hexdigest()


def pbkdf2(raw):
    from django.contrib.auth.hashers import make_password
    return make_password(raw)


def guard_db_name(name):
    if not name.startswith(DB_PREFIX):
        raise SystemExit('拒绝：库名必须命中 {}，当前 {!r}'.format(DB_PREFIX, name))


def db_exists(name):
    conn = pymysql.connect(host=HOST, user=ADMIN_USER,
                           password=ADMIN_PASSWORD, charset='utf8mb4')
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s',
                [name])
            return cur.fetchone()[0] > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 合成内容生成（确定性，且明显非真实）
# ---------------------------------------------------------------------------
SURNAME_POOL = ['赵', '钱', '孙', '李', '周', '吴', '郑', '王', '冯', '陈']
GIVEN_POOL = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']


def synth_name(rng, index):
    """合成姓名：姓氏池 + 天干，带序号后缀，明确可辨为合成。"""
    return '{}{}{:04d}'.format(
        SURNAME_POOL[index % len(SURNAME_POOL)],
        GIVEN_POOL[(index // len(SURNAME_POOL)) % len(GIVEN_POOL)],
        index)


def synth_card_id(index):
    """合成证件号：**刻意**不是 18 位身份证格式，避免被误认。"""
    return 'SYNTH{:013d}'.format(index)


def synth_phone(index):
    """合成手机号：以 000 开头，真实号码不会出现。"""
    return '000{:08d}'.format(index)


def synth_password(index):
    """合成明文密码（仅用于计算哈希，不落库）。"""
    return 'PmrSynth#{:06d}'.format(index)


def pick_format(rng):
    threshold = rng.random()
    cumulative = 0.0
    for name, weight in FORMAT_WEIGHTS:
        cumulative += weight
        if threshold <= cumulative:
            return name
    return FORMAT_WEIGHTS[-1][0]


def encode_password(raw, fmt):
    if fmt == 'legacy_md5_single':
        return legacy_md5(raw)
    if fmt == 'legacy_md5_double':
        return legacy_md5(legacy_md5(raw))
    return pbkdf2(raw)


# ---------------------------------------------------------------------------
# 结构复制
# ---------------------------------------------------------------------------
def dump_schema(out_path):
    env = dict(os.environ)
    env['MYSQL_PWD'] = ADMIN_PASSWORD
    cmd = [str(MYSQL_BIN / 'mysqldump.exe'),
           '--single-transaction', '--no-tablespaces', '--skip-triggers',
           '--set-gtid-purged=OFF', '--no-data',
           '--host', HOST, '--user', ADMIN_USER, SOURCE_DB]
    with open(out_path, 'wb') as handle:
        result = subprocess.run(cmd, stdout=handle, stderr=subprocess.PIPE, env=env)
    return result


def dump_migrations(out_path):
    env = dict(os.environ)
    env['MYSQL_PWD'] = ADMIN_PASSWORD
    cmd = [str(MYSQL_BIN / 'mysqldump.exe'),
           '--single-transaction', '--no-tablespaces', '--skip-triggers',
           '--set-gtid-purged=OFF', '--no-create-info',
           '--host', HOST, '--user', ADMIN_USER, SOURCE_DB, 'django_migrations']
    with open(out_path, 'wb') as handle:
        result = subprocess.run(cmd, stdout=handle, stderr=subprocess.PIPE, env=env)
    return result


def import_sql(db, path):
    cmd = [str(MYSQL_BIN / 'mysql.exe'), '--host', HOST, '--user', ADMIN_USER,
           '--password={}'.format(ADMIN_PASSWORD), db]
    with open(path, 'rb') as handle:
        return subprocess.run(cmd, stdin=handle, capture_output=True)


# ---------------------------------------------------------------------------
# 填充
# ---------------------------------------------------------------------------
def populate(db, seed, count):
    rng = random.Random(seed)
    conn = pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db, charset='utf8mb4')
    stats = {'admin': 0, 'student': 0, 'teacher': 0, 'classes': 0,
             'college': 0, 'major': 0, 'adversarial': 0}
    format_counts = {}
    checksum_parts = []
    md5_parts = []

    try:
        with conn.cursor() as cur:
            cur.execute('SET FOREIGN_KEY_CHECKS=0')

            # 院系 / 专业 / 班级（层级）
            colleges = max(2, count // 50)
            for i in range(colleges):
                cur.execute(
                    'INSERT INTO app01_college (name) VALUES (%s)',
                    ['合成学院{:02d}'.format(i)])
                stats['college'] += 1
            cur.execute('SELECT id FROM app01_college ORDER BY id')
            college_ids = [r[0] for r in cur.fetchall()]

            majors = max(2, count // 25)
            for i in range(majors):
                cur.execute(
                    'INSERT INTO app01_major (name, college_id) VALUES (%s, %s)',
                    ['合成专业{:03d}'.format(i), college_ids[i % len(college_ids)]])
                stats['major'] += 1
            cur.execute('SELECT id FROM app01_major ORDER BY id')
            major_ids = [r[0] for r in cur.fetchall()]

            # 年级
            cur.execute('INSERT INTO app01_grade (name) VALUES (%s)', ['2026级'])
            cur.execute('SELECT LAST_INSERT_ID()')
            grade_id = cur.fetchone()[0]

            classes = max(2, count // 20)
            for i in range(classes):
                cur.execute(
                    'INSERT INTO app01_classes (name, grade_id, major_id) VALUES (%s, %s, %s)',
                    ['合成班级{:04d}'.format(i), grade_id,
                     major_ids[i % len(major_ids)]])
                stats['classes'] += 1
            cur.execute('SELECT id FROM app01_classes ORDER BY id')
            class_ids = [r[0] for r in cur.fetchall()]

            # ---- admin ----
            admin_rows = []
            admin_count = max(1, count // 100)
            for i in range(admin_count):
                raw = synth_password(i)
                fmt = pick_format(rng)
                encoded = encode_password(raw, fmt)
                format_counts[fmt] = format_counts.get(fmt, 0) + 1
                account_id = 'A{:02d}'.format(i)
                # 确定性指纹：用 (id, format, raw) —— **不含 encoded**，
                # 因为 PBKDF2 的 salt 随机，encoded 本身不可复现。
                check = hashlib.sha256(
                    '{}|{}|{}'.format(account_id, fmt, raw).encode()).hexdigest()[:16]
                checksum_parts.append(check)
                # MD5 行额外记 encoded 指纹（这部分是确定的）
                if fmt.startswith('legacy_md5'):
                    md5_parts.append(hashlib.sha256(
                        '{}|{}'.format(account_id, encoded).encode()).hexdigest()[:16])
                admin_rows.append((account_id, synth_name(rng, i), encoded))

            cur.executemany(
                'INSERT INTO app01_admin (id, name, password) VALUES (%s, %s, %s)',
                admin_rows)
            stats['admin'] = len(admin_rows)

            # ---- teacher ----
            teacher_rows = []
            teacher_count = max(1, count // 40)
            for i in range(teacher_count):
                raw = synth_password(i + 100000)
                fmt = pick_format(rng)
                encoded = encode_password(raw, fmt)
                format_counts[fmt] = format_counts.get(fmt, 0) + 1
                account_id = 'T{:06d}'.format(i)
                check = hashlib.sha256(
                    '{}|{}|{}'.format(account_id, fmt, raw).encode()).hexdigest()[:16]
                checksum_parts.append(check)
                if fmt.startswith('legacy_md5'):
                    md5_parts.append(hashlib.sha256(
                        '{}|{}'.format(account_id, encoded).encode()).hexdigest()[:16])
                teacher_rows.append((
                    account_id, synth_name(rng, i + 1000), encoded,
                    1, synth_card_id(i), synth_phone(i), synth_phone(i),
                    '合成地址{:04d}'.format(i), date(2020, 9, 1), 1,
                    college_ids[i % len(college_ids)],
                ))

            cur.executemany(
                'INSERT INTO app01_teacher '
                '(id, name, password, sex, cardID, phone, qq, address, '
                ' entry_time, political, college_id) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                teacher_rows)
            stats['teacher'] = len(teacher_rows)

            # ---- student ----
            student_rows = []
            for i in range(count):
                raw = synth_password(i + 200000)
                fmt = pick_format(rng)
                encoded = encode_password(raw, fmt)
                format_counts[fmt] = format_counts.get(fmt, 0) + 1
                account_id = 'S{:09d}'.format(i)
                check = hashlib.sha256(
                    '{}|{}|{}'.format(account_id, fmt, raw).encode()).hexdigest()[:16]
                checksum_parts.append(check)
                if fmt.startswith('legacy_md5'):
                    md5_parts.append(hashlib.sha256(
                        '{}|{}'.format(account_id, encoded).encode()).hexdigest()[:16])
                student_rows.append((
                    account_id, synth_name(rng, i + 5000), encoded,
                    1, synth_card_id(i + 5000), synth_phone(i + 5000),
                    synth_phone(i + 5000), '合成地址{:04d}'.format(i), 1,
                    class_ids[i % len(class_ids)],
                ))

            cur.executemany(
                'INSERT INTO app01_student '
                '(id, name, password, sex, cardID, phone, qq, address, '
                ' political, classes_id) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                student_rows)
            stats['student'] = len(student_rows)

            # ---- 对抗用例（混入 admin 表，避免污染主计数）----
            for idx, (label, encoded) in enumerate(ADVERSARIAL_CASES):
                account_id = 'X{:02d}'.format(idx)
                cur.execute(
                    'INSERT INTO app01_admin (id, name, password) VALUES (%s, %s, %s)',
                    (account_id, '对抗{}'.format(label), encoded))
                stats['adversarial'] += 1

            # 重复学号：先查后插（不依赖异常捕获，避免事务状态不确定性）
            duplicate_skipped = 0
            cur.execute('SELECT COUNT(*) FROM app01_student WHERE id = %s',
                        ('S000000000',))
            if cur.fetchone()[0]:
                duplicate_skipped = 1
            else:
                cur.execute(
                    'INSERT INTO app01_student (id, name, password, political, cardID) '
                    'VALUES (%s, %s, %s, %s, %s)',
                    ('S000000000', '重复学号', legacy_md5('dup'), 1,
                     'SYNTH9999999999999'))
            stats['duplicate_attempted'] = 1
            stats['duplicate_skipped'] = duplicate_skipped

            # 孤儿引用：classes_id 指向不存在的班级
            cur.execute(
                'INSERT INTO app01_student '
                '(id, name, password, political, cardID, classes_id) '
                'VALUES (%s, %s, %s, %s, %s, %s)',
                ('S999999999', '孤儿班级引用', legacy_md5('orphan'), 1,
                 'SYNTH8888888888888', 999999))
            stats['orphan_reference'] = 1

            cur.execute('SET FOREIGN_KEY_CHECKS=1')
        conn.commit()
    finally:
        conn.close()

    deterministic = hashlib.sha256(
        ''.join(sorted(checksum_parts)).encode()).hexdigest()
    md5_only = hashlib.sha256(
        ''.join(sorted(md5_parts)).encode()).hexdigest()
    return stats, format_counts, deterministic, md5_only


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scale', choices=sorted(SCALES), default='tiny')
    parser.add_argument('--seed', type=int, default=20261031)
    parser.add_argument('--db', default=None)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not ADMIN_PASSWORD:
        raise SystemExit('需要 SMASS_DB_PASSWORD 环境变量')

    count = SCALES[args.scale]
    db_name = args.db or '{}{}_{}'.format(DB_PREFIX, args.scale, args.seed)
    guard_db_name(db_name)
    if db_exists(db_name):
        raise SystemExit('拒绝：库已存在 {}（不覆盖）'.format(db_name))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = OUT_DIR / 'schema_{}.sql'.format(args.seed)
    mig_path = OUT_DIR / 'migrations_{}.sql'.format(args.seed)

    report = {'database': db_name, 'scale': args.scale, 'seed': args.seed,
              'target_rows': count, 'steps': []}

    # 1) 结构
    result = dump_schema(schema_path)
    if result.returncode != 0:
        raise SystemExit('dump 结构失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:200]))
    report['steps'].append({'step': 'dump_schema', 'ok': True,
                            'bytes': schema_path.stat().st_size})

    # 2) 建库 + 导入结构
    conn = pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           charset='utf8mb4')
    try:
        with conn.cursor() as cur:
            cur.execute('CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8mb4'.format(db_name))
        conn.commit()
    finally:
        conn.close()

    result = import_sql(db_name, schema_path)
    if result.returncode != 0:
        raise SystemExit('导入结构失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:200]))
    report['steps'].append({'step': 'import_schema', 'ok': True})

    # 3) 迁移记录（22 行，无 PII）
    result = dump_migrations(mig_path)
    if result.returncode != 0:
        raise SystemExit('dump 迁移记录失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:200]))

    result = import_sql(db_name, mig_path)
    if result.returncode != 0:
        raise SystemExit('导入迁移记录失败: {}'.format(
            result.stderr.decode('utf-8', 'replace')[:200]))
    report['steps'].append({'step': 'import_migrations', 'ok': True})

    # 4) 填充合成行
    stats, format_counts, checksum, md5_checksum = populate(db_name, args.seed, count)
    report['stats'] = stats
    report['format_distribution'] = format_counts
    report['deterministic_checksum'] = checksum
    report['md5_encoded_checksum'] = md5_checksum
    report['steps'].append({'step': 'populate_synthetic', 'ok': True})

    # 5) 验证无 PII
    conn = pymysql.connect(host=HOST, user=ADMIN_USER, password=ADMIN_PASSWORD,
                           database=db_name, charset='utf8mb4')
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM app01_student')
            students = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM app01_student WHERE cardID NOT LIKE 'SYNTH%'")
            bad_cards = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM app01_teacher WHERE phone NOT LIKE '000%'")
            bad_phones = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM django_migrations')
            migs = cur.fetchone()[0]
    finally:
        conn.close()

    report['verification'] = {
        'students': students,
        'non_synthetic_card': bad_cards,
        'non_synthetic_phone': bad_phones,
        'migrations': migs,
    }
    report['steps'].append({
        'step': 'verify_no_pii',
        'ok': bad_cards == 0 and bad_phones == 0,
        'bad_cards': bad_cards, 'bad_phones': bad_phones,
    })

    report['ok'] = all(step.get('ok') for step in report['steps'])
    report['note'] = '库不自动删除；清理需另行批准'

    manifest_path = OUT_DIR / 'manifest_{}_{}.json'.format(args.scale, args.seed)
    manifest_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    report['manifest_path'] = str(manifest_path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
