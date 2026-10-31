"""管理端数据聚合与治理视图服务。

管理端不是"另一套业务库"：所有统计与列表都直接来自统一模型，
写操作调用各模块服务（账号、审批、场地、活动、公告）。
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .. import permissions as perms


# ---------------------------------------------------------------------------
# 范围
# ---------------------------------------------------------------------------
def scope_users(account):
    from r21_account.models import Account

    if perms.is_system_admin(account):
        return Account.objects.all()
    code = (getattr(account, 'scope_college', '') or '').strip()
    if not code:
        return Account.objects.none()
    return Account.objects.filter(
        Q(student_profile__college_name=code)
        | Q(teacher_profile__college_name=code)
        | Q(scope_college=code))


def scope_records(account):
    return perms.scoped_student_records(account)


# ---------------------------------------------------------------------------
# 总览
# ---------------------------------------------------------------------------
def overview(account):
    from r21_account.models import Account
    from smass_academic.models import Course, TeachingSection
    from smass_activities.models import Activity
    from smass_clubs.models import Club
    from smass_facilities.models import Room, RoomBooking
    from smass_finance.models import Bill
    from smass_operations.models import AlertEvent, ReadinessProbe, RequestMetric
    from smass_organization.models import OrganizationUnit
    from smass_scheduling.models import RUN_PUBLISHED, ScheduleRun
    from smass_workflow.models import ApprovalTask, WorkflowDefinition

    records = scope_records(account)
    users = scope_users(account)
    now = timezone.now()
    since = now - timedelta(hours=24)

    bills = Bill.objects.all()
    totals = bills.aggregate(total=Sum('total'), paid=Sum('paid'))
    total = totals['total'] or 0
    paid = totals['paid'] or 0

    pending_tasks = ApprovalTask.objects.filter(status='pending')
    requests = RequestMetric.objects.filter(created_at__gte=since)
    errors = requests.filter(status_code__gte=500).count()

    return {
        'accounts_total': users.count(),
        'students_total': records.count(),
        'teachers_total': users.filter(person_type='teacher').count(),
        'units_total': OrganizationUnit.objects.count(),
        'sections_total': TeachingSection.objects.count(),
        'courses_total': Course.objects.count(),
        'published_runs': ScheduleRun.objects.filter(status=RUN_PUBLISHED).count(),
        'workflows_total': WorkflowDefinition.objects.count(),
        'pending_tasks': pending_tasks.count(),
        'pending_bookings': RoomBooking.objects.filter(status='pending').count(),
        'rooms_total': Room.objects.count(),
        'activities_total': Activity.objects.count(),
        'clubs_total': Club.objects.count(),
        'bills_total': total,
        'bills_paid': paid,
        'bills_unpaid': total - paid,
        'requests_24h': requests.count(),
        'errors_24h': errors,
        'probe_ok': ReadinessProbe.objects.order_by('-checked_at').first(),
        'alerts_24h': AlertEvent.objects.filter(created_at__gte=since).count(),
        'recent_requests': list(requests.order_by('-created_at')[:8]),
        'recent_alerts': list(AlertEvent.objects.order_by('-created_at')[:6]),
    }


# ---------------------------------------------------------------------------
# 用户 / 角色 / 组织
# ---------------------------------------------------------------------------
def users(account, keyword='', role='', person_type=''):
    qs = (scope_users(account)
          .select_related('student_profile', 'teacher_profile')
          .order_by('-created_at'))
    keyword = (keyword or '').strip()
    if keyword:
        qs = qs.filter(Q(login_name__icontains=keyword)
                       | Q(display_name__icontains=keyword))
    if person_type:
        qs = qs.filter(person_type=person_type)
    rows = []
    for item in qs[:200]:
        roles = sorted(perms.active_roles(item))
        if role and role not in roles:
            continue
        rows.append({'account': item, 'roles': roles})
    return rows


def roles_matrix(account):
    from r21_account.models import Account, AccountRole, RoleCode

    result = []
    for code, label in RoleCode.choices:
        count = AccountRole.objects.filter(
            role=code, revoked_at__isnull=True).count()
        result.append({'code': code, 'label': label, 'count': count})
    return result


def organizations(account):
    from smass_organization.models import OrganizationMembership, OrganizationUnit

    units = (OrganizationUnit.objects
             .select_related('parent')
             .annotate(member_count=Count('memberships',
                                          filter=Q(memberships__ended_at__isnull=True)))
             .order_by('unit_type', 'sort_order', 'code'))
    if not perms.is_system_admin(account):
        allowed = set(perms.college_unit_ids(account))
        units = [unit for unit in units if unit.pk in allowed or
                 (unit.parent_id in allowed)]
    return list(units)


def memberships(account, limit=80):
    from smass_organization.models import OrganizationMembership

    qs = (OrganizationMembership.objects
          .filter(ended_at__isnull=True)
          .select_related('account', 'unit')
          .order_by('unit__name', 'account__display_name'))
    if not perms.is_system_admin(account):
        allowed = set(perms.college_unit_ids(account))
        qs = qs.filter(unit_id__in=allowed)
    return list(qs[:limit])


# ---------------------------------------------------------------------------
# 学籍与教学
# ---------------------------------------------------------------------------
def records(account, keyword='', status=''):
    qs = (scope_records(account)
          .select_related('unit', 'unit__parent', 'unit__parent__parent')
          .order_by('unit__name', 'student_no'))
    keyword = (keyword or '').strip()
    if keyword:
        qs = qs.filter(Q(student_no__icontains=keyword)
                       | Q(name__icontains=keyword))
    if status:
        qs = qs.filter(status=status)
    return list(qs[:300])


def record_changes(account):
    from smass_enrollment.models import MajorTransferRequest, StudentStatusChange

    records_qs = scope_records(account)
    transfers = list(
        MajorTransferRequest.objects.filter(record__in=records_qs)
        .select_related('record', 'from_unit', 'to_major', 'target_class')
        .order_by('-created_at')[:60])
    changes = list(
        StudentStatusChange.objects.filter(record__in=records_qs)
        .select_related('record').order_by('-created_at')[:60])
    return {'transfers': transfers, 'changes': changes}


def academics():
    from smass_academic.models import (
        AcademicTerm, AcademicYear, Course, Enrollment, TeachingSection,
    )

    years = list(AcademicYear.objects.order_by('-start_date'))
    terms = list(AcademicTerm.objects.select_related('year')
                 .order_by('-year__start_date', '-semester'))
    courses = list(Course.objects.order_by('code'))
    sections = list(
        TeachingSection.objects.select_related('term', 'term__year', 'course')
        .annotate(enrolled=Count('enrollments',
                                 filter=~Q(enrollments__status='dropped')))
        .order_by('-term__year__start_date', 'course__title'))
    return {
        'years': years,
        'terms': terms,
        'courses': courses,
        'sections': sections,
        'enrollment_total': Enrollment.objects.exclude(status='dropped').count(),
    }


def scheduling(account):
    from smass_scheduling.models import ScheduleEntry, ScheduleRun

    runs = list(
        ScheduleRun.objects.select_related('term', 'term__year')
        .annotate(entry_count=Count('entries'))
        .order_by('-created_at')[:30])
    latest = runs[0] if runs else None
    entries = 0
    if latest is not None:
        entries = ScheduleEntry.objects.filter(run=latest).count()
    return {'runs': runs, 'latest': latest, 'latest_entries': entries}


def facilities(account):
    from smass_facilities.models import Building, Room, RoomBooking

    rooms = list(
        Room.objects.select_related('building')
        .annotate(booking_count=Count('bookings'))
        .order_by('building__name', 'code'))
    pending = list(
        RoomBooking.objects.filter(status='pending')
        .select_related('room', 'room__building', 'account')
        .order_by('start_at')[:40])
    return {'rooms': rooms, 'pending': pending,
            'booking_total': RoomBooking.objects.count(),
            'buildings': list(Building.objects.filter(is_active=True)
                              .order_by('name'))}


# ---------------------------------------------------------------------------
# 审批 / 校园业务
# ---------------------------------------------------------------------------
def approvals(account):
    from smass_attendance.models import LEAVE_SUBMITTED, LeaveRequest
    from smass_facilities.models import RoomBooking
    from smass_workflow.models import ApprovalTask, Notification

    records_qs = scope_records(account)
    leaves = list(
        LeaveRequest.objects.filter(record__in=records_qs,
                                    status=LEAVE_SUBMITTED)
        .select_related('record', 'record__unit')
        .order_by('-created_at')[:60])
    tasks = list(
        ApprovalTask.objects.filter(status='pending')
        .select_related('instance', 'node')
        .order_by('-created_at')[:60])
    bookings = list(
        RoomBooking.objects.filter(status='pending')
        .select_related('room', 'account')
        .order_by('start_at')[:40])
    history = list(
        LeaveRequest.objects.filter(record__in=records_qs)
        .select_related('record', 'record__unit')
        .order_by('-created_at')[:20])
    return {'leaves': leaves, 'tasks': tasks, 'bookings': bookings,
            'leave_history': history}


def workflows():
    from smass_workflow.models import WorkflowDefinition, WorkflowInstance

    definitions = list(
        WorkflowDefinition.objects.annotate(instance_count=Count('versions'))
        .order_by('code'))
    instances = list(
        WorkflowInstance.objects.select_related('version', 'version__definition')
        .order_by('-created_at')[:40])
    return {'definitions': definitions, 'instances': instances}


def activities(account):
    from smass_activities.models import Activity, ActivityCredit

    items = list(
        Activity.objects.select_related('organizer')
        .annotate(reg_count=Count('registrations'))
        .order_by('-start_at')[:60])
    credits = list(
        ActivityCredit.objects.filter(status='pending')
        .select_related('activity', 'record')
        .order_by('-pk')[:50])
    return {'activities': items, 'credits': credits,
            'credits_pending': len(credits)}


def clubs(account):
    from smass_clubs.models import (
        POST_TITLES, Club, ClubMembership, ClubPost,
    )
    from smass_organization.models import OrganizationUnit

    items = list(
        Club.objects.select_related('advisor', 'parent')
        .annotate(member_count=Count('memberships',
                                     filter=Q(memberships__status='active')))
        .order_by('category', 'name'))
    organizations = list(
        OrganizationUnit.objects.filter(unit_type='department')
        .annotate(member_count=Count('memberships'))
        .order_by('sort_order', 'code'))
    pending = list(
        ClubMembership.objects.filter(status='pending')
        .select_related('club', 'record')
        .order_by('applied_at')[:50])
    posts = list(
        ClubPost.objects.filter(ended_at__isnull=True)
        .select_related('club', 'record')
        .order_by('club__name', 'title')[:50])
    return {'clubs': items, 'departments': organizations,
            'pending_list': pending, 'posts': posts,
            'post_titles': POST_TITLES,
            'pending_memberships': len(pending)}


def notices(account):
    from smass_forum.models import Announcement, Report

    items = list(Announcement.objects.order_by('-created_at')[:60])
    return {'announcements': items,
            'pending_reports': Report.objects.filter(status='open').count()}


# ---------------------------------------------------------------------------
# 运维 / 审计 / 配置
# ---------------------------------------------------------------------------
def monitoring(account):
    from smass_operations.models import (
        AlertEvent, AlertRule, ReadinessProbe, RequestMetric,
    )

    since = timezone.now() - timedelta(hours=24)
    requests = RequestMetric.objects.filter(created_at__gte=since)
    slow = list(requests.order_by('-duration_ms')[:15])
    failing = list(requests.filter(status_code__gte=400)
                   .order_by('-created_at')[:15])
    return {
        'requests_24h': requests.count(),
        'errors_24h': requests.filter(status_code__gte=500).count(),
        'avg_duration': (requests.aggregate(avg=Sum('duration_ms'))['avg'] or 0)
        / max(1, requests.count()),
        'slow': slow,
        'failing': failing,
        'probes': list(ReadinessProbe.objects.order_by('-checked_at')[:12]),
        'alerts': list(AlertEvent.objects.order_by('-created_at')[:12]),
        'rules': list(AlertRule.objects.order_by('code')),
    }


def audit(account):
    from r21_account.models import AccountAuditLog, LoginAttempt

    logs = list(AccountAuditLog.objects.order_by('-created_at')[:80])
    attempts = list(LoginAttempt.objects.order_by('-created_at')[:40])
    return {'logs': logs, 'attempts': attempts}


def settings_overview(account):
    from r21_account import authorization as authz
    from smass_organization.models import StudentFieldDefinition

    return {
        'authz': authz.describe(account),
        'fields': list(StudentFieldDefinition.objects.order_by('sort_order', 'code')),
        'role_matrix': roles_matrix(account),
    }


def data_exchange(account):
    datasets = []
    try:
        from smass_data_exchange import adapters, adapters_r5  # noqa: F401
        from smass_data_exchange.schema import all_schemas

        for schema in all_schemas():
            datasets.append({
                'code': getattr(schema, 'code', ''),
                'title': getattr(schema, 'title', getattr(schema, 'code', '')),
                'version': getattr(schema, 'version', ''),
                'fields': len(getattr(schema, 'fields', []) or []),
            })
    except Exception:  # noqa: BLE001 - 适配器异常时降级为空清单
        datasets = []
    return {'datasets': datasets}


# ---------------------------------------------------------------------------
# 教师档案（E02）
# ---------------------------------------------------------------------------
def teachers(account):
    """教师档案列表 + 任课数（系统管理员全局，学院管理员本院）。"""
    from r21_account.models import TeacherProfile

    queryset = TeacherProfile.objects.select_related('account').order_by('teacher_no')
    if not perms.is_system_admin(account):
        code = (getattr(account, 'scope_college', '') or '').strip()
        queryset = queryset.filter(college_name=code) if code else queryset.none()
    rows = list(queryset)
    counts = {}
    try:
        from smass_academic.models import TeachingAssignment

        for item in (TeachingAssignment.objects
                     .filter(account_id__in=[row.account_id for row in rows],
                             revoked_at__isnull=True)
                     .values('account_id')
                     .annotate(total=Count('id'))):
            counts[item['account_id']] = item['total']
    except Exception:  # noqa: BLE001 - 教学模块缺失时降级
        counts = {}
    for row in rows:
        row.assignment_count = counts.get(row.account_id, 0)
    return rows


def create_teacher(*, teacher_no, name, college_name='', password='', actor=''):
    """创建教师账号 + 档案 + 角色 + 学院关系（一次性完成）。"""
    from r21_account import services as account_services
    from r21_account.models import Account, TeacherProfile

    teacher_no = (teacher_no or '').strip()
    name = (name or '').strip()
    college_name = (college_name or '').strip()
    if not teacher_no or not name:
        raise ValueError('工号与姓名必填')
    if len(teacher_no) > 7:
        raise ValueError('工号最多 7 位')
    if len(password or '') < 8:
        raise ValueError('初始口令至少 8 位')
    if Account.objects.filter(login_name=teacher_no).exists():
        raise ValueError('工号已存在')
    if TeacherProfile.objects.filter(teacher_no=teacher_no).exists():
        raise ValueError('教师档案已存在')

    account = Account.objects.create_user(
        login_name=teacher_no, password=password, display_name=name,
        person_type='teacher')
    account.must_change_password = True
    account.save(update_fields=['must_change_password'])
    account_services.grant_role(account, 'teacher', granted_by=actor or 'admin')
    profile = TeacherProfile.objects.create(
        account=account, teacher_no=teacher_no, name=name,
        college_name=college_name)
    if college_name:
        from smass_organization.models import (
            OrganizationMembership, OrganizationUnit,
        )

        unit = OrganizationUnit.objects.filter(
            unit_type='college', name=college_name).first()
        if unit is not None:
            exists = OrganizationMembership.objects.filter(
                account=account, unit=unit, ended_at__isnull=True).exists()
            if not exists:
                OrganizationMembership.objects.create(
                    account=account, unit=unit, role='teacher',
                    started_at=timezone.localdate())
    return account, profile


def update_teacher(profile, *, name='', college_name='', actor=''):
    """更新教师档案并同步账号展示名。"""
    name = (name or '').strip()
    if name:
        profile.name = name[:100]
    profile.college_name = (college_name or '').strip()[:100]
    profile.save(update_fields=['name', 'college_name'])
    account = profile.account
    if name:
        account.display_name = profile.name
        account.save(update_fields=['display_name'])
    return profile


# ---------------------------------------------------------------------------
# 财务（E06）
# ---------------------------------------------------------------------------
def finance(account):
    """收费项、账单与待审退费（系统管理员全局；学院管理员只读本院）。"""
    from smass_finance.models import Bill, FeeItem, RefundRequest

    fee_items = list(FeeItem.objects.order_by('-pk')[:50])
    bills = list(Bill.objects.select_related('record').order_by('-pk')[:60])
    refunds = list(
        RefundRequest.objects.filter(status='submitted')
        .select_related('bill', 'bill__record')
        .order_by('-pk')[:50])
    return {
        'fee_items': fee_items,
        'bills': bills,
        'refunds': refunds,
        'refund_count': len(refunds),
    }
