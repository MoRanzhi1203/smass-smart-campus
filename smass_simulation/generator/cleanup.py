"""P9 安全清理：按仿真前缀/批次删除 V2.1 生成的数据（默认 dry-run）。

只处理仿真数据（`SIM-` 组织与资源、`sim_` 账号、`SEC-`/`COH-` 教学、`S...` 仿真学号、
`sim:` 通知），不触碰产品既有数据；必须显式 ``confirm=True`` 才执行。
"""
from __future__ import annotations

from django.db import transaction

STUDENT_PREFIX = 'S'
SIM_ACCOUNT_PREFIXES = ('sim_stu_', 'sim_tea_', 'sim_adm_', 'sim_dorm_')


def cleanup(*, confirm=False):
    from r21_account.models import Account, StudentProfile, TeacherProfile
    from smass_academic.models import (
        Course, Enrollment, TeachingAssignment, TeachingSection,
    )
    from smass_activities.models import (
        Activity, ActivityCredit, ActivityRegistration,
    )
    from smass_attendance.models import (
        AttendanceRecord, AttendanceSession, LeaveRequest, MakeupRequest,
    )
    from smass_clubs.models import Club, ClubMembership, ClubPost
    from smass_dormitory.models import (
        Bed, DormAssignment, DormBuilding, DormChangeRequest,
        DormCheckoutRequest, DormInspection, DormManagerScope, DormRepair,
        DormRoom, DormZone,
    )
    from smass_facilities.models import Building, Room
    from smass_finance.models import Bill, BillItem, FeeItem, Payment, RefundRequest
    from smass_organization.models import (
        OrganizationMembership, OrganizationUnit, StudentChangeRequest,
        StudentRecord,
    )
    from smass_scheduling.models import (
        Cohort, LessonRequirement, ScheduleEntry, ScheduleRun,
    )
    from smass_simulation.models import SimulationBatch, SimulationObject
    from smass_workflow.models import Notification

    sim_classes = OrganizationUnit.objects.filter(code__startswith='SIM-CLS-')
    sim_sections = TeachingSection.objects.filter(code__startswith='SEC-')
    sim_students = StudentRecord.objects.filter(
        student_no__startswith=STUDENT_PREFIX)
    sim_accounts = Account.objects.none()
    for prefix in SIM_ACCOUNT_PREFIXES:
        sim_accounts = sim_accounts | Account.objects.filter(
            login_name__startswith=prefix)

    plan = {
        'enrollments': Enrollment.objects.filter(
            section__code__startswith='SEC-').count(),
        'attendance_records': AttendanceRecord.objects.filter(
            session__unit__code__startswith='SIM-CLS-').count(),
        'attendance_sessions': AttendanceSession.objects.filter(
            unit__code__startswith='SIM-CLS-').count(),
        'leaves': LeaveRequest.objects.filter(
            record__student_no__startswith=STUDENT_PREFIX).count(),
        'dorm_assignments': DormAssignment.objects.filter(
            student__student_no__startswith=STUDENT_PREFIX).count(),
        'dorm_beds': Bed.objects.filter(
            room__room__code__startswith='SIM-DORM-').count(),
        'bills': Bill.objects.filter(bill_no__startswith='BILL-').count(),
        'clubs': Club.objects.filter(code__startswith='SIM-CLUB-').count(),
        'activities': Activity.objects.filter(
            created_by='simulation').count(),
        'notifications': Notification.objects.filter(
            event_key__startswith='sim:').count(),
        'sections': sim_sections.count(),
        'students': sim_students.count(),
        'accounts': sim_accounts.count(),
        'units': OrganizationUnit.objects.filter(
            code__startswith='SIM-').count(),
    }
    if not confirm:
        return {'dry_run': True, 'plan': plan, 'deleted': None}

    deleted = {}
    with transaction.atomic():
        def drop(key, queryset):
            result = queryset.delete()
            deleted[key] = result[0] if isinstance(result, tuple) else result

        drop('enrollments', Enrollment.objects.filter(
            section__code__startswith='SEC-'))
        drop('attendance_records', AttendanceRecord.objects.filter(
            session__unit__code__startswith='SIM-CLS-'))
        drop('attendance_sessions', AttendanceSession.objects.filter(
            unit__code__startswith='SIM-CLS-'))
        drop('makeups', MakeupRequest.objects.filter(
            record__student_no__startswith=STUDENT_PREFIX))
        drop('leaves', LeaveRequest.objects.filter(
            record__student_no__startswith=STUDENT_PREFIX))
        drop('dorm_requests', DormChangeRequest.objects.filter(
            student__student_no__startswith=STUDENT_PREFIX))
        drop('dorm_checkouts', DormCheckoutRequest.objects.filter(
            student__student_no__startswith=STUDENT_PREFIX))
        drop('dorm_repairs', DormRepair.objects.filter(
            room__room__code__startswith='SIM-DORM-'))
        drop('dorm_inspections', DormInspection.objects.filter(
            building__building__code__startswith='SIM-DORM-'))
        drop('dorm_assignments', DormAssignment.objects.filter(
            student__student_no__startswith=STUDENT_PREFIX))
        drop('dorm_scopes', DormManagerScope.objects.filter(
            building__building__code__startswith='SIM-DORM-'))
        drop('beds', Bed.objects.filter(
            room__room__code__startswith='SIM-DORM-'))
        drop('dorm_rooms', DormRoom.objects.filter(
            room__code__startswith='SIM-DORM-'))
        drop('dorm_buildings', DormBuilding.objects.filter(
            building__code__startswith='SIM-DORM-'))
        drop('dorm_zones', DormZone.objects.filter(code__startswith='SIM-ZONE'))
        drop('bill_items', BillItem.objects.filter(
            bill__bill_no__startswith='BILL-'))
        drop('payments', Payment.objects.filter(
            bill__bill_no__startswith='BILL-'))
        drop('refunds', RefundRequest.objects.filter(
            bill__bill_no__startswith='BILL-'))
        drop('bills', Bill.objects.filter(bill_no__startswith='BILL-'))
        drop('fee_items', FeeItem.objects.filter(code__startswith='SIM-FEE-'))
        drop('activity_registrations', ActivityRegistration.objects.filter(
            activity__created_by='simulation'))
        drop('activity_credits', ActivityCredit.objects.filter(
            activity__created_by='simulation'))
        drop('activities', Activity.objects.filter(created_by='simulation'))
        drop('club_memberships', ClubMembership.objects.filter(
            club__code__startswith='SIM-CLUB-'))
        drop('club_posts', ClubPost.objects.filter(
            club__code__startswith='SIM-CLUB-'))
        drop('clubs', Club.objects.filter(code__startswith='SIM-CLUB-'))
        drop('notifications', Notification.objects.filter(
            event_key__startswith='sim:'))
        drop('assignments', TeachingAssignment.objects.filter(
            section__code__startswith='SEC-'))
        drop('entries', ScheduleEntry.objects.filter(
            requirement__section__code__startswith='SEC-'))
        drop('requirements', LessonRequirement.objects.filter(
            section__code__startswith='SEC-'))
        drop('runs', ScheduleRun.objects.filter(
            term__year__code='2025'))
        drop('sections', TeachingSection.objects.filter(
            code__startswith='SEC-'))
        drop('cohorts', Cohort.objects.filter(code__startswith='COH-'))
        drop('courses', Course.objects.filter(code__startswith='SIM-').filter(
            code__startswith='SIM-M'))
        drop('public_courses', Course.objects.filter(
            code__startswith='PUB-'))
        drop('change_requests', StudentChangeRequest.objects.filter(
            record__student_no__startswith=STUDENT_PREFIX))
        drop('student_records', StudentRecord.objects.filter(
            student_no__startswith=STUDENT_PREFIX))
        drop('student_profiles', StudentProfile.objects.filter(
            student_no__startswith=STUDENT_PREFIX))
        account_ids = list(sim_accounts.values_list('id', flat=True))
        from r21_account.models import AccountRole

        drop('account_roles', AccountRole.objects.filter(
            account_id__in=account_ids))
        drop('teacher_profiles', TeacherProfile.objects.filter(
            account_id__in=account_ids))
        drop('accounts', Account.objects.filter(id__in=account_ids))
        drop('memberships', OrganizationMembership.objects.filter(
            unit__code__startswith='SIM-'))
        for unit_prefix in ('SIM-CLS-', 'SIM-GRD-', 'SIM-MAJ-', 'SIM-COL-'):
            drop('units_{}'.format(unit_prefix.strip('-').lower()),
                 OrganizationUnit.objects.filter(code__startswith=unit_prefix))
        drop('rooms', Room.objects.filter(
            code__startswith='SIM-T')
            | Room.objects.filter(code__startswith='SIM-DORM-'))
        drop('buildings', Building.objects.filter(
            code__startswith='SIM-TEACH')
            | Building.objects.filter(code__startswith='SIM-DORM-'))
        drop('sim_objects', SimulationObject.objects.all())
        drop('sim_batches', SimulationBatch.objects.all())
    return {'dry_run': False, 'plan': plan, 'deleted': deleted}
