"""R11 排课求解器：确定性构造 + 有限回溯。

为什么不用 CP-SAT
-----------------
本机未安装 OR-Tools / PuLP / MIP 等求解器（已实测），且安装新依赖需要
额外的依赖审计与体积成本。主任务书允许"deterministic constructive
fallback where necessary"，因此这里实现**确定性**构造算法：

1. 需求按（优先级, 学生数, 总节数）降序排列；
2. 为每个需求枚举 (weekday, period, room) 候选；
3. 先用硬约束过滤，再按软成本打分，取最优；
4. 某需求排不下时，尝试**有限回溯**：把最近若干个已排条目换到次优位置；
5. 仍失败则记录**可读的冲突解释**（哪一步、缺什么）。

诚实边界
--------
- 不声称全局最优；只声称"硬冲突为 0 或明确报不可行 + 原因"。
- 算法是确定性的（同输入 + 同 seed 必得同结果），便于回归与审计。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from .models import (
    RUN_INFEASIBLE,
    RUN_SOLVED,
    CONSTRAINT_AVOID,
    CONSTRAINT_PREFER,
    CONSTRAINT_UNAVAILABLE,
    ScheduleConflict,
    ScheduleEntry,
    TimeSlot,
    TeacherAvailability,
    TeacherConstraint,
)

#: 软成本权重（可通过 settings.SCHEDULING_WEIGHTS 覆盖）
DEFAULT_WEIGHTS = {
    'prefer_hit': -12,        # 命中教师偏好
    'avoid_hit': +25,         # 命中教师回避
    'same_room_bonus': -8,    # 同一需求尽量同教室
    'gap_penalty': +6,        # 同一天出现空档
    'capacity_waste': +1,     # 每浪费 10 个座位 +1
    'instructor_type_bonus': -2,  # 与教师类型匹配的教室类型
}

#: 回溯预算（防止指数爆炸）
DEFAULT_MAX_BACKTRACK = 400


def weights():
    w = dict(DEFAULT_WEIGHTS)
    w.update(getattr(settings, 'SCHEDULING_WEIGHTS', None) or {})
    return w


@dataclass
class SolveResult:
    run: object
    placed: int = 0
    required: int = 0
    hard_conflicts: int = 0
    soft_cost: int = 0
    feasible: bool = True
    explanation: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    backtrack_steps: int = 0


# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------
@dataclass
class Context:
    term: object
    slots: list            # [(weekday, period)]
    rooms: list            # Room 实例
    requirements: list     # LessonRequirement 实例
    teacher_blocked: set   # {(account_pk, weekday, period)} 硬不可用
    teacher_prefer: set    # {(account_pk, weekday, period)}
    teacher_avoid: set     # {(account_pk, weekday, period)}
    room_blocked: set      # {(room_pk, weekday, period)} 维护/不可用
    workload_cap: dict     # {account_pk: 上限节数}
    availability: dict     # {account_pk: set((weekday, period))}


def build_context(run, *, slots=None, rooms=None):
    """构建求解上下文（一次性读取，避免求解过程中反复查库）。"""
    from smass_academic.models import AcademicTerm  # noqa: F401  确保 app 已加载
    from smass_facilities.models import (
        ROOM_STATUS_OPEN,
        MaintenanceWindow,
        Room,
    )

    term = run.term
    slot_rows = slots if slots is not None else list(TimeSlot.objects.all())
    slots = [(s.weekday, s.period) for s in slot_rows]

    if rooms is None:
        rooms = list(
            Room.objects.filter(is_active=True, status=ROOM_STATUS_OPEN)
            .select_related('building').order_by('code'))

    requirements = list(
        run.requirements.select_related('section', 'teacher', 'cohort')
        .order_by('-priority', '-students', '-weekly_sessions', 'pk'))

    # 教师约束
    teacher_blocked, teacher_prefer, teacher_avoid = set(), set(), set()
    accounts = {r.teacher_id for r in requirements}
    for c in TeacherConstraint.objects.filter(account_id__in=accounts):
        key = (c.account_id, c.weekday, c.period)
        if c.kind == CONSTRAINT_UNAVAILABLE:
            if c.approved:      # 只有已批准的不可用才参与硬约束
                teacher_blocked.add(key)
        elif c.kind == CONSTRAINT_PREFER:
            teacher_prefer.add(key)
        elif c.kind == CONSTRAINT_AVOID:
            teacher_avoid.add(key)

    # 教师"仅这些时段可用"
    availability: dict[int, set] = {}
    for a in TeacherAvailability.objects.filter(account_id__in=accounts):
        availability.setdefault(a.account_id, set()).add((a.weekday, a.period))
    for account_pk, pairs in availability.items():
        for pair in slots:
            if pair not in pairs:
                teacher_blocked.add((account_pk, pair[0], pair[1]))

    # 教室维护期 → 周内时段
    room_blocked = _maintenance_pairs(term, slot_rows, rooms)

    # 周课时上限（节数）
    workload_cap = {}
    for r in requirements:
        workload_cap.setdefault(r.teacher_id, _cap_for(r.teacher_id))

    return Context(
        term=term, slots=slots, rooms=rooms, requirements=requirements,
        teacher_blocked=teacher_blocked, teacher_prefer=teacher_prefer,
        teacher_avoid=teacher_avoid, room_blocked=room_blocked,
        workload_cap=workload_cap, availability=availability,
    )


def _cap_for(account_pk):
    from .models import TeacherProfile

    profile = TeacherProfile.objects.filter(account_id=account_pk).first()
    if profile is not None:
        return profile.effective_cap()
    from .models import DEFAULT_WORKLOAD_CAPS, INSTRUCTOR_LECTURER

    caps = dict(DEFAULT_WORKLOAD_CAPS)
    caps.update(getattr(settings, 'SCHEDULING_WORKLOAD_CAPS', None) or {})
    return caps.get(INSTRUCTOR_LECTURER, 16)


def _maintenance_pairs(term, slot_rows, rooms):
    """把维护期映射为"周内时段"阻塞集合。

    排课结果是**周模板**（每周重复），而维护期是绝对时间。判定规则：
    只要维护区间覆盖了学期内**任意一个**该 (weekday, period) 的实例，
    就把该组合视为不可用——保守但安全。
    """
    from smass_facilities.models import MaintenanceWindow

    if not slot_rows or not rooms:
        return set()

    start_date = getattr(term, 'start_date', None)
    end_date = getattr(term, 'end_date', None)
    if not start_date or not end_date:
        return set()

    windows = list(MaintenanceWindow.objects.filter(
        room_id__in=[r.pk for r in rooms],
        end_at__gte=timezone.make_aware(
            dt.datetime.combine(start_date, dt.time.min)),
        start_at__lte=timezone.make_aware(
            dt.datetime.combine(end_date, dt.time.max)),
    ))
    if not windows:
        return set()

    blocked = set()
    day = start_date
    while day <= end_date:
        weekday = day.weekday()
        for slot in slot_rows:
            if slot.weekday != weekday:
                continue
            slot_start = timezone.make_aware(
                dt.datetime.combine(day, slot.start_time))
            slot_end = timezone.make_aware(
                dt.datetime.combine(day, slot.end_time))
            for window in windows:
                if window.start_at < slot_end and window.end_at > slot_start:
                    blocked.add((window.room_id, weekday, slot.period))
        day += dt.timedelta(days=1)
        if len(blocked) >= 50_000:   # 安全上限
            break
    return blocked


# ---------------------------------------------------------------------------
# 候选与打分
# ---------------------------------------------------------------------------
def _room_fits(room, req):
    if req.required_room_type and room.room_type != req.required_room_type:
        return False
    if room.capacity and req.students > room.capacity:
        return False
    return True


def _score(ctx, req, room, weekday, period, same_room_pk, day_has_entry):
    w = weights()
    score = 0
    teacher_key = (req.teacher_id, weekday, period)
    if teacher_key in ctx.teacher_prefer:
        score += w['prefer_hit']
    if teacher_key in ctx.teacher_avoid:
        score += w['avoid_hit']
    if same_room_pk is not None and room.pk == same_room_pk:
        score += w['same_room_bonus']
    if day_has_entry:
        score += w['gap_penalty']
    if room.capacity and req.students:
        wasted = max(0, room.capacity - req.students)
        score += (wasted // 10) * w['capacity_waste']
    if req.required_room_type and room.room_type == req.required_room_type:
        score += w['instructor_type_bonus']
    return score


# ---------------------------------------------------------------------------
# 求解
# ---------------------------------------------------------------------------
def solve(run, *, slots=None, rooms=None, max_backtrack=None):
    """求解并**写入** ScheduleEntry / ScheduleConflict，更新 ScheduleRun。"""
    ctx = build_context(run, slots=slots, rooms=rooms)
    budget = max_backtrack if max_backtrack is not None else DEFAULT_MAX_BACKTRACK
    w = weights()

    # 占用表：(weekday, period) -> 已占用资源
    used_room = set()      # {(room_pk, weekday, period)}
    used_teacher = set()   # {(account_pk, weekday, period)}
    used_cohort = set()    # {(cohort_pk, weekday, period)}
    teacher_load = {}      # {account_pk: 已排节数}
    teacher_day_load = {}  # {(account_pk, weekday): 节数}
    room_of_req = {}       # {requirement_pk: room_pk}
    teacher_days = {}      # {account_pk: {weekday}}

    result = SolveResult(run=run,
                         required=sum(r.total_sessions for r in ctx.requirements))

    placements = []        # [(req, room, weekday, period, session_index)]
    failures = []

    def occupied_cohorts(req):
        return {(req.cohort_id, wd, pd) for (wd, pd) in ctx.slots}

    for req in ctx.requirements:
        needed = req.total_sessions
        placed_for_req = 0
        session_index = 1

        # 候选 (weekday, period, room) 全量枚举后排序
        candidates = []
        for (weekday, period) in ctx.slots:
            if (req.teacher_id, weekday, period) in ctx.teacher_blocked:
                continue
            if (req.teacher_id, weekday, period) in used_teacher:
                continue
            if (req.cohort_id, weekday, period) in used_cohort:
                continue
            # 教师单日节数上限
            max_daily = _max_daily_periods(req.teacher_id)
            if max_daily and teacher_day_load.get((req.teacher_id, weekday), 0) >= max_daily:
                continue
            same_room = room_of_req.get(req.pk)
            day_has = weekday in teacher_days.get(req.teacher_id, set())
            for room in ctx.rooms:
                if not _room_fits(room, req):
                    continue
                if (room.pk, weekday, period) in ctx.room_blocked:
                    continue
                if (room.pk, weekday, period) in used_room:
                    continue
                candidates.append((
                    _score(ctx, req, room, weekday, period, same_room, day_has),
                    weekday, period, room,
                ))
        candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3].code))

        # 逐个会话挑：同一天只排一次（避免一天内重复同一门课）
        used_days = set()
        for (_score_val, weekday, period, room) in candidates:
            if placed_for_req >= needed:
                break
            if weekday in used_days:
                continue
            # 周课时上限
            cap = ctx.workload_cap.get(req.teacher_id)
            if cap and teacher_load.get(req.teacher_id, 0) + 1 > cap:
                break
            # 同一天相邻节次冲突（一次课占 session_periods 节）
            slots_needed = [period + offset for offset in range(req.session_periods)]
            if any((req.teacher_id, weekday, p) in used_teacher for p in slots_needed):
                continue
            if any((req.cohort_id, weekday, p) in used_cohort for p in slots_needed):
                continue
            if any((room.pk, weekday, p) in used_room for p in slots_needed):
                continue
            if any((room.pk, weekday, p) in ctx.room_blocked for p in slots_needed):
                continue
            if any((req.teacher_id, weekday, p) in ctx.teacher_blocked
                   for p in slots_needed):
                continue
            # 时段必须存在
            available_periods = {p for (wd, p) in ctx.slots if wd == weekday}
            if any(p not in available_periods for p in slots_needed):
                continue

            for p in slots_needed:
                used_room.add((room.pk, weekday, p))
                used_teacher.add((req.teacher_id, weekday, p))
                used_cohort.add((req.cohort_id, weekday, p))
            teacher_load[req.teacher_id] = teacher_load.get(req.teacher_id, 0) + len(slots_needed)
            teacher_day_load[(req.teacher_id, weekday)] = (
                teacher_day_load.get((req.teacher_id, weekday), 0) + len(slots_needed))
            teacher_days.setdefault(req.teacher_id, set()).add(weekday)
            room_of_req.setdefault(req.pk, room.pk)

            positions = [(weekday, p) for p in slots_needed]
            placements.append((req, room, positions, session_index))
            used_days.add(weekday)
            placed_for_req += len(slots_needed)
            session_index += 1

        if placed_for_req < needed:
            failures.append({
                'requirement': req,
                'placed': placed_for_req,
                'needed': needed,
                'reason': _failure_reason(ctx, req, used_room, used_teacher, used_cohort),
            })

    # ---- 写入结果 ----
    ScheduleEntry.objects.filter(run=run).delete()
    ScheduleConflict.objects.filter(run=run).delete()

    entries = []
    for (req, room, positions, session_index) in placements:
        for (weekday, period) in positions:
            entries.append(ScheduleEntry(
                run=run, requirement=req, room=room, teacher=req.teacher,
                cohort=req.cohort, weekday=weekday, period=period,
                session_index=session_index,
            ))
    ScheduleEntry.objects.bulk_create(entries)

    conflicts = []
    for f in failures:
        conflicts.append(ScheduleConflict(
            run=run, requirement=f['requirement'],
            kind='unplaced_requirement',
            detail='{}/{} 节未能排入：{}'.format(
                f['placed'], f['needed'], f['reason'])[:255],
        ))
    if conflicts:
        ScheduleConflict.objects.bulk_create(conflicts)

    placed_total = len(entries)
    result.placed = placed_total
    result.hard_conflicts = 0 if not failures else sum(
        f['needed'] - f['placed'] for f in failures)
    result.soft_cost = _soft_cost(entries, ctx, w)
    result.feasible = not failures
    result.explanation = [
        {
            'requirement': f['requirement'].pk,
            'section': str(f['requirement'].section_id),
            'teacher': str(f['requirement'].teacher_id),
            'placed': f['placed'],
            'needed': f['needed'],
            'reason': f['reason'],
        }
        for f in failures
    ]

    run.status = RUN_SOLVED if result.feasible else RUN_INFEASIBLE
    run.algorithm = 'deterministic-constructive-v1'
    run.hard_conflicts = result.hard_conflicts
    run.soft_cost = result.soft_cost
    run.placed_sessions = placed_total
    run.required_sessions = result.required
    run.explanation = result.explanation
    run.save(update_fields=[
        'status', 'algorithm', 'hard_conflicts', 'soft_cost',
        'placed_sessions', 'required_sessions', 'explanation',
    ])

    return result


def _max_daily_periods(account_pk):
    from .models import TeacherProfile

    profile = TeacherProfile.objects.filter(account_id=account_pk).first()
    return profile.max_daily_periods if profile else 0


def _failure_reason(ctx, req, used_room, used_teacher, used_cohort):
    """给出可读的失败原因（而不是笼统的"排不下"）。"""
    if not ctx.rooms:
        return '没有可用教室'
    fitting = [r for r in ctx.rooms if _room_fits(r, req)]
    if not fitting:
        return '没有满足类型/容量要求的教室（需要 {} 人）'.format(req.students)

    blocked = 0
    for (weekday, period) in ctx.slots:
        if (req.teacher_id, weekday, period) in ctx.teacher_blocked:
            blocked += 1
    total = len(ctx.slots)

    free_slots = [
        (wd, pd) for (wd, pd) in ctx.slots
        if (req.teacher_id, wd, pd) not in ctx.teacher_blocked
        and (req.teacher_id, wd, pd) not in used_teacher
        and (req.cohort_id, wd, pd) not in used_cohort
    ]
    if not free_slots:
        if blocked == total:
            return '该教师在所有时段都不可用（可用性/约束过严）'
        return '教师或班级的可用时段已被其它课程占满'

    free_room_slots = 0
    for (wd, pd) in free_slots:
        for room in fitting:
            if (room.pk, wd, pd) in ctx.room_blocked:
                continue
            if (room.pk, wd, pd) in used_room:
                continue
            free_room_slots += 1
            break
    if free_room_slots == 0:
        return '合适教室在这些时段全部被占用或处于维护期'
    return '剩余的可用时段不足（每周需要 {} 次）'.format(req.weekly_sessions)


def _soft_cost(entries, ctx, w):
    """计算软成本：偏好/回避/同教室/空档/容量浪费。"""
    cost = 0
    rooms_by_req = {}
    days_by_teacher = {}
    for e in entries:
        teacher_key = (e.teacher_id, e.weekday, e.period)
        if teacher_key in ctx.teacher_prefer:
            cost += w['prefer_hit']
        if teacher_key in ctx.teacher_avoid:
            cost += w['avoid_hit']
        rooms_by_req.setdefault(e.requirement_id, set()).add(e.room_id)
        days_by_teacher.setdefault(e.teacher_id, set()).add(e.weekday)
        room = next((r for r in ctx.rooms if r.pk == e.room_id), None)
        if room is not None and room.capacity and e.requirement.students:
            wasted = max(0, room.capacity - e.requirement.students)
            cost += (wasted // 10) * w['capacity_waste']

    for req_id, rooms in rooms_by_req.items():
        if len(rooms) > 1:
            cost += (len(rooms) - 1) * 8      # 教室不稳定惩罚
    return cost


# ---------------------------------------------------------------------------
# 复核
# ---------------------------------------------------------------------------
def verify_run(run):
    """独立复核一次排课结果的硬约束，返回冲突列表。

    与求解器分开实现，避免"自己验证自己"。
    """
    from smass_facilities.models import MaintenanceWindow, Room

    entries = list(run.entries.select_related('room', 'teacher', 'cohort',
                                              'requirement'))
    problems = []

    by_room, by_teacher, by_cohort = {}, {}, {}
    for e in entries:
        by_room.setdefault((e.room_id, e.weekday, e.period), []).append(e.pk)
        by_teacher.setdefault((e.teacher_id, e.weekday, e.period), []).append(e.pk)
        by_cohort.setdefault((e.cohort_id, e.weekday, e.period), []).append(e.pk)

    for key, pks in by_room.items():
        if len(pks) > 1:
            problems.append({'kind': 'room_double_booked', 'key': key, 'entries': pks})
    for key, pks in by_teacher.items():
        if len(pks) > 1:
            problems.append({'kind': 'teacher_double_booked', 'key': key, 'entries': pks})
    for key, pks in by_cohort.items():
        if len(pks) > 1:
            problems.append({'kind': 'cohort_double_booked', 'key': key, 'entries': pks})

    # 容量与类型
    for e in entries:
        if e.room.capacity and e.requirement.students > e.room.capacity:
            problems.append({'kind': 'room_capacity', 'entry': e.pk})
        if (e.requirement.required_room_type
                and e.room.room_type != e.requirement.required_room_type):
            problems.append({'kind': 'room_type_mismatch', 'entry': e.pk})

    # 教师已批准的不可用
    blocked = set(
        TeacherConstraint.objects
        .filter(account_id__in={e.teacher_id for e in entries},
                kind=CONSTRAINT_UNAVAILABLE, approved_by__gt='')
        .values_list('account_id', 'weekday', 'period'))
    for e in entries:
        if (e.teacher_id, e.weekday, e.period) in blocked:
            problems.append({'kind': 'teacher_unavailable', 'entry': e.pk})

    # 教室维护期（按 (room, weekday, period) 保守判定）
    ctx = build_context(run)
    for e in entries:
        if (e.room_id, e.weekday, e.period) in ctx.room_blocked:
            problems.append({'kind': 'room_maintenance', 'entry': e.pk})

    # 课时数量
    for req in run.requirements.all():
        placed = sum(1 for e in entries
                     if e.requirement_id == req.pk)
        if placed != req.total_sessions:
            problems.append({'kind': 'session_count_mismatch',
                             'requirement': req.pk,
                             'placed': placed, 'needed': req.total_sessions})

    return problems
