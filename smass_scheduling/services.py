"""排课产品服务：创建批次、求解、发布门禁。

复用 R11 求解器（``solver.solve`` / ``solver.verify_run``），不重复实现算法；
产品端只负责状态机与权限边界。
"""
from __future__ import annotations

from django.utils import timezone

from smass_scheduling import solver
from smass_scheduling.models import (
    RUN_DRAFT,
    RUN_PUBLISHED,
    RUN_SOLVED,
    ScheduleRun,
)


class ScheduleError(Exception):
    """排课域错误。"""


def create_run(term, *, actor='', algorithm='deterministic-constructive-v1'):
    if term is None:
        raise ScheduleError('请选择学期')
    existing = ScheduleRun.objects.filter(
        term=term, status__in=(RUN_DRAFT, RUN_SOLVED)).first()
    if existing is not None:
        raise ScheduleError('该学期已有未发布的排课批次（#{}）'.format(existing.pk))
    return ScheduleRun.objects.create(
        term=term, status=RUN_DRAFT, algorithm=algorithm)


def solve_run(run, *, actor=''):
    """执行求解并写回条目/冲突/状态。"""
    if run.status == RUN_PUBLISHED:
        raise ScheduleError('已发布的批次不能重新求解')
    result = solver.solve(run)
    run.refresh_from_db()
    return run, result


def publish_run(run, *, actor=''):
    """发布门禁：必须 solved、无硬冲突、独立复核通过。"""
    if run.status != RUN_SOLVED:
        raise ScheduleError(
            '只有已求解的批次可以发布（当前：{}）'.format(run.status))
    if run.hard_conflicts:
        raise ScheduleError(
            '存在 {} 个硬冲突，不能发布'.format(run.hard_conflicts))
    problems = solver.verify_run(run)
    if problems:
        kind = problems[0].get('kind', 'unknown')
        raise ScheduleError('发布前复核未通过：{}'.format(kind))
    run.status = RUN_PUBLISHED
    run.published_at = timezone.now()
    run.save(update_fields=['status', 'published_at'])
    try:
        from r21_account.models import Account
        from smass_academic.models import TeachingAssignment
        from smass_workflow.services import notify_account

        teacher_ids = list(
            TeachingAssignment.objects
            .filter(section__term=run.term, revoked_at__isnull=True)
            .values_list('account_id', flat=True).distinct())
        for account in Account.objects.filter(pk__in=teacher_ids):
            notify_account(
                account, '课表已发布',
                body='{} 的课表已发布，可在教师工作台查看'.format(run.term),
                event_key='schedule:{}:{}'.format(run.pk, account.pk))
    except Exception:  # noqa: BLE001 - 通知失败不影响发布
        pass
    return run
