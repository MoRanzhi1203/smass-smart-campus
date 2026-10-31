"""A04 数据权威源一致性检查（只读）。

检查项：
1. 学籍是否绑定账号；
2. 学号 / 姓名在 ``StudentRecord`` 与 ``StudentProfile`` 是否一致；
3. ``TeacherProfile.teacher_no`` 与账号登录名是否一致；
4. 站内通知的 recipient 是否仍能匹配到账号；
5. 组织树中班级的上级是否仍为专业。

不修改任何数据；结果供管理端「数据质量」页展示。
"""
from __future__ import annotations

MAX_SAMPLES = 20
SCAN_LIMIT = 2000


def check_all():
    from r21_account.models import Account, StudentProfile, TeacherProfile
    from smass_organization.models import OrganizationUnit, StudentRecord
    from smass_workflow.models import Notification

    issues = []

    def add(kind, title, detail):
        issues.append({'kind': kind, 'title': title, 'detail': detail})

    records = list(
        StudentRecord.objects.select_related('account')
        .order_by('student_no')[:SCAN_LIMIT])
    records_without_account = [item for item in records if item.account_id is None]
    for item in records_without_account[:MAX_SAMPLES]:
        add('record_without_account', '学籍未绑定账号',
            '{} {}'.format(item.student_no, item.name))

    record_by_account = {
        item.account_id: item for item in records if item.account_id}
    profiles = list(
        StudentProfile.objects.select_related('account')[:SCAN_LIMIT])
    profile_mismatch = []
    for profile in profiles:
        record = record_by_account.get(profile.account_id)
        if record is None:
            continue
        if record.student_no != profile.student_no:
            profile_mismatch.append(
                '学号：档案 {} / 学籍 {}（账号 {}）'.format(
                    profile.student_no, record.student_no,
                    profile.account.login_name))
        elif record.name != profile.name:
            profile_mismatch.append(
                '姓名：档案 {} / 学籍 {}（账号 {}）'.format(
                    profile.name, record.name, profile.account.login_name))
    for detail in profile_mismatch[:MAX_SAMPLES]:
        add('profile_mismatch', '学生档案与学籍不一致', detail)

    teacher_mismatch = []
    for profile in TeacherProfile.objects.select_related('account')[:SCAN_LIMIT]:
        login_name = getattr(profile.account, 'login_name', '')
        if login_name and profile.teacher_no != login_name:
            teacher_mismatch.append(
                '工号 {} / 登录名 {}'.format(profile.teacher_no, login_name))
    for detail in teacher_mismatch[:MAX_SAMPLES]:
        add('teacher_no_mismatch', '教师工号与登录名不一致', detail)

    recipients = set(
        Notification.objects.order_by('-pk').values_list(
            'recipient', flat=True)[:SCAN_LIMIT])
    orphan = []
    for recipient in recipients:
        if recipient and not Account.objects.filter(login_name=recipient).exists():
            orphan.append(recipient)
    for detail in orphan[:MAX_SAMPLES]:
        add('orphan_notification', '通知接收人已不存在', detail)

    bad_class_parent = []
    for unit in OrganizationUnit.objects.filter(
            unit_type='class').select_related('parent')[:SCAN_LIMIT]:
        if unit.parent_id is None or unit.parent.unit_type != 'major':
            bad_class_parent.append(
                '{}（上级：{}）'.format(
                    unit.code,
                    unit.parent.code if unit.parent_id else '无'))
    for detail in bad_class_parent[:MAX_SAMPLES]:
        add('class_parent', '班级上级不是专业', detail)

    counts = {
        'records': len(records),
        'profiles': len(profiles),
        'teachers': TeacherProfile.objects.count(),
        'notifications': Notification.objects.count(),
    }
    return {
        'issues': issues,
        'total_issues': len(issues),
        'counts': counts,
        'by_kind': {
            kind: len([item for item in issues if item['kind'] == kind])
            for kind in ('record_without_account', 'profile_mismatch',
                         'teacher_no_mismatch', 'orphan_notification',
                         'class_parent')
        },
    }
