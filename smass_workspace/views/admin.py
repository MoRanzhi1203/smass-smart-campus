"""管理控制台视图。

同一套页面服务超级管理员与普通管理员，区别只在**权限范围**：
- 超级管理员：全局治理；
- 学院管理员：本院用户/学籍只读，学籍异动、场地预约、本人流程待办可处理；
- 系统级写操作（用户与角色、活动、公告、系统配置）仅超级管理员，
  且以 HTTP 403 拒绝，而不是只隐藏按钮。
"""
from __future__ import annotations

import secrets
import string

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import permissions as perms
from ..services import admin as svc

admin_only = perms.require_kind(perms.KIND_ADMIN)


def _ctx(request, **extra):
    base = {'workspace_kind': perms.KIND_ADMIN,
            'is_super': perms.is_system_admin(request.user)}
    base.update(extra)
    return base


def _random_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# 总览
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def home(request):
    data = svc.overview(request.user)
    return render(request, 'workspace/admin/home.html', _ctx(request, **data))


# ---------------------------------------------------------------------------
# 用户 / 角色 / 组织
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def users(request):
    keyword = request.GET.get('q', '')
    role = request.GET.get('role', '')
    person_type = request.GET.get('type', '')
    rows = svc.users(request.user, keyword, role, person_type)
    return render(request, 'workspace/admin/users.html', _ctx(
        request,
        rows=rows,
        keyword=keyword,
        role=role,
        person_type=person_type,
        role_choices=_role_choices(),
        person_choices=(('', '全部'), ('student', '学生'),
                        ('teacher', '教师'), ('admin', '管理员')),
        total=len(rows),
    ))


def _role_choices():
    from r21_account.models import RoleCode

    return [('', '全部角色')] + list(RoleCode.choices)


@require_POST
@admin_only
@perms.require_system_admin
def user_role(request, pk):
    from r21_account import services as account_services
    from r21_account.models import Account

    account = Account.objects.filter(pk=pk).first()
    action = request.POST.get('action', '')
    role = request.POST.get('role', '')
    if account is None:
        messages.error(request, '账号不存在。')
        return redirect('/admin/users/')
    try:
        if action == 'grant':
            account_services.grant_role(account, role,
                                        granted_by=request.user.login_name)
            messages.success(request, '已为 {} 分配角色 {}。'.format(
                account.login_name, role))
        elif action == 'revoke':
            account_services.revoke_role(account, role,
                                         revoked_by=request.user.login_name)
            messages.success(request, '已撤销 {} 的角色 {}。'.format(
                account.login_name, role))
        else:
            messages.error(request, '未知操作。')
    except Exception as exc:  # noqa: BLE001 - 服务层错误原样提示
        messages.error(request, str(exc) or '操作失败。')
    return redirect('/admin/users/')


@require_POST
@admin_only
@perms.require_system_admin
def user_toggle(request, pk):
    from r21_account.models import Account

    account = Account.objects.filter(pk=pk).first()
    if account is None:
        messages.error(request, '账号不存在。')
        return redirect('/admin/users/')
    if account.pk == request.user.pk:
        messages.error(request, '不能停用当前登录账号。')
        return redirect('/admin/users/')
    account.is_active = not account.is_active
    account.save(update_fields=['is_active'])
    messages.success(request, '账号 {} 已{}。'.format(
        account.login_name, '启用' if account.is_active else '停用'))
    return redirect('/admin/users/')


@require_POST
@admin_only
@perms.require_system_admin
def user_reset(request, pk):
    from r21_account import services as account_services
    from r21_account.models import Account

    account = Account.objects.filter(pk=pk).first()
    if account is None:
        messages.error(request, '账号不存在。')
        return redirect('/admin/users/')
    password = _random_password()
    try:
        account_services.set_temporary_password(account, password)
        messages.success(
            request,
            '账号 {} 的一次性口令：{}（仅显示一次，请立即转交并提醒改密）'.format(
                account.login_name, password))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, str(exc) or '重置失败。')
    return redirect('/admin/users/')


@require_POST
@admin_only
@perms.require_system_admin
def user_create(request):
    from r21_account import services as account_services
    from r21_account.models import Account
    from r21_account.models import PersonType

    login_name = (request.POST.get('login_name') or '').strip()
    display_name = (request.POST.get('display_name') or '').strip()
    person_type = request.POST.get('person_type') or PersonType.STUDENT
    role = request.POST.get('role') or ''
    if not login_name or not display_name:
        messages.error(request, '登录名与显示名不能为空。')
        return redirect('/admin/users/')
    if Account.objects.filter(login_name=login_name).exists():
        messages.error(request, '登录名已存在。')
        return redirect('/admin/users/')
    password = _random_password()
    try:
        account = Account.objects.create_user(
            login_name, password, display_name=display_name,
            person_type=person_type)
        account.must_change_password = True
        account.save(update_fields=['must_change_password'])
        if role:
            account_services.grant_role(account, role,
                                        granted_by=request.user.login_name)
        messages.success(
            request,
            '已创建账号 {}，初始口令：{}（仅显示一次）。'.format(login_name, password))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, str(exc) or '创建失败。')
    return redirect('/admin/users/')


@require_GET
@admin_only
def roles(request):
    from r21_account.models import RoleCode

    return render(request, 'workspace/admin/roles.html', _ctx(
        request,
        matrix=svc.roles_matrix(request.user),
        role_codes=list(RoleCode.choices),
        account_roles=[perms.ROLE_LABEL.get(item, item)
                       for item in sorted(perms.active_roles(request.user))],
    ))


@require_GET
@admin_only
def organizations(request):
    units = svc.organizations(request.user)
    return render(request, 'workspace/admin/organizations.html', _ctx(
        request,
        units=units,
        memberships=svc.memberships(request.user, limit=60),
    ))


# ---------------------------------------------------------------------------
# 学籍与教学
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def records(request):
    keyword = request.GET.get('q', '')
    status = request.GET.get('status', '')
    rows = svc.records(request.user, keyword, status)
    return render(request, 'workspace/admin/records.html', _ctx(
        request,
        rows=rows,
        keyword=keyword,
        status=status,
        statuses=(('', '全部状态'), ('enrolled', '在读'), ('suspended', '休学'),
                  ('graduated', '毕业'), ('withdrawn', '退学')),
        total=len(rows),
    ))


@require_GET
@admin_only
def record_changes(request):
    return render(request, 'workspace/admin/record_changes.html', _ctx(
        request, **svc.record_changes(request.user)))


@require_POST
@admin_only
def transfer_action(request, pk, action):
    from smass_enrollment import services as enrollment_services
    from smass_enrollment.models import MajorTransferRequest

    transfer = MajorTransferRequest.objects.filter(pk=pk).first()
    if transfer is None:
        messages.error(request, '转专业申请不存在。')
        return redirect('/admin/record-changes/')
    if not perms.can_access_student(request.user, transfer.record):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_ADMIN,
            'attempted_label': '该学籍异动',
            'detail': '该学生不在你的组织范围内。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    try:
        if action == 'approve':
            enrollment_services.approve_transfer(transfer, request.user)
            messages.success(request, '转专业申请已批准。')
        elif action == 'reject':
            enrollment_services.reject_transfer(
                transfer, request.user,
                request.POST.get('reason', '') or '不符合转专业条件')
            messages.success(request, '转专业申请已驳回。')
        else:
            messages.error(request, '未知操作。')
    except enrollment_services.EnrollmentError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权审批该申请。')
    return redirect('/admin/record-changes/')


@require_POST
@admin_only
def status_change_action(request, pk, action):
    from smass_enrollment import services as enrollment_services
    from smass_enrollment.models import StudentStatusChange

    change = StudentStatusChange.objects.filter(pk=pk).first()
    if change is None:
        messages.error(request, '学籍异动不存在。')
        return redirect('/admin/record-changes/')
    if not perms.can_access_student(request.user, change.record):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_ADMIN,
            'attempted_label': '该学籍异动',
            'detail': '该学生不在你的组织范围内。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    try:
        if action == 'approve':
            enrollment_services.approve_status_change(change, request.user)
            messages.success(request, '学籍异动已批准。')
        elif action == 'reject':
            enrollment_services.reject_status_change(
                change, request.user,
                request.POST.get('reason', '') or '不符合学籍异动条件')
            messages.success(request, '学籍异动已驳回。')
        else:
            messages.error(request, '未知操作。')
    except enrollment_services.EnrollmentError as exc:
        messages.error(request, str(exc))
    except PermissionError:
        messages.error(request, '当前账号无权审批该异动。')
    return redirect('/admin/record-changes/')


@require_GET
@admin_only
def academics(request):
    return render(request, 'workspace/admin/academics.html', _ctx(
        request, **svc.academics()))


@require_GET
@admin_only
def sections(request):
    data = svc.academics()
    return render(request, 'workspace/admin/sections.html', _ctx(
        request,
        sections=data['sections'],
        enrollment_total=data['enrollment_total'],
        term=[term for term in data['terms'] if term.is_active][:1],
    ))


@require_GET
@admin_only
def scheduling(request):
    return render(request, 'workspace/admin/scheduling.html', _ctx(
        request, **svc.scheduling(request.user)))


@require_GET
@admin_only
def facilities(request):
    return render(request, 'workspace/admin/facilities.html', _ctx(
        request, **svc.facilities(request.user)))


@require_GET
@admin_only
def booking_approvals(request):
    data = svc.facilities(request.user)
    return render(request, 'workspace/admin/booking_approvals.html', _ctx(
        request,
        pending=data['pending'],
        rooms=data['rooms'],
    ))


@require_POST
@admin_only
def booking_action(request, pk, action):
    from smass_facilities import services as facility_services
    from smass_facilities.models import RoomBooking
    from smass_facilities.services import FacilityError

    booking = RoomBooking.objects.filter(pk=pk).first()
    if booking is None:
        messages.error(request, '预约不存在。')
        return redirect('/admin/booking-approvals/')
    try:
        if action == 'approve':
            facility_services.approve_booking(booking, request.user)
            messages.success(request, '预约已批准，申请人端状态已同步。')
        elif action == 'reject':
            facility_services.reject_booking(
                booking, request.user,
                request.POST.get('reason', '') or '场地不可用')
            messages.success(request, '预约已驳回。')
        else:
            messages.error(request, '未知操作。')
    except (FacilityError, PermissionError) as exc:
        messages.error(request, str(exc) or '操作失败。')
    return redirect('/admin/booking-approvals/')


# ---------------------------------------------------------------------------
# 审批与工作流
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def approvals(request):
    return render(request, 'workspace/admin/approvals.html', _ctx(
        request, **svc.approvals(request.user)))


@require_POST
@admin_only
def leave_action(request, pk, action):
    from smass_attendance import services as attendance_services
    from smass_attendance.models import LeaveRequest
    from smass_attendance.services import AttendanceError

    leave = LeaveRequest.objects.filter(pk=pk).first()
    if leave is None:
        messages.error(request, '请假申请不存在。')
        return redirect('/admin/approvals/')
    if not perms.can_access_student(request.user, leave.record):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_ADMIN,
            'attempted_label': '该请假申请',
            'detail': '该学生不在你的组织范围内。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    try:
        if action == 'approve':
            attendance_services.approve_leave(leave, request.user)
            messages.success(request, '请假已批准。')
        elif action == 'reject':
            attendance_services.reject_leave(
                leave, request.user,
                request.POST.get('reason', '') or '不符合请假规定')
            messages.success(request, '请假已驳回。')
        else:
            messages.error(request, '未知操作。')
    except (AttendanceError, PermissionError) as exc:
        messages.error(request, str(exc) or '操作失败。')
    return redirect('/admin/approvals/')


@require_POST
@admin_only
def task_complete(request, pk):
    from smass_workflow import services as workflow_services
    from smass_workflow.models import ApprovalTask

    task = ApprovalTask.objects.filter(pk=pk).first()
    if task is None:
        messages.error(request, '待办任务不存在。')
        return redirect('/admin/approvals/')
    if task.assignee and task.assignee != request.user.login_name \
            and not perms.is_system_admin(request.user):
        messages.error(request, '该任务未分配给你。')
        return redirect('/admin/approvals/')
    try:
        workflow_services.complete_task(task, actor=request.user.login_name)
        messages.success(request, '流程任务已完成。')
    except workflow_services.ConflictError as exc:
        messages.warning(request, str(exc))
    return redirect('/admin/approvals/')


@require_GET
@admin_only
def workflows(request):
    return render(request, 'workspace/admin/workflows.html', _ctx(
        request, **svc.workflows()))


# ---------------------------------------------------------------------------
# 校园业务
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def activities(request):
    return render(request, 'workspace/admin/activities.html', _ctx(
        request, **svc.activities(request.user)))


@require_POST
@admin_only
@perms.require_system_admin
def activity_action(request, pk, action):
    from smass_activities import services as activity_services
    from smass_activities.models import Activity
    from smass_activities.services import ActivityError

    activity = Activity.objects.filter(pk=pk).first()
    if activity is None:
        messages.error(request, '活动不存在。')
        return redirect('/admin/activities/')
    try:
        if action == 'publish':
            activity_services.publish_activity(activity, request.user)
            messages.success(request, '活动已发布，学生端可见。')
        elif action == 'close':
            activity_services.close_activity(activity, request.user)
            messages.success(request, '活动已结束。')
        elif action == 'credits':
            activity_services.generate_credits(activity, request.user)
            messages.success(request, '已生成学分认定记录。')
        else:
            messages.error(request, '未知操作。')
    except (ActivityError, PermissionError) as exc:
        messages.error(request, str(exc) or '操作失败。')
    return redirect('/admin/activities/')


@require_GET
@admin_only
def clubs(request):
    return render(request, 'workspace/admin/clubs.html', _ctx(
        request, **svc.clubs(request.user)))


@require_GET
@admin_only
def notices(request):
    return render(request, 'workspace/admin/notices.html', _ctx(
        request, **svc.notices(request.user)))


@require_POST
@admin_only
@perms.require_system_admin
def announcement_create(request):
    from smass_forum import services as forum_services
    from smass_forum.services import ForumError

    try:
        announcement = forum_services.create_announcement(
            request.user,
            request.POST.get('title', ''),
            request.POST.get('body', ''),
            request.POST.get('audience', 'all'),
        )
        if request.POST.get('publish') == '1':
            forum_services.publish_announcement(announcement, request.user)
        messages.success(request, '公告已创建。')
    except (ForumError, PermissionError) as exc:
        messages.error(request, str(exc) or '创建失败。')
    return redirect('/admin/notices/')


@require_POST
@admin_only
@perms.require_system_admin
def announcement_publish(request, pk):
    from smass_forum import services as forum_services
    from smass_forum.models import Announcement
    from smass_forum.services import ForumError

    announcement = Announcement.objects.filter(pk=pk).first()
    if announcement is None:
        messages.error(request, '公告不存在。')
        return redirect('/admin/notices/')
    try:
        forum_services.publish_announcement(announcement, request.user)
        messages.success(request, '公告已发布。')
    except (ForumError, PermissionError) as exc:
        messages.error(request, str(exc) or '发布失败。')
    return redirect('/admin/notices/')


# ---------------------------------------------------------------------------
# 数据治理 / 运维 / 审计 / 配置
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def data_exchange(request):
    return render(request, 'workspace/admin/data_exchange.html', _ctx(
        request, **svc.data_exchange(request.user)))


@require_GET
@admin_only
def monitoring(request):
    return render(request, 'workspace/admin/monitoring.html', _ctx(
        request, **svc.monitoring(request.user)))


@require_GET
@admin_only
def audit(request):
    return render(request, 'workspace/admin/audit.html', _ctx(
        request, **svc.audit(request.user)))


@require_GET
@admin_only
@perms.require_system_admin
def settings_overview(request):
    data = svc.settings_overview(request.user)
    return render(request, 'workspace/admin/settings.html', _ctx(
        request,
        authz=data['authz'],
        fields=data['fields'],
        role_matrix=data['role_matrix'],
        lifecycle=_password_lifecycle(),
    ))


def _password_lifecycle():
    from django.conf import settings

    return getattr(settings, 'PASSWORD_LIFECYCLE', {})
