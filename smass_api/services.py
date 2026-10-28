"""R8 服务层：认证、限流、幂等、资源查询与 mock 同步。

所有对外行为都走这里，视图只做参数解析与错误包装。
"""
import hashlib
import json
import time
import uuid
from collections import defaultdict, deque

from django.db import transaction

from smass_api.models import (
    ApiCallLog,
    IdempotencyKey,
    ServiceAccount,
    SyncJob,
    hash_token,
)


class ApiError(Exception):
    """API 错误（带稳定 code）。"""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


#: 所有 scope
SCOPE_READ_UNITS = 'read:units'
SCOPE_READ_STUDENTS = 'read:students'
SCOPE_READ_SECTIONS = 'read:sections'
SCOPE_READ_WORKFLOW = 'read:workflow'
SCOPE_WRITE_STUDENTS = 'write:students'

ALL_SCOPES = (
    SCOPE_READ_UNITS, SCOPE_READ_STUDENTS, SCOPE_READ_SECTIONS,
    SCOPE_READ_WORKFLOW, SCOPE_WRITE_STUDENTS,
)


# ---------------------------------------------------------------------------
# R8-02 认证与限流
# ---------------------------------------------------------------------------
def create_service_account(name, *, scopes=None, rate_limit=60):
    """创建服务账号，返回 ``(account, raw_token)``。明文 token 只返回一次。"""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    account = ServiceAccount.objects.create(
        name=name, token_hash=hash_token(raw),
        scopes=list(scopes or []),  # 默认空
        rate_limit_per_minute=rate_limit,
    )
    return account, raw


def authenticate(request):
    """从 Authorization: Bearer <token> 解析服务账号。"""
    header = request.headers.get('Authorization', '') or ''
    if not header.lower().startswith('bearer '):
        return None
    raw = header.split(' ', 1)[1].strip()
    if not raw:
        return None
    return ServiceAccount.objects.filter(token_hash=hash_token(raw), is_active=True).first()


def require_scope(account, scope):
    if account is None:
        raise ApiError('UNAUTHENTICATED', '缺少有效的服务令牌', 401)
    if not account.has_scope(scope):
        raise ApiError('FORBIDDEN', '缺少 scope: {}'.format(scope), 403)


_buckets = defaultdict(deque)


def check_rate_limit(account):
    """简单滑动窗口限流（进程内；多进程需换共享存储）。"""
    if account is None:
        return
    limit = max(1, account.rate_limit_per_minute)
    now = time.time()
    bucket = _buckets[account.name]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        raise ApiError('RATE_LIMITED', '请求过于频繁，请稍后重试', 429)
    bucket.append(now)


def reset_rate_limits():
    _buckets.clear()


# ---------------------------------------------------------------------------
# R8-03 幂等
# ---------------------------------------------------------------------------
def request_fingerprint(payload):
    text = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]


def begin_idempotent(account, key, payload):
    """返回 ``(existing_response, fingerprint)``；无既存记录时返回 (None, fp)。"""
    if not key:
        return None, request_fingerprint(payload)

    fingerprint = request_fingerprint(payload)
    existing = IdempotencyKey.objects.filter(key=key).first()
    if existing is not None:
        if existing.request_hash != fingerprint:
            raise ApiError('IDEMPOTENCY_CONFLICT',
                           '同一幂等键对应的请求内容不一致', 409)
        return {'status': existing.status_code, 'body': existing.response_json}, fingerprint

    return None, fingerprint


def store_idempotent(key, account, fingerprint, status_code, body):
    if not key:
        return
    IdempotencyKey.objects.create(
        key=key, account_name=account.name if account else '',
        request_hash=fingerprint, status_code=status_code, response_json=body,
    )


# ---------------------------------------------------------------------------
# R8-01 资源查询（复用各模块的 scope）
# ---------------------------------------------------------------------------
def list_units(account, *, page=1, page_size=20, keyword=None):
    from smass_organization.models import OrganizationUnit

    page_size = max(1, min(page_size, 100))
    queryset = OrganizationUnit.objects.all().order_by('code')
    if keyword:
        queryset = queryset.filter(name__icontains=keyword)

    total = queryset.count()
    rows = queryset[(page - 1) * page_size: page * page_size]

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'rows': [
            {'code': u.code, 'name': u.name, 'unit_type': u.unit_type,
             'status': u.status}
            for u in rows
        ],
    }


def list_students(account, *, page=1, page_size=20, unit_code=None, keyword=None):
    """学生列表：**必须**经过组织 scope（与服务端页面一致）。"""
    from smass_organization.services import (
        account_roles,
        scoped_students,
    )
    from r21_account.models import Account

    # 服务账号没有人员账号，因此按其 scopes 决定可见范围：
    # 只读 scope 不等同于"全校可见"，需要额外的 tenant 字段（本轮默认按空集处理）
    if account is not None:
        scoped = scoped_students_service_account(account)
    else:
        scoped = scoped_students(None)

    page_size = max(1, min(page_size, 100))
    if unit_code:
        scoped = scoped.filter(unit__code=unit_code)
    if keyword:
        scoped = scoped.filter(name__icontains=keyword)

    total = scoped.count()
    rows = scoped.select_related('unit').order_by('student_no')[
        (page - 1) * page_size: page * page_size
    ]

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'rows': [
            {'student_no': r.student_no, 'name': r.name,
             'unit': r.unit.code if r.unit else '', 'status': r.status}
            for r in rows
        ],
    }


def scoped_students_service_account(service_account):
    """服务账号的可见范围：默认空集，``write:students``/``read:students`` 不自动等于全校。

    本轮实现：只有显式配置 ``tenant_units``（未来字段）才可见；当前一律空集，
    以避免"给了 read scope 就拿到全校数据"这种默认放大。
    """
    from smass_organization.models import StudentRecord

    allowed = getattr(service_account, 'scopes', []) or []
    if 'admin:students' in allowed:      # 需要显式的高权 scope（默认不存在）
        return StudentRecord.objects.all()
    return StudentRecord.objects.none()


def list_sections(account, *, page=1, page_size=20):
    from smass_academic.models import TeachingSection

    page_size = max(1, min(page_size, 100))
    queryset = TeachingSection.objects.select_related('term', 'course').order_by('code')
    total = queryset.count()
    rows = queryset[(page - 1) * page_size: page * page_size]

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'rows': [
            {'code': s.code, 'course': s.course.title if s.course else '',
             'term': str(s.term) if s.term else '', 'status': s.status}
            for s in rows
        ],
    }


def list_workflow_instances(account, *, page=1, page_size=20, status=None):
    from smass_workflow.models import WorkflowInstance

    page_size = max(1, min(page_size, 100))
    queryset = WorkflowInstance.objects.select_related('current_node').order_by('-created_at')
    if status:
        queryset = queryset.filter(status=status)

    total = queryset.count()
    rows = queryset[(page - 1) * page_size: page * page_size]

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'rows': [
            {'id': i.pk, 'subject': '{}:{}'.format(i.subject_type, i.subject_id),
             'status': i.status,
             'node': i.current_node.code if i.current_node else ''}
            for i in rows
        ],
    }


# ---------------------------------------------------------------------------
# R8-04 mock 同步适配器
# ---------------------------------------------------------------------------
def run_mock_sync(account, payload):
    """本地 mock 同步：不连接任何外部系统。"""
    records = payload.get('records') or []
    if not isinstance(records, list):
        raise ApiError('INVALID_PAYLOAD', 'records 必须是数组', 400)

    seen = set()
    accepted, replayed = 0, 0
    errors = []

    with transaction.atomic():
        job = SyncJob.objects.create(
            connector='local_mock', status='running', payload={'count': len(records)}
        )

        for index, record in enumerate(records):
            external_id = str(record.get('external_id') or '')
            if not external_id:
                errors.append({'index': index, 'code': 'MISSING_ID'})
                continue
            if external_id in seen:
                replayed += 1
                continue
            seen.add(external_id)
            accepted += 1

        job.status = 'done' if not errors else 'failed'
        job.replay_detected = replayed > 0
        job.result = {
            'accepted': accepted, 'replayed': replayed,
            'errors': errors[:20], 'error_count': len(errors),
        }
        from django.utils import timezone

        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'replay_detected', 'result', 'finished_at'])

    return {
        'job_id': str(job.job_id),
        'status': job.status,
        'accepted': accepted,
        'replayed': replayed,
        'errors': errors[:20],
    }


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
def log_call(account, request, status_code, duration_ms):
    try:
        ApiCallLog.objects.create(
            account_name=account.name if account else '',
            method=request.method[:8], path=request.path[:255],
            status_code=status_code, duration_ms=int(duration_ms),
            client_ip=(request.META.get('REMOTE_ADDR') or '')[:45],
        )
    except Exception:  # noqa: BLE001 - 审计失败不影响响应
        pass


# ---------------------------------------------------------------------------
# R8-01 OpenAPI（从实际端点定义生成，不引第三方工具）
# ---------------------------------------------------------------------------
def openapi_schema():
    """返回 /api/v1/ 的 OpenAPI 3.0 描述。"""
    return {
        'openapi': '3.0.0',
        'info': {
            'title': 'SMASS API',
            'version': 'v1',
            'description': 'SMASS 平台化接口（隔离环境；服务账号 Bearer 认证）',
        },
        'servers': [{'url': '/api/v1'}],
        'components': {
            'securitySchemes': {
                'bearerAuth': {'type': 'http', 'scheme': 'bearer'},
            },
            'schemas': {
                'Error': {
                    'type': 'object',
                    'properties': {
                        'error': {
                            'type': 'object',
                            'properties': {
                                'code': {'type': 'string'},
                                'message': {'type': 'string'},
                            },
                            'required': ['code', 'message'],
                        }
                    },
                    'required': ['error'],
                },
                'PagedUnits': {
                    'type': 'object',
                    'properties': {
                        'total': {'type': 'integer'},
                        'page': {'type': 'integer'},
                        'page_size': {'type': 'integer'},
                        'rows': {'type': 'array', 'items': {'type': 'object'}},
                    },
                },
            },
        },
        'security': [{'bearerAuth': []}],
        'paths': {
            '/units/': {
                'get': {
                    'summary': '组织单元列表',
                    'security': [{'bearerAuth': []}],
                    'parameters': [
                        {'name': 'page', 'in': 'query', 'schema': {'type': 'integer'}},
                        {'name': 'page_size', 'in': 'query', 'schema': {'type': 'integer'}},
                        {'name': 'q', 'in': 'query', 'schema': {'type': 'string'}},
                    ],
                    'responses': {
                        '200': {'description': 'OK'},
                        '401': {'description': 'UNAUTHENTICATED'},
                        '403': {'description': 'FORBIDDEN'},
                        '429': {'description': 'RATE_LIMITED'},
                    },
                }
            },
            '/students/': {
                'get': {
                    'summary': '学生档案列表（受 scope 与租户范围限制）',
                    'responses': {'200': {'description': 'OK'}},
                }
            },
            '/sections/': {
                'get': {'summary': '教学班列表', 'responses': {'200': {'description': 'OK'}}},
            },
            '/workflow/instances/': {
                'get': {'summary': '工作流实例列表', 'responses': {'200': {'description': 'OK'}}},
            },
            '/sync/': {
                'post': {
                    'summary': '本地 mock 同步（不连接外部系统）',
                    'parameters': [
                        {'name': 'Idempotency-Key', 'in': 'header',
                         'schema': {'type': 'string'}},
                    ],
                    'responses': {
                        '200': {'description': 'OK'},
                        '409': {'description': 'IDEMPOTENCY_CONFLICT'},
                    },
                }
            },
        },
    }
