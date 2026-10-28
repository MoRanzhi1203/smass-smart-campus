"""H1：批次级审计与回滚可追溯。

设计要点：
1. 每次回填/回滚生成唯一 ``batch_id``；
2. 回滚**追加**一条 ``operation='rollback'`` 事件，并用 ``source_batch_id``
   指向被回滚的回填批次——**不删除**历史事件；
3. 事件是 append-only：重复回滚会产生多个 rollback 批次，各自指向同一源批次；
4. 业务与审计的崩溃窗口：审计写在业务事务**之后**（同一连接），
   若进程在两者之间崩溃，可通过"存在业务数据但无对应批次事件"对账发现
   （见 ``find_unbatched_backfill``）。

注意：本模块只在加载 ``r22_account`` 的隔离配置下可用；
``r21_account`` 的测试环境不加载它，因此不构成对 R2.1 的依赖。
"""
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from r22_account import audit
from r22_account.models import (
    ACTOR_KIND_SYSTEM,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    AccountAuditEvent,
)

OPERATION_BACKFILL = 'backfill'
OPERATION_ROLLBACK = 'rollback'

ACTION_BATCH = 'batch_executed'


def new_batch_id():
    return str(uuid.uuid4())


def record_batch(operation, outcome, *, batch_id, source_batch_id='', counts=None,
                 actor='batch_audit', detail=''):
    """写一条批次事件（append-only）。"""
    return audit.record(
        ACTION_BATCH,
        outcome=outcome,
        actor=None,
        actor_kind=ACTOR_KIND_SYSTEM,
        target=operation,
        target_id=batch_id,
        context={'detail': detail} if detail else None,
        batch_id=batch_id,
        operation=operation,
        source_batch_id=source_batch_id,
        counts=counts or {},
    )


def _backfill_command(**options):
    from django.core.management import call_command
    from io import StringIO

    out = StringIO()
    call_command('backfill_accounts_r21', *(), stdout=out, **options)
    return out.getvalue()


def run_backfill(dry_run=False, since=0):
    """执行一次回填，并记录批次事件。返回 (batch_id, output, outcome)。"""
    batch_id = new_batch_id()
    before = _snapshot()

    try:
        output = _backfill_command(dry_run=dry_run, since=since)
    except Exception as exc:  # noqa: BLE001
        record_batch(
            OPERATION_BACKFILL, OUTCOME_ERROR, batch_id=batch_id,
            counts=dict(_snapshot(), error=type(exc).__name__),
            detail='backfill failed',
        )
        raise

    after = _snapshot()
    counts = _diff(before, after)
    counts['dry_run'] = bool(dry_run)
    counts['since'] = since

    record_batch(OPERATION_BACKFILL, OUTCOME_SUCCESS, batch_id=batch_id, counts=counts)
    return batch_id, output, OUTCOME_SUCCESS


def run_rollback(dry_run=False):
    """执行一次回滚，并追加 rollback 批次事件（引用最近一次回填批次）。"""
    batch_id = new_batch_id()
    source_batch_id = latest_backfill_batch_id() or ''
    before = _snapshot()

    try:
        output = _backfill_command(dry_run=dry_run, rollback=True)
    except Exception as exc:  # noqa: BLE001
        record_batch(
            OPERATION_ROLLBACK, OUTCOME_ERROR, batch_id=batch_id,
            source_batch_id=source_batch_id,
            counts=dict(_snapshot(), error=type(exc).__name__),
            detail='rollback failed',
        )
        raise

    after = _snapshot()
    counts = _diff(before, after)
    counts['dry_run'] = bool(dry_run)

    record_batch(
        OPERATION_ROLLBACK, OUTCOME_SUCCESS, batch_id=batch_id,
        source_batch_id=source_batch_id, counts=counts,
        detail='rolled back batch {}'.format(source_batch_id) if source_batch_id else 'nothing to roll back',
    )
    return batch_id, output, OUTCOME_SUCCESS


def latest_backfill_batch_id():
    event = (
        AccountAuditEvent.objects.filter(
            action=ACTION_BATCH, operation=OPERATION_BACKFILL, outcome=OUTCOME_SUCCESS
        )
        .order_by('-created_at')
        .first()
    )
    return event.batch_id if event else ''


def latest_rollback_batch_id():
    event = (
        AccountAuditEvent.objects.filter(
            action=ACTION_BATCH, operation=OPERATION_ROLLBACK, outcome=OUTCOME_SUCCESS
        )
        .order_by('-created_at')
        .first()
    )
    return event.batch_id if event else ''


def batch_events(batch_id):
    return AccountAuditEvent.objects.filter(batch_id=batch_id).order_by('created_at')


def batch_chain():
    """返回 [(operation, batch_id, source_batch_id, outcome)]，用于追溯链展示。"""
    return list(
        AccountAuditEvent.objects.filter(action=ACTION_BATCH)
        .order_by('created_at')
        .values_list('operation', 'batch_id', 'source_batch_id', 'outcome')
    )


def find_unbatched_backfill(window_minutes=10):
    """对账：若存在映射但近期没有任何回填批次事件，提示崩溃窗口。

    返回 True 表示可能存在"业务已提交但审计未写"的情况。
    """
    from r21_account.models import LegacyAccountLink

    has_links = LegacyAccountLink.objects.exists()
    if not has_links:
        return False

    since = timezone.now() - timedelta(minutes=window_minutes)
    return not AccountAuditEvent.objects.filter(
        action=ACTION_BATCH, operation=OPERATION_BACKFILL, created_at__gte=since
    ).exists()


def _snapshot():
    from r21_account.models import (
        Account, AccountRole, LegacyAccountLink, StudentProfile, TeacherProfile,
    )

    return {
        'accounts': Account.objects.count(),
        'links': LegacyAccountLink.objects.count(),
        'roles': AccountRole.objects.filter(revoked_at__isnull=True).count(),
        'student_profiles': StudentProfile.objects.count(),
        'teacher_profiles': TeacherProfile.objects.count(),
    }


def _diff(before, after):
    return {key: after.get(key, 0) - before.get(key, 0) for key in set(before) | set(after)}
