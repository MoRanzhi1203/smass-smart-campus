"""H4：结构化安全告警（无敏感字段）。

设计：
- 统一 logger 名 ``smass.security``，便于运维单独挂 handler/告警；
- 只输出**非敏感**结构：事件类型、身份种类、原因码、路径、计数；
- 绝不输出姓名、学号、手机号、身份证、密码、哈希、session key；
- 阈值：同一进程内按窗口计数，超过阈值才升为 WARNING，避免日志洪水。
"""
import logging
import threading
import time
from collections import defaultdict, deque

logger = logging.getLogger('smass.security')

#: 事件类型
EVENT_IDENTITY_CONFLICT = 'identity_conflict'
EVENT_DISABLED_ACCOUNT = 'disabled_account'
EVENT_ORPHAN_LINKAGE = 'orphan_linkage'
EVENT_BULK_AUTH_FAILURE = 'bulk_auth_failure'
EVENT_AUDIT_FAILURE = 'audit_failure'

#: 告警阈值（窗口秒数, 次数）
THRESHOLDS = {
    EVENT_IDENTITY_CONFLICT: (60, 1),     # 冲突必须立即可见
    EVENT_DISABLED_ACCOUNT: (60, 10),     # 停用账号尝试登录，10 次/分钟
    EVENT_ORPHAN_LINKAGE: (300, 1),
    EVENT_BULK_AUTH_FAILURE: (60, 20),
    EVENT_AUDIT_FAILURE: (60, 1),
}

#: 允许进入日志的字段（白名单，防止误传敏感信息）
SAFE_FIELDS = (
    'event', 'kind', 'reason', 'path', 'count', 'outcome', 'operation',
    'batch_id', 'role', 'mode', 'window_seconds',
)

_lock = threading.Lock()
_buckets = defaultdict(deque)


def _should_emit(event, now):
    window, limit = THRESHOLDS.get(event, (60, 1))
    bucket = _buckets[event]
    with _lock:
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        bucket.append(now)
        return len(bucket) >= limit


def emit(event, level=logging.WARNING, **fields):
    """输出一条结构化告警。未知字段直接丢弃（白名单）。"""
    now = time.time()
    if not _should_emit(event, now):
        return False

    payload = {'event': event}
    for key in SAFE_FIELDS:
        if key in fields and fields[key] is not None:
            payload[key] = fields[key]

    logger.log(level, 'security_event %s', payload)
    return True


def identity_conflict(identity, path=''):
    return emit(
        EVENT_IDENTITY_CONFLICT,
        kind=identity.kind,
        reason=identity.reason,
        path=path,
    )


def disabled_account_attempt(login_name_present=True, path=''):
    return emit(
        EVENT_DISABLED_ACCOUNT,
        kind='disabled',
        path=path,
        count=1,
        login_present=login_name_present,
    )


def orphan_linkage(count):
    return emit(EVENT_ORPHAN_LINKAGE, count=count)


def bulk_auth_failure(path=''):
    return emit(EVENT_BULK_AUTH_FAILURE, path=path, count=1)


def audit_failure(operation=''):
    return emit(EVENT_AUDIT_FAILURE, operation=operation)


def reset_counters():
    """测试辅助：清空窗口计数。"""
    with _lock:
        _buckets.clear()
