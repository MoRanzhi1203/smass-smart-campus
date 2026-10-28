"""R9 服务层：指标记录与聚合、健康检查、告警评估。

安全：所有写入与日志都不含 PII；路径只记录模板化后的字符串。
"""
import time
from datetime import timedelta

from django.db import connection, connections
from django.utils import timezone

from smass_operations.models import (
    AlertEvent,
    AlertRule,
    ReadinessProbe,
    RequestMetric,
)


class OpsError(Exception):
    """运维域错误。"""


# ---------------------------------------------------------------------------
# R9-01 指标
# ---------------------------------------------------------------------------
def normalize_route(path):
    """把路径里的数字/ID 段替换为占位符，避免记录具体对象标识。"""
    parts = []
    for segment in (path or '').split('/'):
        if not segment:
            parts.append('')
        elif segment.isdigit():
            parts.append('{id}')
        elif len(segment) >= 16:
            parts.append('{token}')
        else:
            parts.append(segment)
    return '/'.join(parts)[:200]


def record_request(request, status_code, duration_ms):
    """记录一次请求指标（失败不抛，避免影响业务）。"""
    try:
        RequestMetric.objects.create(
            method=(request.method or '')[:8],
            route=normalize_route(request.path),
            status_code=int(status_code),
            duration_ms=int(duration_ms),
        )
    except Exception:  # noqa: BLE001
        pass


def _percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return float(ordered[index])


def summary(window_seconds=300):
    """返回窗口内的延迟分位与错误率。"""
    since = timezone.now() - timedelta(seconds=window_seconds)
    rows = list(
        RequestMetric.objects.filter(created_at__gte=since)
        .values_list('status_code', 'duration_ms')
    )
    if not rows:
        return {
            'window_seconds': window_seconds,
            'requests': 0,
            'p50_ms': 0.0, 'p95_ms': 0.0, 'p99_ms': 0.0,
            'error_rate': 0.0,
        }

    durations = [row[1] for row in rows]
    errors = sum(1 for row in rows if row[0] >= 500)

    return {
        'window_seconds': window_seconds,
        'requests': len(rows),
        'p50_ms': _percentile(durations, 50),
        'p95_ms': _percentile(durations, 95),
        'p99_ms': _percentile(durations, 99),
        'error_rate': round(errors / len(rows), 4),
    }


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
def check_database():
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        ok, detail = True, 'ok'
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, type(exc).__name__
    return ok, detail, int((time.perf_counter() - started) * 1000)


def check_migrations():
    """检查是否有未应用的迁移（只读，不执行迁移）。"""
    started = time.perf_counter()
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        ok = not plan
        detail = 'ok' if ok else '{} pending'.format(len(plan))
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, type(exc).__name__
    return ok, detail, int((time.perf_counter() - started) * 1000)


def readiness(persist=True):
    """逐项检查，返回总体是否就绪。"""
    checks = []
    for name, func in (('database', check_database), ('migrations', check_migrations)):
        ok, detail, duration = func()
        checks.append({'name': name, 'ok': ok, 'detail': detail,
                       'duration_ms': duration})
        if persist:
            try:
                ReadinessProbe.objects.create(
                    name=name, ok=ok, detail=detail[:255], duration_ms=duration
                )
            except Exception:  # noqa: BLE001
                pass

    return all(item['ok'] for item in checks), checks


def close_connections():
    """测试辅助：释放连接（避免连接数堆积）。"""
    connections.close_all()


# ---------------------------------------------------------------------------
# 告警
# ---------------------------------------------------------------------------
def create_rule(code, name, metric, threshold, *, window_seconds=300,
                severity='warning', enabled=True):
    if metric not in dict(AlertRule.METRIC_CHOICES):
        raise OpsError('未知指标: {}'.format(metric))
    if AlertRule.objects.filter(code=code).exists():
        raise OpsError('规则 {} 已存在'.format(code))
    return AlertRule.objects.create(
        code=code, name=name, metric=metric, threshold=threshold,
        window_seconds=window_seconds, severity=severity, is_enabled=enabled,
    )


def _observed(rule):
    stats = summary(rule.window_seconds)
    if rule.metric == AlertRule.METRIC_ERROR_RATE:
        return stats['error_rate']
    if rule.metric == AlertRule.METRIC_LATENCY_P95:
        return stats['p95_ms']
    if rule.metric == AlertRule.METRIC_DB_ERRORS:
        since = timezone.now() - timedelta(seconds=rule.window_seconds)
        return float(
            RequestMetric.objects.filter(
                created_at__gte=since, status_code__gte=500
            ).count()
        )
    return 0.0


def evaluate_rules(persist=True):
    """评估所有启用规则，超阈值则记 AlertEvent。"""
    triggered = []
    for rule in AlertRule.objects.filter(is_enabled=True).order_by('code'):
        observed = _observed(rule)
        if observed > rule.threshold:
            triggered.append({
                'rule': rule.code, 'metric': rule.metric,
                'observed': observed, 'threshold': rule.threshold,
                'severity': rule.severity,
            })
            if persist:
                try:
                    AlertEvent.objects.create(
                        rule=rule, observed=observed, threshold=rule.threshold,
                        severity=rule.severity,
                        detail='{} > {}'.format(observed, rule.threshold),
                    )
                except Exception:  # noqa: BLE001
                    pass
    return triggered
