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
    from ..services import pagination as pagination_svc

    page_info = pagination_svc.paginate(rows, request.GET.get('page'))
    return render(request, 'workspace/admin/users.html', _ctx(
        request,
        rows=page_info['items'],
        page_info=page_info,
        querystring=pagination_svc.querystring_without_page(request),
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
@perms.require_recent_auth
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
@perms.require_recent_auth
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


@require_POST
@perms.require_system_admin
def organization_create(request):
    from smass_organization import services as org_services
    from smass_organization.models import OrganizationUnit

    unit_type = (request.POST.get('unit_type') or '').strip()
    code = (request.POST.get('code') or '').strip()
    name = (request.POST.get('name') or '').strip()
    parent = OrganizationUnit.objects.filter(
        pk=request.POST.get('parent') or 0).first()
    try:
        org_services.create_unit(code=code, name=name, unit_type=unit_type,
                                 parent=parent)
        messages.success(request, '组织单元已创建：{}'.format(name))
    except Exception as exc:  # noqa: BLE001 - 唯一约束/层级校验统一提示
        messages.error(request, '创建失败：{}'.format(exc))
    return redirect('workspace:admin_organizations')


@require_POST
@perms.require_system_admin
def organization_update(request, pk):
    from django.shortcuts import get_object_or_404

    from smass_organization import services as org_services
    from smass_organization.models import OrganizationUnit

    unit = get_object_or_404(OrganizationUnit, pk=pk)
    action = (request.POST.get('action') or '').strip()
    try:
        if action == 'rename':
            org_services.rename_unit(unit, request.POST.get('name'))
            messages.success(request, '名称已更新')
        elif action == 'move':
            parent = OrganizationUnit.objects.filter(
                pk=request.POST.get('parent') or 0).first()
            org_services.move_unit(unit, parent,
                                   actor=request.user.login_name)
            messages.success(request, '上级已更新')
        elif action == 'status':
            org_services.set_unit_status(unit, request.POST.get('status'))
            messages.success(request, '状态已更新')
        else:
            messages.error(request, '未知操作')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:admin_organizations')


@require_GET
@admin_only
def teachers(request):
    from smass_organization.models import OrganizationUnit

    rows = svc.teachers(request.user)
    colleges = OrganizationUnit.objects.filter(
        unit_type='college', status='active').order_by('name')
    return render(request, 'workspace/admin/teachers.html', _ctx(
        request, rows=rows, colleges=colleges))


@require_POST
@perms.require_system_admin
def teacher_create(request):
    try:
        svc.create_teacher(
            teacher_no=request.POST.get('teacher_no'),
            name=request.POST.get('name'),
            college_name=request.POST.get('college_name'),
            password=request.POST.get('password'),
            actor=request.user.login_name)
        messages.success(request, '教师已创建（首次登录需修改口令）')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '创建失败：{}'.format(exc))
    return redirect('workspace:admin_teachers')


@require_POST
@perms.require_system_admin
def teacher_update(request, pk):
    from r21_account.models import TeacherProfile

    profile = TeacherProfile.objects.filter(pk=pk).first()
    if profile is None:
        messages.error(request, '教师档案不存在')
        return redirect('workspace:admin_teachers')
    try:
        svc.update_teacher(
            profile,
            name=request.POST.get('name', ''),
            college_name=request.POST.get('college_name', ''),
            actor=request.user.login_name)
        messages.success(request, '教师档案已更新')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '更新失败：{}'.format(exc))
    return redirect('workspace:admin_teachers')


# ---------------------------------------------------------------------------
# 学籍与教学
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def records(request):
    keyword = request.GET.get('q', '')
    status = request.GET.get('status', '')
    rows = svc.records(request.user, keyword, status)
    from ..services import pagination as pagination_svc

    page_info = pagination_svc.paginate(rows, request.GET.get('page'))
    return render(request, 'workspace/admin/records.html', _ctx(
        request,
        rows=page_info['items'],
        page_info=page_info,
        querystring=pagination_svc.querystring_without_page(request),
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
    from smass_academic.models import Course
    from smass_organization.models import OrganizationUnit

    data = svc.academics()
    return render(request, 'workspace/admin/academics.html', _ctx(
        request,
        **data,
        year_options=[(year.pk, year.code) for year in data['years']],
        course_options=[(course.pk, '{} {}'.format(course.code, course.title))
                        for course in data['courses'] if course.is_active],
        term_options=[(term.pk, '{} {}'.format(
            term.year.code, term.get_semester_display()))
            for term in data['terms']],
        class_units=[(unit.pk, unit.name) for unit in
                     OrganizationUnit.objects.filter(
                         unit_type='class', status='active')
                     .order_by('code')],
    ))


@require_POST
@admin_only
@perms.require_system_admin
def year_create(request):
    from django.utils.dateparse import parse_date

    from smass_academic import services as academic_services
    from smass_academic.services import AcademicError

    try:
        academic_services.create_year(
            request.POST.get('code', ''),
            parse_date(request.POST.get('start_date', '') or ''),
            parse_date(request.POST.get('end_date', '') or ''),
            is_active=request.POST.get('is_active') == '1',
        )
        messages.success(request, '学年已创建。')
    except AcademicError as exc:
        messages.error(request, str(exc))
    return redirect('/admin/academics/')


@require_POST
@admin_only
@perms.require_system_admin
def term_create(request):
    from django.utils.dateparse import parse_date

    from smass_academic import services as academic_services
    from smass_academic.models import AcademicYear
    from smass_academic.services import AcademicError

    year = AcademicYear.objects.filter(pk=request.POST.get('year') or 0).first()
    if year is None:
        messages.error(request, '请选择有效学年。')
        return redirect('/admin/academics/')
    try:
        academic_services.create_term(
            year, request.POST.get('semester', '1'),
            parse_date(request.POST.get('start_date', '') or ''),
            parse_date(request.POST.get('end_date', '') or ''),
            name=request.POST.get('name', ''),
            is_active=request.POST.get('is_active') == '1',
        )
        messages.success(request, '学期已创建。')
    except AcademicError as exc:
        messages.error(request, str(exc))
    return redirect('/admin/academics/')


@require_POST
@admin_only
@perms.require_system_admin
def course_create(request):
    from smass_academic import services as academic_services
    from smass_academic.services import AcademicError

    credit = request.POST.get('credit') or None
    try:
        credit_value = float(credit) if credit else None
    except ValueError:
        messages.error(request, '学分必须是数字。')
        return redirect('/admin/academics/')
    try:
        academic_services.create_course(
            request.POST.get('code', ''),
            request.POST.get('title', ''),
            credit=credit_value,
            course_type=request.POST.get('course_type', ''),
        )
        messages.success(request, '课程已创建。')
    except AcademicError as exc:
        messages.error(request, str(exc))
    return redirect('/admin/academics/')


@require_GET
@admin_only
def sections(request):
    data = svc.academics()
    return render(request, 'workspace/admin/sections.html', _ctx(
        request,
        sections=data['sections'],
        enrollment_total=data['enrollment_total'],
        term_options=[(term.pk, '{} {}'.format(
            term.year.code, term.get_semester_display()))
            for term in data['terms']],
        course_options=[(course.pk, '{} {}'.format(course.code, course.title))
                        for course in data['courses'] if course.is_active],
    ))


@require_POST
@admin_only
@perms.require_system_admin
def section_create(request):
    from smass_academic import services as academic_services
    from smass_academic.models import AcademicTerm, Course
    from smass_academic.services import AcademicError

    term = AcademicTerm.objects.filter(pk=request.POST.get('term') or 0).first()
    course = Course.objects.filter(pk=request.POST.get('course') or 0).first()
    if term is None or course is None:
        messages.error(request, '请选择有效学期与课程。')
        return redirect('/admin/sections/')
    try:
        academic_services.create_section(
            term, course, request.POST.get('code', ''),
            capacity=int(request.POST.get('capacity') or 0))
        messages.success(request, '教学班已创建。')
    except (AcademicError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect('/admin/sections/')


@require_GET
@admin_only
def section_roster(request, pk):
    from smass_academic.models import Enrollment, TeachingAssignment, TeachingSection

    section = (TeachingSection.objects.select_related(
        'term', 'term__year', 'course').filter(pk=pk).first())
    if section is None:
        messages.error(request, '教学班不存在。')
        return redirect('/admin/sections/')
    enrollments = list(
        Enrollment.objects.filter(section=section).exclude(status='dropped')
        .select_related('account').order_by('account__login_name'))
    assignments = list(
        TeachingAssignment.objects.filter(section=section,
                                          revoked_at__isnull=True)
        .select_related('account'))
    return render(request, 'workspace/admin/section_roster.html', _ctx(
        request,
        section=section,
        enrollments=enrollments,
        assignments=assignments,
    ))


@require_GET
@admin_only
def record_detail(request, student_no):
    from smass_academic.models import Enrollment
    from smass_organization.models import OrganizationUnit, StudentRecord

    record = (StudentRecord.objects.select_related(
        'unit', 'unit__parent', 'unit__parent__parent')
        .filter(student_no=student_no).first())
    if record is None or not perms.can_access_student(request.user, record):
        return render(request, 'workspace/403.html', {
            'workspace_kind': perms.KIND_ADMIN,
            'attempted_label': '该学籍档案',
            'detail': '该学生不在你的组织范围内。',
            'landing_url': perms.landing_url(request.user),
        }, status=403)
    enrollments = list(
        Enrollment.objects.filter(account=record.account).exclude(
            status='dropped').select_related('section', 'section__course'))
    return render(request, 'workspace/admin/record_detail.html', _ctx(
        request,
        record=record,
        enrollments=enrollments,
        class_units=[(unit.pk, unit.name) for unit in
                     OrganizationUnit.objects.filter(
                         unit_type='class', status='active').order_by('code')],
        statuses=(('enrolled', '在读'), ('suspended', '休学'),
                  ('graduated', '毕业'), ('withdrawn', '退学')),
    ))


@require_POST
@admin_only
@perms.require_system_admin
def record_update(request, student_no):
    from smass_organization import services as org_services
    from smass_organization.models import OrganizationUnit, StudentRecord

    record = StudentRecord.objects.filter(student_no=student_no).first()
    if record is None:
        messages.error(request, '学籍不存在。')
        return redirect('/admin/records/')
    unit = OrganizationUnit.objects.filter(
        pk=request.POST.get('unit') or 0, unit_type='class').first()
    try:
        org_services.update_student(
            record,
            name=request.POST.get('name') or record.name,
            status=request.POST.get('status') or record.status,
            unit=unit or record.unit,
            actor=request.user.login_name,
        )
        messages.success(request, '学籍信息已更新，变更已记录。')
    except Exception as exc:  # noqa: BLE001 - 服务层错误原样提示
        messages.error(request, str(exc) or '更新失败。')
    return redirect('/admin/records/{}/'.format(student_no))


@require_GET
@admin_only
def scheduling(request):
    from smass_academic.models import AcademicTerm

    terms = AcademicTerm.objects.select_related('year').order_by(
        '-year__start_date', 'semester')
    return render(request, 'workspace/admin/scheduling.html', _ctx(
        request, terms=terms, **svc.scheduling(request.user)))


@require_POST
@admin_only
@perms.require_system_admin
def schedule_create(request):
    from smass_academic.models import AcademicTerm
    from smass_scheduling import services as schedule_services

    term = AcademicTerm.objects.filter(pk=request.POST.get('term') or 0).first()
    try:
        run = schedule_services.create_run(
            term, actor=request.user.login_name)
        messages.success(request, '排课批次已创建（#{}）'.format(run.pk))
    except schedule_services.ScheduleError as exc:
        messages.error(request, str(exc))
    return redirect('workspace:admin_scheduling')


@require_POST
@admin_only
@perms.require_system_admin
def schedule_solve(request, pk):
    from smass_scheduling import services as schedule_services
    from smass_scheduling.models import ScheduleRun

    run = ScheduleRun.objects.filter(pk=pk).first()
    if run is None:
        messages.error(request, '排课批次不存在')
        return redirect('workspace:admin_scheduling')
    try:
        schedule_services.solve_run(run, actor=request.user.login_name)
        messages.success(request, '求解完成：{}，硬冲突 {} 个'.format(
            run.get_status_display(), run.hard_conflicts))
    except schedule_services.ScheduleError as exc:
        messages.error(request, str(exc))
    return redirect('workspace:admin_scheduling')


@require_POST
@admin_only
@perms.require_system_admin
def schedule_publish(request, pk):
    from smass_scheduling import services as schedule_services
    from smass_scheduling.models import ScheduleRun

    run = ScheduleRun.objects.filter(pk=pk).first()
    if run is None:
        messages.error(request, '排课批次不存在')
        return redirect('workspace:admin_scheduling')
    try:
        schedule_services.publish_run(run, actor=request.user.login_name)
        messages.success(request, '课表已发布，学生端与教师端同步更新')
    except schedule_services.ScheduleError as exc:
        messages.error(request, str(exc))
    return redirect('workspace:admin_scheduling')


@require_GET
@admin_only
def schedule_conflicts(request, pk):
    from django.shortcuts import get_object_or_404

    from smass_scheduling.models import ScheduleConflict, ScheduleRun

    run = get_object_or_404(ScheduleRun, pk=pk)
    conflicts = ScheduleConflict.objects.filter(run=run).order_by('pk')[:200]
    return render(request, 'workspace/admin/schedule_conflicts.html', _ctx(
        request, run=run, conflicts=conflicts))


@require_GET
@admin_only
def facilities(request):
    return render(request, 'workspace/admin/facilities.html', _ctx(
        request, **svc.facilities(request.user)))


@require_POST
@admin_only
@perms.require_system_admin
def room_create(request):
    from smass_facilities.models import Building, Room

    building = Building.objects.filter(
        pk=request.POST.get('building') or 0).first()
    code = (request.POST.get('code') or '').strip()
    name = (request.POST.get('name') or '').strip()
    if building is None or not code or not name:
        messages.error(request, '请选择楼宇并填写房间编码与名称。')
        return redirect('/admin/facilities/')
    if Room.objects.filter(code=code).exists():
        messages.error(request, '房间编码 {} 已存在。'.format(code))
        return redirect('/admin/facilities/')
    try:
        Room.objects.create(
            code=code, name=name, building=building,
            floor=request.POST.get('floor', ''),
            room_type=request.POST.get('room_type') or 'classroom',
            capacity=int(request.POST.get('capacity') or 0),
            status='open',
            requires_approval=request.POST.get('requires_approval') == '1',
            requires_qualification=request.POST.get('requires_qualification') == '1',
            is_active=True,
        )
        messages.success(request, '场地已创建，可立即接受预约。')
    except ValueError:
        messages.error(request, '容量必须是数字。')
    return redirect('/admin/facilities/')


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
    from smass_workflow.models import WorkflowDefinition

    published = WorkflowDefinition.objects.filter(
        versions__status='active').distinct()
    return render(request, 'workspace/admin/workflows.html', _ctx(
        request, published_definitions=published, **svc.workflows()))


@require_POST
@admin_only
@perms.require_system_admin
def workflow_create(request):
    from smass_workflow import blueprints

    try:
        definition, version = blueprints.create_single_approval_flow(
            request.POST.get('code'), request.POST.get('name'),
            description=request.POST.get('description') or '')
        messages.success(request, '流程已创建并发布：{}（版本 #{}）'.format(
            definition.name, version.pk))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '创建失败：{}'.format(exc))
    return redirect('workspace:admin_workflows')


@require_POST
@admin_only
@perms.require_system_admin
def workflow_instance_start(request):
    from smass_workflow import blueprints
    from smass_workflow.models import WorkflowDefinition

    definition = WorkflowDefinition.objects.filter(
        pk=request.POST.get('definition') or 0).first()
    try:
        instance = blueprints.start_and_submit(
            definition, subject_id=request.POST.get('subject_id') or '',
            actor=request.user.login_name)
        messages.success(request, '流程已发起（#{}），待办已生成'.format(
            instance.pk))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '发起失败：{}'.format(exc))
    return redirect('workspace:admin_workflows')


# ---------------------------------------------------------------------------
# 校园业务
# ---------------------------------------------------------------------------
@require_GET
@admin_only
def activities(request):
    from smass_activities.models import ACTIVITY_STATUS

    data = svc.activities(request.user)
    return render(request, 'workspace/admin/activities.html', _ctx(
        request,
        **data,
        categories=(('second_class', '第二课堂'), ('volunteer', '志愿服务'),
                    ('lecture', '讲座报告'), ('club', '社团活动')),
        statuses=ACTIVITY_STATUS,
    ))


@require_POST
@admin_only
@perms.require_system_admin
def activity_create(request):
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from smass_activities import services as activity_services
    from smass_activities.services import ActivityError

    start_at = parse_datetime(request.POST.get('start_at', '') or '')
    end_at = parse_datetime(request.POST.get('end_at', '') or '')
    if start_at is None or end_at is None:
        messages.error(request, '请填写完整的活动起止时间。')
        return redirect('/admin/activities/')
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at)
    if timezone.is_naive(end_at):
        end_at = timezone.make_aware(end_at)
    try:
        activity = activity_services.create_activity(
            request.user,
            request.POST.get('title', ''),
            request.POST.get('category', 'second_class'),
            start_at, end_at,
            capacity=int(request.POST.get('capacity') or 0),
            credit_points=float(request.POST.get('credit_points') or 0),
            volunteer_hours=float(request.POST.get('volunteer_hours') or 0),
            location=request.POST.get('location', ''),
        )
        if request.POST.get('publish') == '1':
            activity_services.publish_activity(activity, request.user)
        messages.success(request, '活动已创建。')
    except (ActivityError, ValueError) as exc:
        messages.error(request, str(exc) or '创建失败。')
    return redirect('/admin/activities/')


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


@require_POST
@admin_only
@perms.require_system_admin
def credit_action(request, pk, action):
    from django.shortcuts import get_object_or_404

    from smass_activities import services as activity_services
    from smass_activities.models import ActivityCredit

    credit = get_object_or_404(ActivityCredit, pk=pk)
    try:
        if action == 'approve':
            activity_services.approve_credit(credit, request.user)
            messages.success(request, '学分/志愿时长已认定')
        elif action == 'reject':
            activity_services.reject_credit(
                credit, request.user,
                request.POST.get('reason') or '材料不足')
            messages.success(request, '已驳回认定申请')
        else:
            messages.error(request, '未知操作')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:admin_activities')


@require_POST
@admin_only
@perms.require_system_admin
def club_membership_action(request, pk, action):
    from django.shortcuts import get_object_or_404

    from smass_clubs import services as club_services
    from smass_clubs.models import ClubMembership

    membership = get_object_or_404(ClubMembership, pk=pk)
    try:
        if action == 'approve':
            club_services.approve_join(membership, request.user)
            messages.success(request, '已通过「{}」的入社申请'.format(
                membership.record.name))
        elif action == 'reject':
            club_services.reject_join(
                membership, request.user,
                request.POST.get('reason') or '不符合入社条件')
            messages.success(request, '已驳回入社申请')
        else:
            messages.error(request, '未知操作')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:admin_clubs')


@require_POST
@admin_only
@perms.require_system_admin
def club_appoint(request, pk):
    from django.shortcuts import get_object_or_404

    from smass_clubs import services as club_services
    from smass_clubs.models import Club
    from smass_organization.models import StudentRecord

    club = get_object_or_404(Club, pk=pk)
    record = StudentRecord.objects.filter(
        student_no=(request.POST.get('record_no') or '').strip()).first()
    try:
        club_services.appoint_post(
            club, record, request.POST.get('title'),
            request.POST.get('term'), request.user)
        messages.success(request, '任职已创建')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '任命失败：{}'.format(exc))
    return redirect('workspace:admin_clubs')


@require_POST
@admin_only
@perms.require_system_admin
def club_post_end(request, pk):
    from django.shortcuts import get_object_or_404

    from smass_clubs import services as club_services
    from smass_clubs.models import ClubPost

    post = get_object_or_404(ClubPost, pk=pk)
    try:
        club_services.end_post(post, request.user)
        messages.success(request, '已卸任')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '卸任失败：{}'.format(exc))
    return redirect('workspace:admin_clubs')


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
def finance(request):
    from smass_finance.models import FeeItem

    return render(request, 'workspace/admin/finance.html', _ctx(
        request,
        categories=FeeItem._meta.get_field('category').choices
        if hasattr(FeeItem._meta.get_field('category'), 'choices') else (),
        **svc.finance(request.user)))


@require_POST
@admin_only
@perms.require_system_admin
def fee_item_create(request):
    from smass_finance import services as finance_services

    try:
        finance_services.create_fee_item(
            request.user, request.POST.get('code'), request.POST.get('name'),
            request.POST.get('category'), request.POST.get('amount'),
            request.POST.get('term') or '')
        messages.success(request, '收费项已创建')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '创建失败：{}'.format(exc))
    return redirect('workspace:admin_finance')


@require_POST
@admin_only
@perms.require_system_admin
def bill_create(request):
    from smass_finance import services as finance_services
    from smass_finance.models import FeeItem
    from smass_organization.models import StudentRecord

    record = StudentRecord.objects.filter(
        student_no=(request.POST.get('student_no') or '').strip()).first()
    items = list(FeeItem.objects.filter(
        pk__in=request.POST.getlist('fee_items')))
    try:
        bill = finance_services.create_bill(
            record, request.POST.get('term') or '', items, request.user,
            due_date=request.POST.get('due_date') or None)
        messages.success(request, '账单已生成：{}'.format(bill.bill_no))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '生成失败：{}'.format(exc))
    return redirect('workspace:admin_finance')


@require_POST
@admin_only
@perms.require_system_admin
def refund_action(request, pk, action):
    from django.shortcuts import get_object_or_404

    from smass_finance import services as finance_services
    from smass_finance.models import RefundRequest

    refund = get_object_or_404(RefundRequest, pk=pk)
    try:
        if action == 'approve':
            finance_services.approve_refund(refund, request.user)
            messages.success(request, '退费申请已批准')
        elif action == 'reject':
            finance_services.reject_refund(
                refund, request.user,
                request.POST.get('reason') or '不符合退费条件')
            messages.success(request, '退费申请已驳回')
        else:
            messages.error(request, '未知操作')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, '操作失败：{}'.format(exc))
    return redirect('workspace:admin_finance')


@require_GET
@admin_only
def data_exchange(request):
    return render(request, 'workspace/admin/data_exchange.html', _ctx(
        request, **svc.data_exchange(request.user)))


def _import_tmp_dir():
    from pathlib import Path

    from django.conf import settings

    path = Path(settings.BASE_DIR) / 'private_uploads' / 'import_tmp'
    path.mkdir(parents=True, exist_ok=True)
    return path


@require_POST
@admin_only
@perms.require_system_admin
def data_import_preview(request):
    from smass_organization import services as org_services

    upload = request.FILES.get('file')
    if upload is None:
        messages.error(request, '请选择要上传的 CSV 文件')
        return redirect('workspace:admin_data_exchange')
    if upload.size > 8 * 1024 * 1024:
        messages.error(request, '文件超过 8MB 限制')
        return redirect('workspace:admin_data_exchange')
    if not (upload.name or '').lower().endswith('.csv'):
        messages.error(request, '当前仅支持 CSV 模板')
        return redirect('workspace:admin_data_exchange')
    try:
        text = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        messages.error(request, '文件需为 UTF-8 编码')
        return redirect('workspace:admin_data_exchange')

    job, preview = org_services.import_preview(
        text, actor=request.user.login_name)
    from uuid import uuid4

    token = uuid4().hex
    (_import_tmp_dir() / '{}.csv'.format(token)).write_text(
        text, encoding='utf-8')
    request.session['import_token'] = token
    from smass_organization.models import DataImportRowError

    errors = list(DataImportRowError.objects.filter(job=job).order_by('row_number')[:100])
    return render(request, 'workspace/admin/data_import_preview.html', _ctx(
        request, job=job, preview=preview[:60], preview_total=len(preview),
        errors=errors, token=token))


@require_POST
@admin_only
@perms.require_system_admin
@perms.require_recent_auth
def data_import_commit(request):
    from smass_organization import services as org_services

    token = request.session.get('import_token') or ''
    path = _import_tmp_dir() / '{}.csv'.format(token) if token else None
    if path is None or not path.exists():
        messages.error(request, '预检文件已过期，请重新上传')
        return redirect('workspace:admin_data_exchange')
    text = path.read_text(encoding='utf-8')
    job, stats = org_services.import_commit(
        text, actor=request.user.login_name)
    path.unlink(missing_ok=True)
    request.session.pop('import_token', None)
    messages.success(request, '导入完成：新增 {}，更新 {}，失败 {}'.format(
        stats.get('created', 0), stats.get('updated', 0),
        stats.get('failed', 0)))
    return redirect('workspace:admin_data_exchange')


@require_GET
@admin_only
def monitoring(request):
    return render(request, 'workspace/admin/monitoring.html', _ctx(
        request, **svc.monitoring(request.user)))


@require_GET
@admin_only
def audit(request):
    from ..services import pagination as pagination_svc

    data = svc.audit(request.user)
    page_info = pagination_svc.paginate(data['logs'], request.GET.get('page'))
    data['logs'] = page_info['items']
    return render(request, 'workspace/admin/audit.html', _ctx(
        request, page_info=page_info,
        querystring=pagination_svc.querystring_without_page(request),
        **data))


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
