#!/usr/bin/env python
"""隔离环境初始化：建库 → 迁移 → 灌合成数据（可重复执行）。

用法::

    python scripts/integrated_dev_bootstrap.py                      # 集成开发库（默认）
    python scripts/integrated_dev_bootstrap.py --target r20         # R20 门户独立库
    python scripts/integrated_dev_bootstrap.py --keep-db            # 只补数据，不删库
    python scripts/integrated_dev_bootstrap.py --json out.json

安全约束
--------
- 库名白名单：``smass_integrated_dev`` / ``smass_r20_portal``，其余直接退出；
- **绝不指向正式库 ``smass``**；
- 全部为合成数据，账号密码仅用于本地演示。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 演示账号密码：优先取 .env / 环境变量，未配置时生成随机值并在输出中打印
PASSWORD = os.environ.get('INTEGRATED_DEV_PASSWORD', '')

ACCOUNTS = (
    ('dev_admin', '系统管理员', 'admin', ['system_admin']),
    ('dev_college', '学院管理员', 'admin', ['college_admin']),
    ('dev_teacher', '张老师', 'teacher', ['teacher']),
    ('dev_student', '李同学', 'student', ['student']),
    ('dev_counselor', '王辅导员', 'teacher', ['teacher']),
)

TARGETS = {
    'integrated': {
        'db': 'smass_integrated_dev',
        'settings': 'smass.settings_integrated_dev',
        'academic': True, 'workflow': True, 'analytics': True,
    },
    'r20': {
        'db': 'smass_r20_portal',
        'settings': 'smass.settings_r20',
        'academic': False, 'workflow': False, 'analytics': False,
    },
}


def demo_password():
    """返回演示密码。

    优先级：环境变量 `INTEGRATED_DEV_PASSWORD` → 项目 `.env` → 随机生成。
    仓库内不保存明文密码（由 .env 或环境变量提供）。
    """
    global PASSWORD
    if PASSWORD:
        return PASSWORD
    try:
        from smass.env_loader import load_env  # noqa: PLC0415
        load_env()
    except Exception:  # noqa: BLE001 - 无 .env 时忽略
        pass
    PASSWORD = os.environ.get('INTEGRATED_DEV_PASSWORD', '')
    if not PASSWORD:
        import secrets
        PASSWORD = 'Dev-' + secrets.token_urlsafe(9)
    return PASSWORD


def setup_django(settings_module):
    os.environ['DJANGO_SETTINGS_MODULE'] = settings_module
    sys.path.insert(0, str(ROOT))
    import django  # noqa: PLC0415
    django.setup()
    from django.conf import settings  # noqa: PLC0415
    return settings


def db_config(settings_module):
    settings = setup_django(settings_module)
    return dict(settings.DATABASES['default'])


def _admin_connection(cfg):
    import pymysql  # noqa: PLC0415
    return pymysql.connect(
        host=str(cfg['HOST'] or '127.0.0.1'), port=int(cfg['PORT'] or 3306),
        user=str(cfg['USER']), password=str(cfg['PASSWORD']),
        charset='utf8mb4', autocommit=True)


def recreate_database(cfg, db_name):
    connection = _admin_connection(cfg)
    try:
        with connection.cursor() as cursor:
            cursor.execute('DROP DATABASE IF EXISTS `{}`'.format(db_name))
            cursor.execute(
                'CREATE DATABASE `{}` CHARACTER SET utf8mb4'.format(db_name))
    finally:
        connection.close()


def ensure_database(cfg, db_name):
    connection = _admin_connection(cfg)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET utf8mb4'.format(
                    db_name))
    finally:
        connection.close()


def migrate(settings_module):
    completed = subprocess.run(  # noqa: S603 - 固定参数
        [sys.executable, 'manage.py', 'migrate', '--noinput',
         '--settings={}'.format(settings_module)],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=1800)
    if completed.returncode != 0:
        raise SystemExit('migrate 失败：{}'.format(
            (completed.stderr or '').strip()[-1500:]))
    return True


def seed_accounts():
    from r21_account import services as account_services  # noqa: PLC0415
    from r21_account.models import Account  # noqa: PLC0415

    account_services.ensure_role_groups()
    created = {}
    for login_name, display, person_type, roles in ACCOUNTS:
        account = Account.objects.filter(login_name=login_name).first()
        if account is None:
            account = Account.objects.create_user(
                login_name, demo_password(), display_name=display,
                person_type=person_type)
        account.must_change_password = False
        account.display_name = display
        account.save(update_fields=['must_change_password', 'display_name'])
        for role in roles:
            account_services.grant_role(account, role, granted_by='bootstrap')
        created[login_name] = roles
    return created


def seed_organization():
    from smass_organization import services as org_services  # noqa: PLC0415
    from smass_organization.models import (  # noqa: PLC0415
        UNIT_TYPE_CLASS, UNIT_TYPE_COLLEGE, UNIT_TYPE_MAJOR,
        OrganizationUnit, StudentRecord,
    )

    college = OrganizationUnit.objects.filter(code='DEV-COL').first() or \
        org_services.create_unit(code='DEV-COL', name='信息工程学院',
                                 unit_type=UNIT_TYPE_COLLEGE)
    major = OrganizationUnit.objects.filter(code='DEV-MAJ').first() or \
        org_services.create_unit(code='DEV-MAJ', name='软件工程',
                                 unit_type=UNIT_TYPE_MAJOR, parent=college)
    klass = OrganizationUnit.objects.filter(code='DEV-CLS').first() or \
        org_services.create_unit(code='DEV-CLS', name='软工2401',
                                 unit_type=UNIT_TYPE_CLASS, parent=major)

    for index in range(1, 6):
        number = 'DEV2024{:03d}'.format(index)
        StudentRecord.objects.get_or_create(
            student_no=number,
            defaults={'name': '演示学生{}'.format(index), 'unit': klass,
                      'extra': {'phone': '1380000{:04d}'.format(index)}})
    return {'units': OrganizationUnit.objects.count(),
            'students': StudentRecord.objects.count()}


def seed_academic():
    from smass_academic import services as academic_services  # noqa: PLC0415
    from smass_academic.models import (  # noqa: PLC0415
        AcademicTerm, AcademicYear, Course, TeachingSection,
    )

    year = AcademicYear.objects.filter(code='DEV-2025').first()
    if year is None:
        year = academic_services.create_year(
            'DEV-2025', date(2025, 9, 1), date(2026, 8, 31))
    term = AcademicTerm.objects.filter(year=year, semester='1').first()
    if term is None:
        term = academic_services.create_term(
            year, '1', date(2025, 9, 1), date(2026, 1, 15))
    course = Course.objects.filter(code='DEV-CS101').first()
    if course is None:
        course = academic_services.create_course('DEV-CS101', '程序设计基础', credit=3)
    section = TeachingSection.objects.filter(
        term=term, course=course, code='A').first()
    if section is None:
        section = academic_services.create_section(term, course, 'A', capacity=40)
    return {'years': AcademicYear.objects.count(),
            'terms': AcademicTerm.objects.count(),
            'courses': Course.objects.count(),
            'sections': TeachingSection.objects.count()}


def seed_workflow():
    from smass_workflow import services as workflow_services  # noqa: PLC0415
    from smass_workflow.models import WorkflowDefinition  # noqa: PLC0415

    if WorkflowDefinition.objects.filter(code='DEV-LEAVE').exists():
        return {'definitions': WorkflowDefinition.objects.count()}
    definition = workflow_services.create_definition('DEV-LEAVE', '演示请假流程')
    version = workflow_services.create_draft_version(definition)
    workflow_services.add_node(version, 'start', '发起', 'start', order=0)
    workflow_services.add_node(version, 'approve', '审批', 'approval', order=1)
    workflow_services.add_node(version, 'end', '完成', 'end', order=2)
    workflow_services.add_transition(version, 'start', 'approve', 'submit')
    workflow_services.add_transition(version, 'approve', 'end', 'approve')
    workflow_services.publish_version(version)
    return {'definitions': WorkflowDefinition.objects.count()}


def seed_analytics():
    from smass_analytics import services as analytics_services  # noqa: PLC0415
    from smass_analytics.models import MetricDefinition  # noqa: PLC0415

    for code, name, source in (
            ('org_units_total', '组织单元总数', 'organization'),
            ('students_scoped', '可见学生档案数', 'student'),
            ('sections_visible', '可见教学班数', 'academic')):
        metric = MetricDefinition.objects.filter(code=code).first()
        if metric is None:
            metric = analytics_services.register_metric(code, name, source)
        if not metric.is_enabled:
            analytics_services.validate_metric(metric)
    return {'metrics': MetricDefinition.objects.count()}


def main():
    parser = argparse.ArgumentParser(description='隔离环境初始化')
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--keep-db', action='store_true')
    parser.add_argument('--target', choices=sorted(TARGETS), default='integrated')
    args = parser.parse_args()

    target = TARGETS[args.target]
    db_name = target['db']
    if db_name not in ('smass_integrated_dev', 'smass_r20_portal'):
        raise SystemExit('拒绝操作非白名单库：{!r}'.format(db_name))

    cfg = db_config(target['settings'])
    if not args.keep_db:
        recreate_database(cfg, db_name)
    else:
        ensure_database(cfg, db_name)
    setup_django(target['settings'])

    report = {'target': args.target, 'db': db_name,
              'migrate': migrate(target['settings'])}
    report['accounts'] = seed_accounts()
    report['organization'] = seed_organization()
    if target['academic']:
        report['academic'] = seed_academic()
    if target['workflow']:
        report['workflow'] = seed_workflow()
    if target['analytics']:
        report['analytics'] = seed_analytics()
    report['password'] = demo_password()
    report['ok'] = True

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    print(text)
    print('RESULT: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
