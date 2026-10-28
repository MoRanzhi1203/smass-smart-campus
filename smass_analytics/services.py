"""R7 服务层：指标注册、计算、报表与导出。

安全原则（对应计划 §1.6 与 R7-05）：
- 所有计算**先**应用 scope 过滤，再聚合；不会"先算总数再判断权限"；
- 小样本抑制：可见群体小于阈值时返回 0 并记 ``DataQualityIssue``，
  防止通过聚合反推未授权个体（阈值默认 5，可在指标定义中覆盖）。
"""
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from smass_analytics.models import (
    DataQualityIssue,
    MetricDefinition,
    MetricSnapshot,
    ReportDefinition,
    ReportRun,
    hash_payload,
)


class AnalyticsError(Exception):
    """分析域错误基类。"""


class MetricNotEnabled(AnalyticsError):
    """指标未校验/未启用。"""


class AccessError(AnalyticsError):
    """越权。"""


#: 默认最小汇总群体（防止小样本反推）
DEFAULT_MIN_GROUP = 5


# ---------------------------------------------------------------------------
# R7-01 注册与校验
# ---------------------------------------------------------------------------
def register_metric(code, name, data_source, *, description='', definition=None,
                    permission_roles=None, owner='', period='realtime',
                    precision=0, enabled=False):
    if data_source not in dict(MetricDefinition.DATA_SOURCES):
        raise AnalyticsError('未知数据源: {}'.format(data_source))
    if MetricDefinition.objects.filter(code=code).exists():
        raise AnalyticsError('指标 {} 已存在'.format(code))

    return MetricDefinition.objects.create(
        code=code, name=name, data_source=data_source, description=description,
        definition=definition or {}, permission_roles=permission_roles or [],
        owner=owner, period=period, precision=precision,
        is_enabled=enabled,  # 默认不启用
    )


def validate_metric(metric):
    """校验：必须能在代码中找到对应计算函数，且数据源匹配。"""
    if metric.code not in COMPUTERS:
        raise AnalyticsError('指标 {} 没有计算实现'.format(metric.code))

    expected_source = COMPUTERS[metric.code]['data_source']
    if metric.data_source != expected_source:
        raise AnalyticsError(
            '指标数据源声明 {} 与实现 {} 不一致'.format(
                metric.data_source, expected_source
            )
        )

    metric.validated_at = timezone.now()
    metric.is_enabled = True
    metric.save(update_fields=['validated_at', 'is_enabled'])
    return metric


def enabled_metrics(account=None):
    roles = _roles(account)
    queryset = MetricDefinition.objects.filter(is_enabled=True).order_by('code')
    return [
        metric for metric in queryset
        if not metric.permission_roles or set(metric.permission_roles) & roles
    ]


# ---------------------------------------------------------------------------
# R7-02 确定性指标
# ---------------------------------------------------------------------------
def _roles(account):
    if account is None or not getattr(account, 'is_authenticated', False):
        return set()
    if not getattr(account, 'is_active', False):
        return set()
    return set(account.active_roles())


def _count_org_units(account, **kwargs):
    from smass_organization.services import scoped_units

    return scoped_units(account).count()


def _count_students(account, **kwargs):
    from smass_organization.services import scoped_students

    return scoped_students(account).count()


def _count_sections(account, **kwargs):
    from smass_academic.models import TeachingSection
    from smass_academic.services import teacher_sections
    from r21_account.models import RoleCode

    roles = _roles(account)
    if RoleCode.SYSTEM_ADMIN in roles or 'college_admin' in roles:
        return TeachingSection.objects.count()
    if RoleCode.TEACHER in roles:
        return teacher_sections(account).count()
    if RoleCode.STUDENT in roles:
        from smass_academic.services import student_sections

        return student_sections(account).count()
    return 0


def _count_workflow_by_status(account, **kwargs):
    from smass_workflow.models import WorkflowInstance

    status = kwargs.get('status')
    queryset = WorkflowInstance.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    return queryset.count()


COMPUTERS = {
    'org_units_total': {
        'data_source': 'organization',
        'compute': _count_org_units,
        'label': '组织单元总数',
    },
    'students_scoped': {
        'data_source': 'student',
        'compute': _count_students,
        'label': '可见学生档案数',
    },
    'sections_visible': {
        'data_source': 'academic',
        'compute': _count_sections,
        'label': '可见教学班数',
    },
    'workflow_instances': {
        'data_source': 'workflow',
        'compute': _count_workflow_by_status,
        'label': '工作流实例数',
    },
}


def compute_metric(metric, account, *, params=None, persist=True):
    """计算指标并（可选）写快照。返回 ``(value, meta)``。"""
    if not metric.is_enabled:
        raise MetricNotEnabled('指标 {} 未校验/未启用'.format(metric.code))

    roles = _roles(account)
    if metric.permission_roles and not (set(metric.permission_roles) & roles):
        raise AccessError('无权查看指标 {}'.format(metric.code))

    spec = COMPUTERS.get(metric.code)
    if spec is None:
        raise AnalyticsError('指标 {} 没有计算实现'.format(metric.code))

    params = params or {}
    raw = spec['compute'](account, **params)

    # 小样本抑制：仅对"按人计数"的指标生效。
    # 注意：
    # 1) 教学班数等非个人维度不抑制（不会反推个体）；
    # 2) 全局管理员本来就能看全部，不抑制（否则运维看不到真实总数）。
    min_group = int(metric.definition.get('min_group', DEFAULT_MIN_GROUP))
    suppressed = False
    is_global_admin = 'system_admin' in roles
    if (metric.code == 'students_scoped'
            and not is_global_admin
            and 0 < raw < min_group):
        raw_before = raw
        raw = 0
        suppressed = True
        DataQualityIssue.objects.create(
            code='SMALL_SAMPLE', metric=metric, severity='warning',
            message='可见群体 {} 小于阈值 {}，已抑制为 0'.format(raw_before, min_group),
        )

    scope_hash = hash_payload({
        'account': getattr(account, 'login_name', '') if account else '',
        'roles': sorted(roles),
        'params': params,
        'metric': metric.code,
        'min_group': min_group,
    })
    query_hash = hash_payload({'metric': metric.code, 'version': metric.version})

    value = Decimal(str(raw))
    meta = {
        'metric': metric.code,
        'name': metric.name,
        'value': float(value),
        'scope_hash': scope_hash,
        'query_hash': query_hash,
        'suppressed': suppressed,
    }

    if persist:
        MetricSnapshot.objects.create(
            metric=metric, metric_version=metric.version, value=value,
            scope_hash=scope_hash, query_hash=query_hash,
            computed_by=getattr(account, 'login_name', '')[:32],
        )

    return value, meta


# ---------------------------------------------------------------------------
# R7-03 报表
# ---------------------------------------------------------------------------
def create_report(code, name, *, metric_codes=None, permission_roles=None):
    if ReportDefinition.objects.filter(code=code).exists():
        raise AnalyticsError('报表 {} 已存在'.format(code))

    report = ReportDefinition.objects.create(
        code=code, name=name, permission_roles=permission_roles or [],
        is_enabled=False,
    )
    for metric_code in metric_codes or []:
        metric = MetricDefinition.objects.filter(code=metric_code).first()
        if metric:
            report.metrics.add(metric)
    return report


def run_report(report, account, *, persist=True):
    """运行报表：逐指标计算结果，记录 query_hash 与 scope_hash。"""
    roles = _roles(account)
    if not report.is_enabled:
        raise AnalyticsError('报表 {} 未启用'.format(report.code))
    if report.permission_roles and not (set(report.permission_roles) & roles):
        raise AccessError('无权运行报表 {}'.format(report.code))

    rows = []
    for metric in report.metrics.filter(is_enabled=True).order_by('code'):
        try:
            value, meta = compute_metric(metric, account, persist=persist)
            rows.append(meta)
        except AccessError:
            continue

    query_hash = hash_payload({'report': report.code, 'rows': [
        {'metric': row['metric'], 'query_hash': row['query_hash']} for row in rows
    ]})
    scope_hash = hash_payload({'account': getattr(account, 'login_name', ''),
                               'roles': sorted(roles)})

    if persist:
        ReportRun.objects.create(
            report=report, status='ok', row_count=len(rows),
            query_hash=query_hash, scope_hash=scope_hash, rows=rows,
            ran_by=getattr(account, 'login_name', '')[:32],
        )

    return rows, {'query_hash': query_hash, 'scope_hash': scope_hash}


def latest_snapshot(metric):
    return metric.snapshots.order_by('-computed_at').first()


# ---------------------------------------------------------------------------
# R7-04 受限导出
# ---------------------------------------------------------------------------
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _sanitize(value):
    text = '' if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        text = "'" + text
    return text.replace('\r', ' ').replace('\n', ' ')


def export_report_csv(report, account):
    """导出报表（CSV），权限与网页一致；含 query_hash 便于对账。"""
    rows, meta = run_report(report, account, persist=True)

    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['metric', 'name', 'value', 'query_hash', 'scope_hash'])

    for row in rows:
        writer.writerow([
            _sanitize(row['metric']), _sanitize(row['name']),
            row['value'], row['query_hash'], row['scope_hash'],
        ])

    return buffer.getvalue(), meta
