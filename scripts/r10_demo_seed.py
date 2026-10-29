"""为 R10 演示环境生成少量**合成**数据（隔离库）。

用法：
    conda run -n smass python scripts/r10_demo_seed.py
"""
import os
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r10')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402

from r21_account import services as core_services  # noqa: E402
from r21_account.models import Account, RoleCode  # noqa: E402
from smass_academic import services as academic_services  # noqa: E402
from smass_analytics import services as analytics_services  # noqa: E402
from smass_organization import services as org_services  # noqa: E402
from smass_organization.models import StudentRecord  # noqa: E402
from smass_workflow import services as workflow_services  # noqa: E402

PASSWORD = 'Demo#2024'


def guard():
    name = connection.settings_dict['NAME'] or ''
    if not name.startswith('smass_r10_'):
        raise SystemExit('拒绝：只在 smass_r10_* 演示库执行，当前 {!r}'.format(name))
    return name


def make_account(login, role, person_type='admin', display=''):
    account, created = Account.objects.get_or_create(
        login_name=login,
        defaults={
            'display_name': display or login,
            'person_type': person_type,
            'must_change_password': False,
        },
    )
    if created:
        account.set_password(PASSWORD)
        account.must_change_password = False
        account.save()
    core_services.ensure_role_groups()
    core_services.grant_role(account, role, granted_by='demo_seed')
    return Account.objects.get(pk=account.pk)


def main():
    db = guard()
    print('target database : {}'.format(db))

    # ---- 账号 ----
    admin = make_account('admin', RoleCode.SYSTEM_ADMIN, 'admin', '演示管理员')
    teacher = make_account('teacher', RoleCode.TEACHER, 'teacher', '演示教师')
    student = make_account('student', RoleCode.STUDENT, 'student', '演示学生')

    # ---- R4 组织 + 学生（6 人，超过小样本阈值）----
    from smass_organization.models import OrganizationUnit

    college, _ = OrganizationUnit.objects.get_or_create(
        code='DEMO-C', defaults={'name': '信息工程学院', 'unit_type': 'college'})
    major, _ = OrganizationUnit.objects.get_or_create(
        code='DEMO-M', defaults={'name': '信息安全技术', 'unit_type': 'major',
                                 'parent': college})
    klass, _ = OrganizationUnit.objects.get_or_create(
        code='DEMO-K', defaults={'name': '信安2101', 'unit_type': 'class',
                                 'parent': major})

    created_students = 0
    for index in range(6):
        student_no = 'DEMO-S{:03d}'.format(index)
        record, created = StudentRecord.objects.get_or_create(
            student_no=student_no,
            defaults={'name': '演示学生{}'.format(index), 'unit': klass},
        )
        if created:
            created_students += 1

    # 把演示学生账号关联到第一条档案
    first = StudentRecord.objects.filter(student_no='DEMO-S000').first()
    if first and first.account_id is None:
        first.account = student
        first.save(update_fields=['account'])

    # ---- R5 学年/学期/课程/教学班/任课/修读 ----
    year, _ = academic_services.AcademicYear.objects.get_or_create(
        code='DEMO-2025',
        defaults={'start_date': date(2025, 9, 1), 'end_date': date(2026, 8, 31),
                  'is_active': True},
    )
    term, _ = academic_services.AcademicTerm.objects.get_or_create(
        year=year, semester='1',
        defaults={'start_date': date(2025, 9, 1), 'end_date': date(2026, 1, 15),
                  'is_active': True, 'name': '第一学期'},
    )
    course, _ = academic_services.Course.objects.get_or_create(
        code='DEMO-CS1', defaults={'title': '程序设计基础', 'credit': 3,
                                   'course_type': '专业必修'})
    section, _ = academic_services.TeachingSection.objects.get_or_create(
        term=term, course=course, code='A',
        defaults={'capacity': 30},
    )
    try:
        academic_services.assign_teacher(section, teacher, assigned_by='demo_seed')
    except Exception:  # noqa: BLE001 - 已分配则跳过（幂等）
        pass
    try:
        academic_services.enroll(section, student, actor='demo_seed')
    except Exception:  # noqa: BLE001 - 已选则跳过（幂等）
        pass

    # ---- R6 流程定义 + 实例 ----
    if not workflow_services.WorkflowDefinition.objects.filter(code='DEMO-LEAVE').exists():
        definition = workflow_services.create_definition('DEMO-LEAVE', '演示请假流程')
        version = workflow_services.create_draft_version(definition)
        workflow_services.add_node(version, 'start', '发起', 'start', order=0)
        workflow_services.add_node(version, 'approve', '辅导员审批', 'approval', order=1)
        workflow_services.add_node(version, 'end', '完成', 'end', order=2)
        workflow_services.add_transition(version, 'start', 'approve', 'submit')
        workflow_services.add_transition(version, 'approve', 'end', 'approve')
        workflow_services.add_transition(version, 'approve', 'end', 'reject')
        workflow_services.publish_version(version)

        instance = workflow_services.start_instance(
            version, subject_type='leave', subject_id='DEMO-L1',
            created_by='student',
        )
        workflow_services.transition(instance, 'submit', actor='student')
        workflow_services.notify('admin', '有一条待审批：演示请假',
                                 event_key='demo-leave-1')

    # ---- R7 指标 ----
    metric, _ = analytics_services.MetricDefinition.objects.get_or_create(
        code='org_units_total',
        defaults={'name': '组织单元总数', 'data_source': 'organization'},
    )
    if not metric.is_enabled:
        analytics_services.validate_metric(metric)

    metric2, _ = analytics_services.MetricDefinition.objects.get_or_create(
        code='students_scoped',
        defaults={'name': '可见学生数', 'data_source': 'student'},
    )
    if not metric2.is_enabled:
        analytics_services.validate_metric(metric2)

    # ---- R7 报表（U6 需要）----
    from smass_analytics.models import ReportDefinition

    report, created = ReportDefinition.objects.get_or_create(
        code='DEMO-RPT',
        defaults={'name': '演示综合报表', 'permission_roles': ['system_admin',
                                                             'college_admin',
                                                             'teacher']},
    )
    report.metrics.set([metric, metric2])
    if not report.is_enabled:
        report.is_enabled = True
        report.save(update_fields=['is_enabled'])

    print('')
    print('demo accounts (password = {}):'.format(PASSWORD))
    print('  admin   / system_admin')
    print('  teacher / teacher')
    print('  student / student')
    print('')
    print('counts: units={} students={} (new {}) sections={} instances={}'.format(
        org_services.OrganizationUnit.objects.count(),
        StudentRecord.objects.count(), created_students,
        academic_services.TeachingSection.objects.count(),
        workflow_services.WorkflowInstance.objects.count(),
    ))
    return 0


if __name__ == '__main__':
    sys.exit(main())
