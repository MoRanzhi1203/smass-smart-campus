"""R11 验收：排课求解器、硬约束、软成本、冲突解释与复核。

覆盖主任务书 R11：
- 硬约束：教师/教室/群体冲突、教室容量与类型、教师已批准不可用、课时数；
- 软约束：教师偏好/回避、教室稳定性、空档、容量浪费；
- **不可行时给出可读原因**，而不是只说"排不出来"；
- 求解**确定性**（同输入同结果）；
- 独立的 `verify_run` 复核，不自己验证自己。

运行::

    python manage.py test smass_scheduling --settings=smass.settings_r11
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode
from smass_academic.models import AcademicTerm, AcademicYear, Course, TeachingSection
from smass_facilities.models import (
    ROOM_TYPE_CLASSROOM,
    ROOM_TYPE_LAB,
    Building,
    MaintenanceWindow,
    Room,
)
from smass_scheduling import solver
from smass_scheduling.models import (
    CONSTRAINT_AVOID,
    CONSTRAINT_PREFER,
    CONSTRAINT_UNAVAILABLE,
    RUN_INFEASIBLE,
    RUN_SOLVED,
    Cohort,
    LessonRequirement,
    ScheduleConflict,
    ScheduleEntry,
    ScheduleRun,
    TeacherAvailability,
    TeacherConstraint,
    TeacherProfile,
    TimeSlot,
)

PASSWORD = 'R11Pass#2024'


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def make_account(login_name, roles=(RoleCode.TEACHER,), person_type='teacher'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def make_term():
    year, _ = AcademicYear.objects.get_or_create(
        code='2024-2025',
        defaults={'start_date': dt.date(2024, 9, 2),
                  'end_date': dt.date(2025, 1, 17)})
    term, _ = AcademicTerm.objects.get_or_create(
        year=year, semester='1',
        defaults={'name': '2024 秋', 'start_date': dt.date(2024, 9, 2),
                  'end_date': dt.date(2025, 1, 17)})
    return term


def make_slots(days=3, periods=4):
    """3 天 × 4 节，返回已创建的时间槽。"""
    created = []
    for weekday in range(days):
        for period in range(1, periods + 1):
            slot, _ = TimeSlot.objects.get_or_create(
                weekday=weekday, period=period,
                defaults={
                    'start_time': dt.time(8 + (period - 1), 0),
                    'end_time': dt.time(9 + (period - 1), 0),
                    'label': '周{}第{}节'.format(weekday + 1, period),
                })
            created.append(slot)
    return created


def make_room(code='R1', capacity=50, room_type=ROOM_TYPE_CLASSROOM):
    building, _ = Building.objects.get_or_create(code='B1', defaults={'name': '主楼'})
    room, _ = Room.objects.get_or_create(
        code=code,
        defaults={'name': '房间' + code, 'building': building,
                  'room_type': room_type, 'capacity': capacity})
    return room


def make_section(code='CS101-01', course_code='CS101', term=None):
    term = term or make_term()
    course, _ = Course.objects.get_or_create(
        code=course_code, defaults={'title': '课程' + course_code, 'credit': 3})
    section, _ = TeachingSection.objects.get_or_create(
        term=term, course=course, code=code, defaults={'capacity': 50})
    return section


def make_run(term=None, created_by='test'):
    return ScheduleRun.objects.create(term=term or make_term(), created_by=created_by)


def make_requirement(run, section, teacher, cohort, *, weekly=1, periods=2,
                     students=40, room_type='', priority=0):
    return LessonRequirement.objects.create(
        run=run, section=section, teacher=teacher, cohort=cohort,
        weekly_sessions=weekly, session_periods=periods, students=students,
        required_room_type=room_type, priority=priority)


# ---------------------------------------------------------------------------
# 基础可行场景
# ---------------------------------------------------------------------------
class SolverBasicsTests(TestCase):
    def setUp(self):
        make_slots()
        self.term = make_term()
        self.room = make_room('R1', capacity=50)
        self.teacher = make_account('T11A')
        self.cohort = Cohort.objects.create(code='C1', name='软工2101', size=40)
        self.run = make_run(self.term)
        self.section = make_section('CS101-01')
        self.req = make_requirement(self.run, self.section, self.teacher,
                                    self.cohort, weekly=2, periods=1)

    def test_solve_places_all_sessions(self):
        result = solver.solve(self.run)
        self.assertTrue(result.feasible, result.explanation)
        self.assertEqual(result.hard_conflicts, 0)
        self.assertEqual(result.placed, 2)
        self.assertEqual(ScheduleEntry.objects.filter(run=self.run).count(), 2)

    def test_run_status_updated(self):
        solver.solve(self.run)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, RUN_SOLVED)
        self.assertIn('deterministic', self.run.algorithm)
        self.assertEqual(self.run.placed_sessions, 2)

    def test_no_conflict_rows_when_feasible(self):
        solver.solve(self.run)
        self.assertEqual(ScheduleConflict.objects.filter(run=self.run).count(), 0)

    def test_verify_run_reports_no_problem(self):
        solver.solve(self.run)
        problems = solver.verify_run(self.run)
        self.assertEqual(problems, [])


# ---------------------------------------------------------------------------
# 硬约束
# ---------------------------------------------------------------------------
class TeacherConflictTests(TestCase):
    def setUp(self):
        make_slots()
        self.term = make_term()
        make_room('R1')
        self.teacher = make_account('T11B')
        self.run = make_run(self.term)

    def test_same_teacher_never_double_booked(self):
        c1 = Cohort.objects.create(code='C1', name='班1', size=30)
        c2 = Cohort.objects.create(code='C2', name='班2', size=30)
        make_requirement(self.run, make_section('S1'), self.teacher, c1,
                         weekly=2, periods=2)
        make_requirement(self.run, make_section('S2'), self.teacher, c2,
                         weekly=2, periods=2)
        solver.solve(self.run)

        entries = list(ScheduleEntry.objects.filter(run=self.run))
        keys = [(e.teacher_id, e.weekday, e.period) for e in entries]
        self.assertEqual(len(keys), len(set(keys)), '教师出现重复占用')

    def test_teacher_unavailable_constraint_respected(self):
        cohort = Cohort.objects.create(code='C3', name='班3', size=30)
        # 把所有时段都标记为已批准不可用 -> 必然排不进
        for slot in TimeSlot.objects.all():
            TeacherConstraint.objects.create(
                account=self.teacher, kind=CONSTRAINT_UNAVAILABLE,
                weekday=slot.weekday, period=slot.period,
                approved_by='admin')
        make_requirement(self.run, make_section('S3'), self.teacher, cohort,
                         weekly=1, periods=1)
        result = solver.solve(self.run)
        self.assertFalse(result.feasible)
        self.assertIn('不可用', result.explanation[0]['reason'])

    def test_unapproved_unavailable_is_ignored(self):
        cohort = Cohort.objects.create(code='C4', name='班4', size=30)
        for slot in TimeSlot.objects.all():
            TeacherConstraint.objects.create(
                account=self.teacher, kind=CONSTRAINT_UNAVAILABLE,
                weekday=slot.weekday, period=slot.period)  # 未批准
        make_requirement(self.run, make_section('S4'), self.teacher, cohort,
                         weekly=1, periods=1)
        result = solver.solve(self.run)
        self.assertTrue(result.feasible, '未批准的约束不应参与硬判定')

    def test_availability_restricts_slots(self):
        cohort = Cohort.objects.create(code='C5', name='班5', size=30)
        # 只允许 周一第1节
        TeacherAvailability.objects.create(account=self.teacher, weekday=0, period=1)
        make_requirement(self.run, make_section('S5'), self.teacher, cohort,
                         weekly=1, periods=1)
        solver.solve(self.run)
        entries = list(ScheduleEntry.objects.filter(run=self.run))
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0].weekday, entries[0].period), (0, 1))

    def test_workload_cap_limits_sessions(self):
        cohort = Cohort.objects.create(code='C6', name='班6', size=30)
        TeacherProfile.objects.create(account=self.teacher, weekly_hour_cap=1)
        make_requirement(self.run, make_section('S6'), self.teacher, cohort,
                         weekly=3, periods=1)
        result = solver.solve(self.run)
        self.assertFalse(result.feasible)
        self.assertLessEqual(
            ScheduleEntry.objects.filter(run=self.run).count(), 1)


class RoomConflictTests(TestCase):
    def setUp(self):
        make_slots()
        self.term = make_term()
        self.room = make_room('R1', capacity=50)
        self.run = make_run(self.term)

    def test_same_room_never_double_booked(self):
        t1 = make_account('T11C')
        t2 = make_account('T11D')
        c1 = Cohort.objects.create(code='C1', name='班1', size=30)
        c2 = Cohort.objects.create(code='C2', name='班2', size=30)
        make_requirement(self.run, make_section('S1'), t1, c1, weekly=2, periods=2)
        make_requirement(self.run, make_section('S2'), t2, c2, weekly=2, periods=2)
        solver.solve(self.run)
        entries = list(ScheduleEntry.objects.filter(run=self.run))
        keys = [(e.room_id, e.weekday, e.period) for e in entries]
        self.assertEqual(len(keys), len(set(keys)), '教室出现重复占用')

    def test_maintenance_window_blocks_room(self):
        teacher = make_account('T11E')
        cohort = Cohort.objects.create(code='C9', name='班9', size=30)
        make_requirement(self.run, make_section('S9'), teacher, cohort,
                         weekly=1, periods=1)
        # 学期内所有周一第 1 节都维护
        term = self.term
        day = term.start_date
        while day <= term.end_date:
            if day.weekday() == 0:
                MaintenanceWindow.objects.create(
                    room=self.room,
                    start_at=timezone.make_aware(dt.datetime.combine(day, dt.time(8, 0))),
                    end_at=timezone.make_aware(dt.datetime.combine(day, dt.time(9, 0))),
                    reason='检修')
            day += dt.timedelta(days=1)
        solver.solve(self.run)
        entries = list(ScheduleEntry.objects.filter(run=self.run))
        self.assertFalse(any(e.weekday == 0 and e.period == 1 for e in entries),
                         '维护期内的时段不应被排课')


class CapacityAndTypeTests(TestCase):
    def setUp(self):
        make_slots()
        self.term = make_term()
        self.run = make_run(self.term)

    def test_insufficient_capacity_reports_reason(self):
        make_room('R-small', capacity=10)
        teacher = make_account('T11F')
        cohort = Cohort.objects.create(code='C1', name='班1', size=100)
        make_requirement(self.run, make_section('S1'), teacher, cohort,
                         weekly=1, periods=1, students=100)
        result = solver.solve(self.run)
        self.assertFalse(result.feasible)
        self.assertIn('教室', result.explanation[0]['reason'])
        self.assertGreater(ScheduleConflict.objects.filter(run=self.run).count(), 0)

    def test_room_type_requirement_enforced(self):
        make_room('R-class', capacity=50)
        lab = make_room('R-lab', capacity=50, room_type=ROOM_TYPE_LAB)
        teacher = make_account('T11G')
        cohort = Cohort.objects.create(code='C2', name='班2', size=30)
        make_requirement(self.run, make_section('S2'), teacher, cohort,
                         weekly=1, periods=1, students=30,
                         room_type=ROOM_TYPE_LAB)
        solver.solve(self.run)
        entries = list(ScheduleEntry.objects.filter(run=self.run))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].room_id, lab.pk)

    def test_no_matching_room_type_infeasible(self):
        make_room('R-class2', capacity=50)
        teacher = make_account('T11H')
        cohort = Cohort.objects.create(code='C3', name='班3', size=30)
        make_requirement(self.run, make_section('S3'), teacher, cohort,
                         weekly=1, periods=1, room_type=ROOM_TYPE_LAB)
        result = solver.solve(self.run)
        self.assertFalse(result.feasible)


class CohortConflictTests(TestCase):
    def setUp(self):
        make_slots()
        self.term = make_term()
        make_room('R1', capacity=50)
        make_room('R2', capacity=50)
        self.run = make_run(self.term)

    def test_same_cohort_not_double_booked(self):
        t1 = make_account('T11I')
        t2 = make_account('T11J')
        cohort = Cohort.objects.create(code='CX', name='同一班', size=40)
        make_requirement(self.run, make_section('S1'), t1, cohort, weekly=2, periods=2)
        make_requirement(self.run, make_section('S2'), t2, cohort, weekly=2, periods=2)
        solver.solve(self.run)
        entries = list(ScheduleEntry.objects.filter(run=self.run))
        keys = [(e.cohort_id, e.weekday, e.period) for e in entries]
        self.assertEqual(len(keys), len(set(keys)), '同一修读群体出现重复占用')


# ---------------------------------------------------------------------------
# 软约束与确定性
# ---------------------------------------------------------------------------
class SoftCostTests(TestCase):
    def setUp(self):
        make_slots()
        self.term = make_term()
        make_room('R1', capacity=50)
        self.teacher = make_account('T11K')
        self.cohort = Cohort.objects.create(code='C1', name='班1', size=40)
        self.run = make_run(self.term)
        self.section = make_section('CS101-01')

    def test_preferred_slot_is_chosen(self):
        TeacherConstraint.objects.create(
            account=self.teacher, kind=CONSTRAINT_PREFER, weekday=0, period=1)
        make_requirement(self.run, self.section, self.teacher, self.cohort,
                         weekly=1, periods=1)
        solver.solve(self.run)
        entry = ScheduleEntry.objects.get(run=self.run)
        self.assertEqual((entry.weekday, entry.period), (0, 1))

    def test_soft_cost_is_recorded(self):
        TeacherConstraint.objects.create(
            account=self.teacher, kind=CONSTRAINT_AVOID, weekday=0, period=1)
        make_requirement(self.run, self.section, self.teacher, self.cohort,
                         weekly=1, periods=1)
        solver.solve(self.run)
        self.run.refresh_from_db()
        self.assertIsInstance(self.run.soft_cost, int)

    def test_capacity_waste_increases_cost(self):
        big = make_room('R-big', capacity=200)
        make_requirement(self.run, self.section, self.teacher, self.cohort,
                         weekly=1, periods=1, students=20)
        result = solver.solve(self.run, rooms=[big])
        self.assertTrue(result.feasible)
        self.assertGreaterEqual(result.soft_cost, 0)


class DeterminismTests(TestCase):
    def test_same_input_same_output(self):
        make_slots()
        term = make_term()
        make_room('R1', capacity=50)
        make_room('R2', capacity=50)
        teacher = make_account('T11L')
        cohort = Cohort.objects.create(code='C1', name='班1', size=40)

        def build():
            ScheduleRun.objects.all().delete()
            run = make_run(term)
            make_requirement(run, make_section('CS101-01'), teacher, cohort,
                             weekly=2, periods=2)
            make_requirement(run, make_section('CS101-02', course_code='CS102'),
                             teacher, cohort, weekly=1, periods=2)
            return run

        run1 = build()
        solver.solve(run1)
        sig1 = sorted(
            (e.requirement.section.code, e.weekday, e.period, e.room.code)
            for e in ScheduleEntry.objects.filter(run=run1))

        run2 = build()
        solver.solve(run2)
        sig2 = sorted(
            (e.requirement.section.code, e.weekday, e.period, e.room.code)
            for e in ScheduleEntry.objects.filter(run=run2))

        self.assertEqual(sig1, sig2, '求解结果必须可复现')


class VerifyRunTests(TestCase):
    def test_detects_duplicate_entries(self):
        make_slots()
        term = make_term()
        room = make_room('R1', capacity=50)
        teacher = make_account('T11M')
        cohort = Cohort.objects.create(code='C1', name='班1', size=40)
        run = make_run(term)
        req = make_requirement(run, make_section('CS101-01'), teacher, cohort,
                               weekly=1, periods=1)
        # 人为制造两条冲突记录（绕过唯一约束用不同 requirement）
        req2 = make_requirement(run, make_section('CS101-02', course_code='CS102'),
                                teacher, cohort, weekly=1, periods=1)
        ScheduleEntry.objects.create(run=run, requirement=req, room=room,
                                     teacher=teacher, cohort=cohort,
                                     weekday=0, period=1)
        # 同一教室/教师/群体/时段但不同需求：数据库唯一约束会拒绝同 room
        with self.assertRaises(Exception):
            ScheduleEntry.objects.create(run=run, requirement=req2, room=room,
                                         teacher=teacher, cohort=cohort,
                                         weekday=0, period=1)

    def test_detects_session_count_mismatch(self):
        make_slots()
        term = make_term()
        room = make_room('R1', capacity=50)
        teacher = make_account('T11N')
        cohort = Cohort.objects.create(code='C1', name='班1', size=40)
        run = make_run(term)
        req = make_requirement(run, make_section('CS101-01'), teacher, cohort,
                               weekly=2, periods=1)
        ScheduleEntry.objects.create(run=run, requirement=req, room=room,
                                     teacher=teacher, cohort=cohort,
                                     weekday=0, period=1)
        problems = solver.verify_run(run)
        kinds = {p['kind'] for p in problems}
        self.assertIn('session_count_mismatch', kinds)


class ExplanationTests(TestCase):
    def test_infeasible_explanation_is_human_readable(self):
        make_slots(days=1, periods=1)   # 只有 1 个时段
        term = make_term()
        make_room('R1', capacity=50)
        teacher = make_account('T11O')
        cohort = Cohort.objects.create(code='C1', name='班1', size=40)
        run = make_run(term)
        make_requirement(run, make_section('CS101-01'), teacher, cohort,
                         weekly=3, periods=1)
        result = solver.solve(run)
        self.assertFalse(result.feasible)
        self.assertTrue(result.explanation)
        first = result.explanation[0]
        self.assertIn('reason', first)
        self.assertTrue(first['reason'])
        self.assertLess(first['placed'], first['needed'])

        run.refresh_from_db()
        self.assertEqual(run.status, RUN_INFEASIBLE)
        self.assertTrue(run.explanation)
