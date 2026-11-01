"""P4 教学数据：学年学期、教室、课程、教学班、任课、排课、选课。

排课用确定性贪心（教室/教师/修读群体三类硬约束），生成后调用
``smass_scheduling.solver.verify_run`` 独立复核，不复用求解器结果。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from smass_academic.models import (
    AcademicTerm,
    AcademicYear,
    Course,
    Enrollment,
    TeachingAssignment,
    TeachingSection,
)
from smass_facilities.models import Building, Room
from smass_organization.models import OrganizationUnit, StudentRecord
from smass_scheduling import solver
from smass_scheduling.models import (
    RUN_SOLVED,
    Cohort,
    LessonRequirement,
    ScheduleEntry,
    ScheduleRun,
)

BATCH_SIZE = 500
WEEKDAYS = (1, 2, 3, 4, 5)
PERIODS = (1, 2, 3, 4, 5, 6)
SESSIONS_PER_SECTION = 1
ROOM_CAPACITY = 60
ROOMS_PER_BUILDING = 80
BUILDINGS = 3
MAX_TEACHER_PER_DAY = 5
SECTION_PREFIX = 'SEC-'

PUBLIC_COURSES = [
    ('PUB-MATH', '高等数学', '3.0', '公共必修'),
    ('PUB-ENG', '大学英语', '3.0', '公共必修'),
]
MAJOR_COURSE_SUFFIXES = [
    ('核心', '4.0', '专业必修'), ('核心', '4.0', '专业必修'),
    ('核心', '3.0', '专业必修'), ('核心', '3.0', '专业必修'),
    ('选修', '2.0', '专业选修'), ('选修', '2.0', '专业选修'),
]


class TeachingError(Exception):
    pass


def ensure_term():
    year, _ = AcademicYear.objects.update_or_create(
        code='2025', defaults={
            'start_date': date(2025, 9, 1), 'end_date': date(2026, 8, 31),
            'is_active': True})
    term, _ = AcademicTerm.objects.update_or_create(
        year=year, semester='1', defaults={
            'name': '2025-2026-1', 'start_date': date(2025, 9, 1),
            'end_date': date(2026, 1, 15), 'is_active': True})
    return term


def ensure_rooms(target_rooms=None):
    import math as _math
    rooms_needed = target_rooms or (BUILDINGS * ROOMS_PER_BUILDING)
    building_count = max(1, int(_math.ceil(rooms_needed / ROOMS_PER_BUILDING)))
    rooms = []
    for building_index in range(building_count):
        building, _ = Building.objects.update_or_create(
            code='SIM-TEACH-{}'.format(building_index + 1),
            defaults={'name': '仿真教学楼{}'.format(building_index + 1),
                      'campus': '主校区'})
        existing = {room.code: room for room in Room.objects.filter(
            building=building)}
        for index in range(ROOMS_PER_BUILDING):
            code = 'SIM-T{}-{:03d}'.format(building_index + 1, index + 1)
            room = existing.get(code)
            if room is None:
                room = Room.objects.create(
                    code=code, name='教室{}'.format(index + 1),
                    building=building, floor=str(index // 20 + 1),
                    capacity=ROOM_CAPACITY)
            rooms.append(room)
    return rooms[0].building, rooms


def ensure_courses(majors):
    courses = {}
    for code, title, credit, course_type in PUBLIC_COURSES:
        course, _ = Course.objects.update_or_create(
            code=code, defaults={'title': title, 'credit': credit,
                                 'course_type': course_type})
        courses[code] = course
    for major in majors:
        short = major.code.split('-')[-1]
        for order, (label, credit, course_type) in enumerate(
                MAJOR_COURSE_SUFFIXES, start=1):
            code = 'SIM-M{}-C{}'.format(short, order)
            course, _ = Course.objects.update_or_create(
                code=code, defaults={
                    'title': '{}（{}）'.format(major.name, label),
                    'credit': credit, 'course_type': course_type})
            courses[(major.pk, order)] = course
    return courses


def course_plan():
    plan = [('major', order) for order in
            range(1, len(MAJOR_COURSE_SUFFIXES) + 1)]
    plan.extend(('public', code) for code, *_rest in PUBLIC_COURSES)
    return plan


def section_class_code(section_code):
    """``SEC-XXXX-YY`` → ``SIM-CLS-XXXX``。"""
    parts = section_code.split('-')
    return 'SIM-CLS-{}'.format(parts[1])


def generate_teaching(config, ctx, *, dry_run=False):
    classes = list(OrganizationUnit.objects.filter(
        code__startswith='SIM-CLS-').order_by('code'))
    majors = list(OrganizationUnit.objects.filter(
        code__startswith='SIM-MAJ-').order_by('code'))
    teachers = list(Account_objects())
    if not classes or not majors or not teachers:
        raise TeachingError('请先生成组织、学生与教师（--stage org,students,staff）')

    plan = course_plan()
    total_sections = len(classes) * len(plan)
    if dry_run:
        return {'term': '2025-2026-1', 'sections': total_sections,
                'assignments': total_sections, 'requirements': total_sections,
                'entries': total_sections * SESSIONS_PER_SECTION,
                'dry_run': True}

    term = ensure_term()
    needed_rooms = max(120, int(len(classes) * 1.2))
    _building, rooms = ensure_rooms(needed_rooms)
    courses = ensure_courses(majors)
    teachers_by_college = defaultdict(list)
    for teacher in teachers:
        membership = teacher.org_memberships.filter(
            unit__unit_type='college').select_related('unit').first()
        if membership is not None:
            teachers_by_college[membership.unit.code].append(teacher)

    cohorts = {}
    sections = []
    section_class = {}
    section_teacher = {}
    assignments = []
    teacher_cursor = defaultdict(int)
    for class_unit in classes:
        major = class_unit.parent
        college = major.parent
        pool = teachers_by_college.get(college.code) or teachers
        suffix = class_unit.code.replace('SIM-CLS-', '')
        cohort, _ = Cohort.objects.update_or_create(
            code='COH-{}'.format(suffix),
            defaults={'name': '{}修读群体'.format(class_unit.name),
                      'size': config['students_per_class']})
        cohorts[class_unit.pk] = cohort
        for order, (kind, ref) in enumerate(plan, start=1):
            course = (courses[(major.pk, ref)] if kind == 'major'
                      else courses[ref])
            section, _ = TeachingSection.objects.update_or_create(
                term=term, code='{}{}-{:02d}'.format(SECTION_PREFIX, suffix, order),
                defaults={'course': course,
                          'capacity': config['students_per_class'] + 10,
                          'status': TeachingSection.STATUS_OPEN})
            teacher = pool[teacher_cursor[college.code] % len(pool)]
            teacher_cursor[college.code] += 1
            sections.append(section)
            section_class[section.pk] = class_unit
            section_teacher[section.pk] = teacher
            assignments.append(TeachingAssignment(
                section=section, account=teacher, assigned_by='simulation'))

    TeachingAssignment.objects.filter(
        section__term=term, section__code__startswith=SECTION_PREFIX).delete()
    TeachingAssignment.objects.bulk_create(
        assignments, ignore_conflicts=True, batch_size=BATCH_SIZE)

    run, _ = ScheduleRun.objects.update_or_create(
        term=term,
        defaults={'status': RUN_SOLVED, 'algorithm': 'greedy'})
    ScheduleEntry.objects.filter(run=run).delete()
    LessonRequirement.objects.filter(run=run).delete()

    class_map = {item.code: item for item in classes}
    requirements = []
    for section in sections:
        class_unit = section_class[section.pk]
        requirements.append(LessonRequirement(
            run=run, section=section, teacher=section_teacher[section.pk],
            cohort=cohorts[class_unit.pk],
            weekly_sessions=SESSIONS_PER_SECTION, session_periods=2,
            students=config['students_per_class']))
    LessonRequirement.objects.bulk_create(requirements, batch_size=BATCH_SIZE)

    loaded = list(LessonRequirement.objects.filter(run=run)
                  .select_related('section', 'teacher', 'cohort'))
    entries = _schedule(loaded, rooms)
    ScheduleEntry.objects.bulk_create(entries, batch_size=BATCH_SIZE)
    problems = solver.verify_run(run)
    run.hard_conflicts = len(problems)
    run.save(update_fields=['hard_conflicts'])

    enrollments = _enroll(sections, section_class, config)
    ctx.stage_done('teaching', {
        'sections': len(sections), 'entries': len(entries),
        'enrollments': enrollments, 'conflicts': len(problems),
    })
    return {'term': term.name, 'sections': len(sections),
            'assignments': len(assignments),
            'requirements': len(loaded), 'entries': len(entries),
            'enrollments': enrollments, 'conflicts': len(problems),
            'conflict_samples': problems[:5]}


def Account_objects():
    from r21_account.models import Account

    return Account.objects.filter(login_name__startswith='sim_tea_') \
        .order_by('login_name')


def _schedule(requirements, rooms):
    room_used = defaultdict(set)
    teacher_used = set()
    cohort_used = set()
    teacher_day = defaultdict(int)
    entries = []
    starts = (1, 3, 5)
    for requirement in requirements:
        need = requirement.weekly_sessions
        for weekday in WEEKDAYS:
            if need <= 0:
                break
            for start in starts:
                if need <= 0:
                    break
                second = start + 1
                if second > max(PERIODS):
                    continue
                if (requirement.teacher_id, weekday, start) in teacher_used:
                    continue
                if (requirement.teacher_id, weekday, second) in teacher_used:
                    continue
                if (requirement.cohort_id, weekday, start) in cohort_used:
                    continue
                if (requirement.cohort_id, weekday, second) in cohort_used:
                    continue
                if (teacher_day[(requirement.teacher_id, weekday)] + 2
                        > MAX_TEACHER_PER_DAY):
                    continue
                room = None
                for candidate in rooms:
                    if (candidate.pk not in room_used[(weekday, start)]
                            and candidate.pk not in room_used[(weekday, second)]):
                        room = candidate
                        break
                if room is None:
                    continue
                for offset, period in enumerate((start, second)):
                    room_used[(weekday, period)].add(room.pk)
                    teacher_used.add((requirement.teacher_id, weekday, period))
                    cohort_used.add((requirement.cohort_id, weekday, period))
                    teacher_day[(requirement.teacher_id, weekday)] += 1
                    entries.append(ScheduleEntry(
                        run_id=requirement.run_id, requirement=requirement,
                        room=room, teacher_id=requirement.teacher_id,
                        cohort_id=requirement.cohort_id, weekday=weekday,
                        period=period,
                        session_index=requirement.weekly_sessions - need + 1))
                need -= 1
        if need > 0:
            raise TeachingError(
                '排课空间不足：教学班 {} 仍缺 {} 次'.format(
                    requirement.section_id, need))
    return entries


def _enroll(sections, section_class, config):
    records = list(StudentRecord.objects.filter(
        student_no__startswith='S', unit__code__startswith='SIM-CLS-')
        .values_list('unit__code', 'account_id'))
    students_by_class = defaultdict(list)
    for class_code, account_id in records:
        students_by_class[class_code].append(account_id)

    Enrollment.objects.filter(
        section__code__startswith=SECTION_PREFIX).delete()
    rows = []
    for section in sections:
        class_unit = section_class[section.pk]
        for account_id in students_by_class.get(class_unit.code, []):
            rows.append(Enrollment(section=section, account_id=account_id,
                                   status=Enrollment.STATUS_ENROLLED))
        if len(rows) >= BATCH_SIZE:
            Enrollment.objects.bulk_create(rows, ignore_conflicts=True,
                                           batch_size=BATCH_SIZE)
            rows = []
    if rows:
        Enrollment.objects.bulk_create(rows, ignore_conflicts=True,
                                       batch_size=BATCH_SIZE)
    return Enrollment.objects.filter(
        section__code__startswith=SECTION_PREFIX).count()
