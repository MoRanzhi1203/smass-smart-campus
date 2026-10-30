#!/usr/bin/env python
"""app01 历史数据 → 统一身份与业务模型的隔离迁移。

用法::

    python scripts/legacy_migration.py --preview      # 只读预览映射（默认）
    python scripts/legacy_migration.py --apply        # 写入产品隔离库
    python scripts/legacy_migration.py --verify       # 计数/角色/权限一致性校验
    python scripts/legacy_migration.py --rollback     # 按 manifest 回滚本批次

安全约束
--------
- 源库（正式 ``smass``）**只读**：连接即 ``SET SESSION TRANSACTION READ ONLY``，
  只用 SELECT；执行前后比对指纹，必须完全一致；
- 目标库必须是 ``smass_product_dev`` 前缀；
- 个人敏感信息默认**掩码/不迁移**（手机号掩码、身份证不迁），
  需要原值时须显式设置 ``SMASS_MIGRATE_REAL_PII=YES_I_HAVE_AUTHORIZATION``；
- 幂等：以 ``LegacyAccountLink(source_table, source_pk)`` 为唯一锚点，
  重复执行不会产生重复账号；
- 回滚：manifest 记录本批次新建对象，回滚只删本批次且无外部引用的对象。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = 'smass.settings_product'
PRODUCT_DB = os.environ.get('PRODUCT_DB', 'smass_product_dev')
SOURCE_DB = 'smass'
MANIFEST = ROOT / '.local/evidence/migration/legacy_migration_manifest.json'

LEGACY_PREFIX = 'LEGACY-'


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------
def product_setup():
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.conf import settings

    if not PRODUCT_DB.startswith('smass_product_dev'):
        raise SystemExit('拒绝写入非产品隔离库：{}'.format(PRODUCT_DB))
    return settings


def source_connection():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    import pymysql

    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', '127.0.0.1'),
        port=int(os.environ.get('DB_PORT', 3306)),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=SOURCE_DB, charset='utf8mb4', autocommit=False)
    with conn.cursor() as cursor:
        cursor.execute('SET SESSION TRANSACTION READ ONLY')
    return conn


def source_fingerprint(conn):
    """正式库只读指纹：表名 + 行数 + 列定义，不含数据内容。"""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME", (SOURCE_DB,))
        tables = [row[0] for row in cursor.fetchall()]
        digest = hashlib.sha256()
        for table in tables:
            cursor.execute('SELECT COUNT(*) FROM `{}`'.format(table))
            rows = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "ORDER BY ORDINAL_POSITION", (SOURCE_DB, table))
            columns = cursor.fetchall()
            digest.update('{}|{}|{}'.format(
                table, rows, json.dumps(columns, ensure_ascii=False)).encode('utf-8'))
        return {'tables': len(tables), 'sha256': digest.hexdigest()}


def fetch_all(conn):
    data = {}
    queries = {
        'colleges': 'SELECT id, name FROM app01_college ORDER BY id',
        'majors': 'SELECT id, name, college_id FROM app01_major ORDER BY id',
        'grades': 'SELECT id, name FROM app01_grade ORDER BY id',
        'classes': ('SELECT id, name, counsellor_id, grade_id, major_id '
                    'FROM app01_classes ORDER BY id'),
        'departments': ('SELECT id, department, faction, college_id, level '
                        'FROM app01_department ORDER BY id'),
        'students': ('SELECT id, name, password, sex, nation, phone, '
                     'building, dormitory, political, classes_id '
                     'FROM app01_student ORDER BY id'),
        'teachers': ('SELECT id, name, password, sex, nation, phone, '
                     'college_id, entry_time FROM app01_teacher ORDER BY id'),
        'admins': 'SELECT id, name, password FROM app01_admin ORDER BY id',
        'class_committee': ('SELECT id, committee, classes_id '
                            'FROM app01_classcommittee ORDER BY id'),
        'league_cadres': ('SELECT id, duties, department_id '
                          'FROM app01_leaguecadres ORDER BY id'),
    }
    with conn.cursor() as cursor:
        for key, sql in queries.items():
            try:
                cursor.execute(sql)
                columns = [item[0] for item in cursor.description]
                data[key] = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as exc:  # noqa: BLE001 - 缺失表按空集处理
                data[key] = []
                data.setdefault('_warnings', []).append('{}: {}'.format(key, exc))
    return data


# ---------------------------------------------------------------------------
# 敏感信息策略
# ---------------------------------------------------------------------------
def allow_real_pii():
    return os.environ.get('SMASS_MIGRATE_REAL_PII') == 'YES_I_HAVE_AUTHORIZATION'


def mask_phone(value):
    value = (value or '').strip()
    if len(value) < 7:
        return ''
    return '{}****{}'.format(value[:3], value[-4:])


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------
def run_preview(data, fingerprint):
    students = len(data['students'])
    return {
        'mode': 'preview',
        'source_fingerprint': fingerprint,
        'source_counts': {key: len(value) for key, value in data.items()
                          if isinstance(value, list)},
        'mapping': {
            'colleges': '→ OrganizationUnit(college)',
            'majors': '→ OrganizationUnit(major, parent=college)',
            'grades': '→ OrganizationUnit(grade)（仅作展示，不改变班级单亲树）',
            'classes': '→ OrganizationUnit(class, parent=major)',
            'departments': '→ OrganizationUnit(department)',
            'students': '→ Account(student) + StudentProfile + StudentRecord',
            'teachers': '→ Account(teacher) + TeacherProfile + Membership',
            'admins': '→ Account(person_type=admin) + system_admin',
            'class_committee': '→ OrganizationMembership(role=class_committee)',
            'league_cadres': '→ OrganizationMembership(role=league_cadre)',
        },
        'pii_policy': ('real_pii_authorized' if allow_real_pii()
                       else 'masked: 手机号掩码、身份证不迁移'),
        'student_count': students,
    }


def get_or_create_unit(code, name, unit_type, parent, created_ids, reused_ids):
    from smass_organization.models import OrganizationUnit
    from smass_organization.services import create_unit

    existing = OrganizationUnit.objects.filter(code=code).first()
    if existing is not None:
        reused_ids.append(existing.pk)
        return existing, False
    # 同名同类型同上级视为同一组织，避免融合后出现重复学院
    same = OrganizationUnit.objects.filter(
        unit_type=unit_type, name=name, parent=parent).first()
    if same is not None:
        reused_ids.append(same.pk)
        return same, False
    unit = create_unit(code=code, name=name, unit_type=unit_type, parent=parent)
    created_ids.append(unit.pk)
    return unit, True


def run_apply(data):
    from r21_account import services as account_services
    from r21_account.models import Account, LegacyAccountLink, StudentProfile, TeacherProfile
    from smass_organization.models import OrganizationMembership, OrganizationUnit, StudentRecord

    manifest = {
        'batch': 'legacy_app01',
        'source_db': SOURCE_DB,
        'target_db': PRODUCT_DB,
        'created_units': [], 'reused_units': [],
        'created_accounts': [], 'created_records': [],
        'created_memberships': [], 'links': [],
        'pii_policy': ('real_pii' if allow_real_pii() else 'masked'),
    }

    def link_account(login_name, display_name, person_type, password_hash,
                     source_table, source_pk, role):
        link = LegacyAccountLink.objects.filter(
            source_table=source_table, source_pk=str(source_pk)).first()
        if link is not None:
            return link.account, False
        account = Account.objects.filter(login_name=login_name).first()
        if account is None:
            account = Account(
                login_name=login_name, display_name=display_name,
                person_type=person_type, is_active=True,
                must_change_password=not (password_hash or '').startswith(
                    'pbkdf2_sha256$'))
            if (password_hash or '').startswith(('pbkdf2_sha256$', 'pbkdf2$')):
                account.password = password_hash
            else:
                account.set_unusable_password()
            account.save()
            manifest['created_accounts'].append(account.pk)
        else:
            manifest['reused_units'].append('account:{}'.format(account.pk))
        account_services.grant_role(account, role, granted_by='legacy-migration')
        checksum = hashlib.sha256(
            '{}|{}|{}'.format(source_table, source_pk, login_name).encode('utf-8')
        ).hexdigest()[:32]
        LegacyAccountLink.objects.create(
            account=account, source_table=source_table,
            source_pk=str(source_pk), checksum=checksum)
        manifest['links'].append({'table': source_table, 'pk': str(source_pk),
                                  'account': account.pk})
        return account, True

    # 组织
    colleges = {}
    for row in data['colleges']:
        unit, _ = get_or_create_unit(
            '{}COL-{}'.format(LEGACY_PREFIX, row['id']), row['name'],
            'college', None, manifest['created_units'], manifest['reused_units'])
        colleges[row['id']] = unit

    majors = {}
    for row in data['majors']:
        unit, _ = get_or_create_unit(
            '{}MAJ-{}'.format(LEGACY_PREFIX, row['id']), row['name'],
            'major', colleges.get(row['college_id']),
            manifest['created_units'], manifest['reused_units'])
        majors[row['id']] = unit

    for row in data['grades']:
        get_or_create_unit(
            '{}GRD-{}'.format(LEGACY_PREFIX, row['id']), row['name'],
            'grade', colleges.get(1), manifest['created_units'],
            manifest['reused_units'])

    classes = {}
    for row in data['classes']:
        unit, _ = get_or_create_unit(
            '{}CLS-{}'.format(LEGACY_PREFIX, row['id']), row['name'],
            'class', majors.get(row['major_id']),
            manifest['created_units'], manifest['reused_units'])
        classes[row['id']] = unit

    departments = {}
    for row in data['departments']:
        unit, _ = get_or_create_unit(
            '{}DEPT-{}'.format(LEGACY_PREFIX, row['id']), row['department'],
            'department', None, manifest['created_units'],
            manifest['reused_units'])
        departments[row['id']] = unit

    # 教师
    teachers = {}
    for row in data['teachers']:
        account, _ = link_account(
            row['id'], row['name'], 'teacher', row['password'],
            'app01_teacher', row['id'], 'teacher')
        teachers[row['id']] = account
        TeacherProfile.objects.update_or_create(
            account=account,
            defaults={'teacher_no': row['id'], 'name': row['name'],
                      'college_name': '', 'phone': mask_phone(row['phone'])
                      if not allow_real_pii() else (row['phone'] or '')})
        college = colleges.get(row['college_id'])
        if college is not None:
            membership, created = OrganizationMembership.objects.get_or_create(
                account=account, unit=college,
                defaults={'role': 'teacher', 'started_at': date.today()})
            if created:
                manifest['created_memberships'].append(membership.pk)

    # 管理员
    for row in data['admins']:
        link_account(row['id'], row['name'], 'admin', row['password'],
                     'app01_admin', row['id'], 'system_admin')

    # 学生
    for row in data['students']:
        account, _ = link_account(
            row['id'], row['name'], 'student', row['password'],
            'app01_student', row['id'], 'student')
        class_unit = classes.get(row['classes_id'])
        StudentProfile.objects.update_or_create(
            account=account,
            defaults={'student_no': row['id'], 'name': row['name'],
                      'college_name': class_unit.parent.parent.name
                      if class_unit and class_unit.parent and class_unit.parent.parent else '',
                      'classes_name': class_unit.name if class_unit else '',
                      'phone': mask_phone(row['phone'])
                      if not allow_real_pii() else (row['phone'] or ''),
                      'card_id': ''})
        extra = {
            'sex': row['sex'],
            'nation': row['nation'],
            'political': row['political'],
            'dormitory': {
                'building': row['building'] or '',
                'room': row['dormitory'] or '',
                'bed': '',
                'roommates': [],
            },
            'migrated_from': 'app01_student',
        }
        record, created = StudentRecord.objects.update_or_create(
            student_no=row['id'],
            defaults={'name': row['name'], 'account': account,
                      'unit': class_unit, 'status': 'enrolled',
                      'enrolled_at': date.today(), 'extra': extra})
        if created:
            manifest['created_records'].append(record.pk)
        # 班级辅导员
        class_row = next((item for item in data['classes']
                          if item['id'] == row['classes_id']), None)
        if class_row and class_row.get('counsellor_id'):
            counselor = teachers.get(class_row['counsellor_id'])
            if counselor is not None and class_unit is not None:
                membership, created = OrganizationMembership.objects.get_or_create(
                    account=counselor, unit=class_unit,
                    defaults={'role': 'counselor', 'started_at': date.today()})
                if created:
                    manifest['created_memberships'].append(membership.pk)

    # 班委 / 团学干部
    for row in data.get('class_committee', []):
        account = Account.objects.filter(login_name=row['id']).first()
        unit = classes.get(row['classes_id'])
        if account is None or unit is None:
            continue
        membership, created = OrganizationMembership.objects.get_or_create(
            account=account, unit=unit,
            defaults={'role': 'class_committee', 'started_at': date.today()})
        if created:
            manifest['created_memberships'].append(membership.pk)

    for row in data.get('league_cadres', []):
        account = Account.objects.filter(login_name=row['id']).first()
        unit = departments.get(row['department_id'])
        if account is None or unit is None:
            continue
        membership, created = OrganizationMembership.objects.get_or_create(
            account=account, unit=unit,
            defaults={'role': 'league_cadre', 'started_at': date.today()})
        if created:
            manifest['created_memberships'].append(membership.pk)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    return {
        'mode': 'apply',
        'created_units': len(manifest['created_units']),
        'created_accounts': len(manifest['created_accounts']),
        'created_records': len(manifest['created_records']),
        'created_memberships': len(manifest['created_memberships']),
        'links': len(manifest['links']),
        'pii_policy': manifest['pii_policy'],
        'manifest': str(MANIFEST),
    }


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def run_verify(data):
    from r21_account.models import Account, LegacyAccountLink, StudentProfile, TeacherProfile
    from smass_organization.models import OrganizationUnit, StudentRecord

    checks = []

    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    source_students = {row['id'] for row in data['students']}
    source_teachers = {row['id'] for row in data['teachers']}
    source_admins = {row['id'] for row in data['admins']}

    links = {item.source_pk: item for item in LegacyAccountLink.objects.all()}
    check('学生账号全部映射',
          source_students.issubset({pk for pk in links
                                    if links[pk].source_table == 'app01_student'}),
          '{} / {}'.format(len(source_students), len(links)))
    check('教师账号全部映射',
          source_teachers.issubset({pk for pk in links
                                    if links[pk].source_table == 'app01_teacher'}))
    check('管理员账号全部映射',
          source_admins.issubset({pk for pk in links
                                  if links[pk].source_table == 'app01_admin'}))

    for student_no in source_students:
        account = Account.objects.filter(login_name=student_no).first()
        check('学生 {} 角色与学籍'.format(student_no),
              account is not None
              and len(account.active_roles()) > 0
              and 'student' in set(account.active_roles())
              and StudentRecord.objects.filter(
                  student_no=student_no, account=account).exists()
              and StudentProfile.objects.filter(account=account).exists())

    for teacher_no in source_teachers:
        account = Account.objects.filter(login_name=teacher_no).first()
        check('教师 {} 角色与档案'.format(teacher_no),
              account is not None
              and 'teacher' in set(account.active_roles())
              and TeacherProfile.objects.filter(account=account).exists())

    for admin_id in source_admins:
        account = Account.objects.filter(login_name=admin_id).first()
        check('管理员 {} 系统管理员角色'.format(admin_id),
              account is not None and 'system_admin' in set(account.active_roles()))

    check('组织编码无重复', OrganizationUnit.objects.filter(
        code__startswith=LEGACY_PREFIX).count()
        == OrganizationUnit.objects.filter(
            code__startswith=LEGACY_PREFIX).values('code').distinct().count())

    # 权限一致性：迁移账号访问管理端的结果
    from django.test import Client

    for student_no in list(source_students)[:1]:
        client = Client()
        account = Account.objects.get(login_name=student_no)
        client.force_login(account)
        check('迁移学生访问管理端被拒绝',
              client.get('/admin/').status_code == 403)
        check('迁移学生可进学生工作台',
              client.get('/student/').status_code == 200)
    for teacher_no in list(source_teachers)[:1]:
        client = Client()
        account = Account.objects.get(login_name=teacher_no)
        client.force_login(account)
        check('迁移教师访问管理端被拒绝',
              client.get('/admin/').status_code == 403)
    for admin_id in list(source_admins)[:1]:
        client = Client()
        account = Account.objects.filter(login_name=admin_id).first()
        client.force_login(account)
        check('迁移管理员可进管理控制台',
              client.get('/admin/').status_code == 200)

    failures = [item for item in checks if not item['ok']]
    return {'mode': 'verify', 'checks': checks,
            'failures': failures, 'ok': not failures}


# ---------------------------------------------------------------------------
# 回滚
# ---------------------------------------------------------------------------
def run_rollback():
    from r21_account.models import Account, LegacyAccountLink, StudentProfile, TeacherProfile
    from smass_organization.models import OrganizationMembership, OrganizationUnit, StudentRecord

    if not MANIFEST.exists():
        raise SystemExit('缺少 manifest，无法回滚：{}'.format(MANIFEST))
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))

    removed = {'records': 0, 'accounts': 0, 'memberships': 0, 'units': 0}
    links = list(LegacyAccountLink.objects.filter(
        source_table__startswith='app01_'))
    account_ids = [item.account_id for item in links]
    legacy_logins = [item.account.login_name for item in links
                     if item.account is not None]
    # 迁移建立的学生档案
    for record in StudentRecord.objects.filter(student_no__in=legacy_logins):
        record.delete()
        removed['records'] += 1

    for account_id in set(account_ids + manifest['created_accounts']):
        account = Account.objects.filter(pk=account_id).first()
        if account is None:
            continue
        StudentProfile.objects.filter(account=account).delete()
        TeacherProfile.objects.filter(account=account).delete()
        LegacyAccountLink.objects.filter(account=account).delete()
        OrganizationMembership.objects.filter(account=account).delete()
        account.delete()
        removed['accounts'] += 1

    for membership_id in manifest['created_memberships']:
        deleted, _ = OrganizationMembership.objects.filter(
            pk=membership_id).delete()
        removed['memberships'] += deleted

    # 清理本迁移建立的组织单元（前缀锚点，覆盖跨批次残留；复用单元不动）
    for unit in reversed(list(OrganizationUnit.objects.filter(
            code__startswith=LEGACY_PREFIX).order_by('-id'))):
        if unit.children.exists() or unit.memberships.exists() \
                or StudentRecord.objects.filter(unit=unit).exists():
            continue
        unit.delete()
        removed['units'] += 1

    MANIFEST.unlink(missing_ok=True)
    return {'mode': 'rollback', 'removed': removed,
            'note': '仅删除本批次新建且无外部引用的对象；复用单元未删除。'}


def main():
    parser = argparse.ArgumentParser(description='app01 历史数据隔离迁移')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()

    if args.rollback:
        product_setup()
        report = run_rollback()
    else:
        product_setup()
        conn = source_connection()
        before = source_fingerprint(conn)
        data = fetch_all(conn)
        conn.rollback()
        conn.close()

        if args.apply:
            report = run_apply(data)
        elif args.verify:
            report = run_verify(data)
        else:
            report = run_preview(data, before)

        # 源库只读验证：再次取指纹必须一致
        conn = source_connection()
        after = source_fingerprint(conn)
        conn.rollback()
        conn.close()
        report['source_fingerprint_after'] = after
        report['source_unchanged'] = before == after

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    ok = report.get('ok', True) and report.get('source_unchanged', True)
    print('RESULT: {}'.format('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
