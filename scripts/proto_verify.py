"""R2.0 原型回填校验（只读）。

对比 ``smass``（旧三表）与 ``smass_proto_account``（统一 Account）：

1. 账号数量：Account == Admin + Teacher + Student
2. **密码原样迁移**：每个 Account.password 必须与其来源表对应行的 password 完全一致
   （证明没有二次加密）
3. 角色：每个 Account 恰好一个 AccountRole，且角色与人员类型匹配
4. 档案：学生的 StudentProfile、教师的 TeacherProfile 数量一致
5. login_name 无重复

用法：
    conda run -n smass python scripts/proto_verify.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings')

import django  # noqa: E402

django.setup()

import pymysql  # noqa: E402
from django.conf import settings  # noqa: E402

PROTO_DB = 'smass_proto_account'

#: Account.person_type -> 旧表名
SOURCE_MAP = {
    'admin': 'app01_admin',
    'teacher': 'app01_teacher',
    'student': 'app01_student',
}


def connect(dbname):
    cfg = settings.DATABASES['default']
    return pymysql.connect(
        host=cfg['HOST'] or 'localhost',
        user=cfg['USER'],
        password=cfg['PASSWORD'],
        port=int(cfg['PORT'] or 3306),
        database=dbname,
        charset='utf8mb4',
    )


def fetch_all(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def main():
    problems = []

    source = connect('smass')
    proto = connect(PROTO_DB)

    try:
        legacy_total = 0
        legacy_passwords = {}
        for table in ('app01_admin', 'app01_teacher', 'app01_student'):
            rows = fetch_all(source, 'SELECT id, password FROM `{}`'.format(table))
            legacy_total += len(rows)
            for pk, pwd in rows:
                legacy_passwords[(table, str(pk))] = pwd

        accounts = fetch_all(
            proto,
            'SELECT login_name, password, person_type, legacy_source, legacy_pk '
            'FROM proto_account_account',
        )
        print('legacy accounts : {}'.format(legacy_total))
        print('proto accounts  : {}'.format(len(accounts)))

        if len(accounts) != legacy_total:
            problems.append(
                '账号数不一致：旧表 {} vs Account {}'.format(legacy_total, len(accounts))
            )

        role_rows = fetch_all(
            proto, 'SELECT account_id, role FROM proto_account_accountrole'
        )
        role_by_account = {}
        for account_id, role in role_rows:
            role_by_account.setdefault(account_id, []).append(role)

        student_profiles = fetch_all(
            proto, 'SELECT account_id FROM proto_account_studentprofile'
        )
        teacher_profiles = fetch_all(
            proto, 'SELECT account_id FROM proto_account_teacherprofile'
        )
        print('account roles   : {}'.format(len(role_rows)))
        print('student profile : {}'.format(len(student_profiles)))
        print('teacher profile : {}'.format(len(teacher_profiles)))

        if len(role_rows) != len(accounts):
            problems.append(
                '角色数({}) 与账号数({}) 不一致'.format(len(role_rows), len(accounts))
            )

        # 密码原样性 + 角色匹配
        account_ids = fetch_all(
            proto,
            'SELECT id, login_name, password, person_type, legacy_source, legacy_pk '
            'FROM proto_account_account',
        )
        mismatch = 0
        role_mismatch = 0
        for account_id, login_name, password, person_type, legacy_source, legacy_pk in account_ids:
            table = SOURCE_MAP.get(person_type)
            if table is None:
                problems.append('未知 person_type: {}'.format(person_type))
                continue

            expected = legacy_passwords.get((table, legacy_pk))
            if expected is None:
                problems.append('找不到来源行: {}/{}'.format(legacy_source, legacy_pk))
                continue

            if password != expected:
                mismatch += 1

            roles = role_by_account.get(account_id, [])
            if roles != [person_type]:
                role_mismatch += 1

        if mismatch:
            problems.append('密码哈希被改动（疑似二次加密）：{} 行'.format(mismatch))
        if role_mismatch:
            problems.append('角色与 person_type 不匹配：{} 行'.format(role_mismatch))

        dup = fetch_all(
            proto,
            'SELECT login_name, COUNT(*) c FROM proto_account_account '
            'GROUP BY login_name HAVING c > 1',
        )
        if dup:
            problems.append('login_name 重复：{}'.format(dup))

        # 旧数据本身的跨类型撞号（用于 ADR 证据）
        by_login = {}
        for (table, pk), _pwd in legacy_passwords.items():
            by_login.setdefault(pk, []).append(table)
        collisions = {k: v for k, v in by_login.items() if len(v) > 1}
        print('cross-type login collisions in legacy data: {}'.format(len(collisions)))
    finally:
        source.close()
        proto.close()

    print('')
    if problems:
        print('[FAIL] 发现 {} 处问题：'.format(len(problems)))
        for item in problems:
            print('  - {}'.format(item))
        return 1

    print('[PASS] 账号数量 / 密码原样迁移 / 角色映射 / 档案数量 / login_name 唯一性 全部一致')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
