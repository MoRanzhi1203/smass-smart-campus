"""R19 服务层：党建/专项组织、成员、活动、受控资料与访问审计。

核心约束
--------
- 资料分三级：公开（登录可见）、内部（本组织成员/党务管理员）、敏感（需授权或按次审批）；
- **未授权访问不返回正文**，只返回受控占位，并写一条 ``deny`` 审计；
- 借阅申请有有效期，过期自动视为 ``expired``；
- 访问审计 append-only，任何修改/删除抛错；
- 本模块不存真实党建材料，``summary`` 只是合成摘要。
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode
from smass_organization.models import StudentRecord

from .models import (
    ACT_CANCELLED,
    ACT_DONE,
    ACT_PLANNED,
    ACTIVITY_TYPES,
    CLASS_INTERNAL,
    CLASS_PUBLIC,
    CLASS_SENSITIVE,
    CLASSIFICATIONS,
    DOC_PUBLISHED,
    GRANT_SENSITIVE,
    LOG_APPROVE,
    LOG_DENY,
    LOG_REJECT,
    LOG_REQUEST,
    LOG_VIEW,
    MEMBER_ACTIVE,
    MEMBER_LEFT,
    ORG_ACTIVE,
    ORG_TYPES,
    POLITICAL_STATUS,
    REQ_APPROVED,
    REQ_EXPIRED,
    REQ_REJECTED,
    REQ_SUBMITTED,
    AccessGrant,
    AccessLog,
    AccessRequest,
    PartyActivity,
    PartyDocument,
    PartyMember,
    PartyOrg,
)

logger = logging.getLogger('smass.audit')

PARTY_ROLES = frozenset({RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN})

MASKED = '（受控资料：需授权或按次审批后查看）'


class PartyError(ValueError):
    def __init__(self, message, code='PARTY_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(PartyError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _is_self(account, identity):
    if account is None or not identity:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def can_manage_party(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & PARTY_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def _require_party(account):
    if not can_manage_party(account):
        raise PermissionDenied('只有党务管理员可以执行该操作')


def record_for_account(account):
    return StudentRecord.objects.filter(account=account).first()


def is_org_member(account, org):
    record = record_for_account(account)
    if record is None:
        return False
    return PartyMember.objects.filter(
        org=org, record=record, status=MEMBER_ACTIVE).exists()


def has_clearance(account):
    if getattr(account, 'pk', None) is None:
        return False
    now = timezone.now()
    qs = AccessGrant.objects.filter(
        account=account, level=GRANT_SENSITIVE, revoked_at__isnull=True)
    qs = qs.filter(models_q_expiry(now))
    return qs.exists()


def models_q_expiry(now):
    from django.db.models import Q
    return Q(expires_at__isnull=True) | Q(expires_at__gt=now)


# ---------------------------------------------------------------------------
# 组织与成员
# ---------------------------------------------------------------------------
def create_org(actor, code, name, org_type, *, parent=None,
               sensitivity='normal'):
    _require_party(actor)
    if not str(code or '').strip() or not str(name or '').strip():
        raise PartyError('组织编码与名称不能为空', code='EMPTY_FIELD')
    if org_type not in dict(ORG_TYPES):
        raise PartyError('未知的组织类型', code='BAD_TYPE')
    if PartyOrg.objects.filter(code=str(code).strip()).exists():
        raise PartyError('组织编码已存在', code='DUPLICATE_CODE')
    org = PartyOrg.objects.create(
        code=str(code).strip()[:64], name=str(name).strip()[:100],
        org_type=org_type, parent=parent, sensitivity=sensitivity,
        status=ORG_ACTIVE, created_by=_actor_id(actor))
    logger.info('party_org_created id=%s code=%s by=%s',
                org.pk, org.code, _actor_id(actor))
    return org


def add_member(org, record, political_status, actor, *, joined_at=None, note=''):
    _require_party(actor)
    if record is None:
        raise PartyError('学籍档案不存在', code='NO_RECORD')
    if political_status not in dict(POLITICAL_STATUS):
        raise PartyError('未知的政治面貌', code='BAD_POLITICAL')
    if org.status != ORG_ACTIVE:
        raise PartyError('组织已归档', code='ORG_ARCHIVED')

    with transaction.atomic():
        existing = PartyMember.objects.filter(org=org, record=record).first()
        if existing is not None and existing.status == MEMBER_ACTIVE:
            raise PartyError('该学生已是本组织成员', code='DUPLICATE_MEMBER')
        if existing is None:
            member = PartyMember.objects.create(
                org=org, record=record, political_status=political_status,
                joined_at=joined_at, status=MEMBER_ACTIVE,
                note=str(note or '')[:200])
        else:
            existing.status = MEMBER_ACTIVE
            existing.political_status = political_status
            existing.note = str(note or '')[:200]
            existing.save(update_fields=['status', 'political_status', 'note'])
            member = existing
    logger.info('party_member_added org=%s record=%s by=%s',
                org.pk, record.student_no, _actor_id(actor))
    return member


def remove_member(member, actor):
    _require_party(actor)
    if member.status != MEMBER_ACTIVE:
        raise PartyError('成员已不在册', code='BAD_STATE')
    member.status = MEMBER_LEFT
    member.save(update_fields=['status'])
    logger.info('party_member_removed org=%s record=%s by=%s',
                member.org_id, member.record.student_no, _actor_id(actor))
    return member


# ---------------------------------------------------------------------------
# 活动
# ---------------------------------------------------------------------------
def create_activity(org, title, activity_type, held_on, actor, *, summary=''):
    _require_party(actor)
    if not str(title or '').strip():
        raise PartyError('活动主题不能为空', code='EMPTY_TITLE')
    if activity_type not in dict(ACTIVITY_TYPES):
        raise PartyError('未知的活动类型', code='BAD_TYPE')
    if held_on is None:
        raise PartyError('请填写开展日期', code='MISSING_DATE')
    activity = PartyActivity.objects.create(
        org=org, title=str(title).strip()[:120], activity_type=activity_type,
        held_on=held_on, summary=str(summary or '')[:500],
        status=ACT_PLANNED, created_by=_actor_id(actor))
    logger.info('party_activity_created id=%s org=%s by=%s',
                activity.pk, org.code, _actor_id(actor))
    return activity


def complete_activity(activity, actor, *, summary=''):
    _require_party(actor)
    if activity.status != ACT_PLANNED:
        raise PartyError('只有计划中的活动可以标记完成', code='BAD_STATE')
    activity.status = ACT_DONE
    if summary:
        activity.summary = str(summary)[:500]
    activity.save(update_fields=['status', 'summary'])
    logger.info('party_activity_done id=%s by=%s', activity.pk, _actor_id(actor))
    return activity


def cancel_activity(activity, actor):
    _require_party(actor)
    if activity.status != ACT_PLANNED:
        raise PartyError('只有计划中的活动可以取消', code='BAD_STATE')
    activity.status = ACT_CANCELLED
    activity.save(update_fields=['status'])
    logger.info('party_activity_cancelled id=%s by=%s',
                activity.pk, _actor_id(actor))
    return activity


# ---------------------------------------------------------------------------
# 受控资料与访问
# ---------------------------------------------------------------------------
def create_document(org, title, classification, summary, actor):
    _require_party(actor)
    if not str(title or '').strip():
        raise PartyError('资料标题不能为空', code='EMPTY_TITLE')
    if classification not in dict(CLASSIFICATIONS):
        raise PartyError('未知的密级', code='BAD_CLASSIFICATION')
    document = PartyDocument.objects.create(
        org=org, title=str(title).strip()[:120], classification=classification,
        summary=str(summary or '')[:500], status=DOC_PUBLISHED,
        created_by=_actor_id(actor))
    logger.info('party_document_created id=%s org=%s class=%s by=%s',
                document.pk, org.code, classification, _actor_id(actor))
    return document


def _approved_request(account, document):
    if getattr(account, 'pk', None) is None:
        return None
    now = timezone.now()
    return AccessRequest.objects.filter(
        document=document, applicant=account, status=REQ_APPROVED,
        valid_until__gt=now).first()


def can_view(account, document):
    """是否可查看资料正文。"""
    if getattr(account, 'pk', None) is None:
        return document.classification == CLASS_PUBLIC
    if can_manage_party(account):
        return True
    if document.classification == CLASS_PUBLIC:
        return True
    if document.classification == CLASS_INTERNAL:
        return is_org_member(account, document.org)
    # sensitive
    if has_clearance(account):
        return True
    return _approved_request(account, document) is not None


def _log(account, document, action, purpose='', ip=''):
    return AccessLog.objects.create(
        account=account if getattr(account, 'pk', None) is not None else None,
        account_id_text=_actor_id(account), document=document,
        action=action, purpose=str(purpose or '')[:200], ip=str(ip or '')[:64])


def view_document(document, actor, *, purpose='', ip=''):
    """受控查看：允许则返回摘要并记 view，否则记 deny 并返回占位。"""
    if can_view(actor, document):
        _log(actor, document, LOG_VIEW, purpose, ip)
        return {'allowed': True, 'summary': document.summary, 'masked': False}
    _log(actor, document, LOG_DENY, purpose, ip)
    logger.info('party_document_denied id=%s by=%s',
                document.pk, _actor_id(actor))
    return {'allowed': False, 'summary': MASKED, 'masked': True}


def request_access(document, purpose, applicant):
    if getattr(applicant, 'pk', None) is None:
        raise PartyError('请先登录', code='NOT_AUTHENTICATED')
    if document.classification != CLASS_SENSITIVE:
        raise PartyError('只有敏感资料需要按次审批', code='NOT_SENSITIVE')
    if not str(purpose or '').strip():
        raise PartyError('借阅必须填写用途', code='EMPTY_PURPOSE')
    if can_view(applicant, document):
        raise PartyError('你已有该资料的查看权限', code='ALREADY_ALLOWED')
    if AccessRequest.objects.filter(
            document=document, applicant=applicant,
            status=REQ_SUBMITTED).exists():
        raise PartyError('你已有待审批的申请', code='DUPLICATE_REQUEST')

    request = AccessRequest.objects.create(
        document=document, applicant=applicant,
        purpose=str(purpose).strip()[:500], status=REQ_SUBMITTED)
    _log(applicant, document, LOG_REQUEST, purpose)
    logger.info('party_access_requested id=%s doc=%s by=%s',
                request.pk, document.pk, _actor_id(applicant))
    return request


def approve_access(request, actor, *, valid_days=7):
    _require_party(actor)
    if request.status != REQ_SUBMITTED:
        raise PartyError('只有待审批的申请可以批准', code='BAD_STATE')
    if _is_self(actor, request.applicant_id):
        raise PartyError('不能审批自己提交的借阅申请（职责分离）',
                         code='SELF_APPROVAL_DENIED')
    if valid_days <= 0:
        raise PartyError('有效期必须大于 0 天', code='BAD_VALIDITY')

    request.status = REQ_APPROVED
    request.reviewed_by = _actor_id(actor)
    request.reviewed_at = timezone.now()
    request.valid_until = timezone.now() + timezone.timedelta(days=valid_days)
    request.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                                'valid_until'])
    _log(actor, request.document, LOG_APPROVE,
         '批准借阅 {}'.format(request.pk))
    logger.info('party_access_approved id=%s by=%s days=%s',
                request.pk, _actor_id(actor), valid_days)
    return request


def reject_access(request, actor, reason):
    _require_party(actor)
    if request.status != REQ_SUBMITTED:
        raise PartyError('只有待审批的申请可以驳回', code='BAD_STATE')
    if _is_self(actor, request.applicant_id):
        raise PartyError('不能驳回自己提交的借阅申请（职责分离）',
                         code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise PartyError('驳回必须填写原因', code='EMPTY_REASON')

    request.status = REQ_REJECTED
    request.reviewed_by = _actor_id(actor)
    request.reviewed_at = timezone.now()
    request.reject_reason = str(reason).strip()[:255]
    request.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                                'reject_reason'])
    _log(actor, request.document, LOG_REJECT,
         '驳回借阅 {}'.format(request.pk))
    logger.info('party_access_rejected id=%s by=%s',
                request.pk, _actor_id(actor))
    return request


def expire_requests(now=None):
    """把已过有效期的批准申请标记为 expired（惰性清理）。"""
    now = now or timezone.now()
    updated = AccessRequest.objects.filter(
        status=REQ_APPROVED, valid_until__lt=now).update(status=REQ_EXPIRED)
    if updated:
        logger.info('party_access_expired count=%s', updated)
    return updated


def grant_clearance(account, actor, *, valid_days=365):
    _require_party(actor)
    if _is_self(actor, account.pk):
        raise PartyError('不能给自己授予敏感资料权限（职责分离）',
                         code='SELF_GRANT_DENIED')
    grant = AccessGrant.objects.create(
        account=account, level=GRANT_SENSITIVE, granted_by=_actor_id(actor),
        expires_at=timezone.now() + timezone.timedelta(days=max(1, valid_days)))
    logger.info('party_clearance_granted account=%s by=%s',
                account.pk, _actor_id(actor))
    return grant


def revoke_clearance(grant, actor):
    _require_party(actor)
    if grant.revoked_at is not None:
        raise PartyError('授权已撤销', code='BAD_STATE')
    grant.revoked_at = timezone.now()
    grant.save(update_fields=['revoked_at'])
    logger.info('party_clearance_revoked grant=%s by=%s',
                grant.pk, _actor_id(actor))
    return grant


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def scoped_orgs(account):
    qs = PartyOrg.objects.select_related('parent')
    if can_manage_party(account):
        return qs.order_by('org_type', 'code')
    return qs.filter(status=ORG_ACTIVE).order_by('org_type', 'code')


def scoped_documents(account, org=None):
    """列表只返回元数据；正文是否可见由 ``view_document`` 判定。"""
    qs = PartyDocument.objects.select_related('org')
    if org is not None:
        qs = qs.filter(org=org)
    if can_manage_party(account):
        return qs.order_by('-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.filter(classification=CLASS_PUBLIC).order_by('-created_at')

    record = record_for_account(account)
    member_org_ids = []
    if record is not None:
        member_org_ids = list(PartyMember.objects.filter(
            record=record, status=MEMBER_ACTIVE).values_list('org_id', flat=True))
    from django.db.models import Q
    return qs.filter(
        Q(classification=CLASS_PUBLIC)
        | Q(classification=CLASS_INTERNAL, org_id__in=member_org_ids)
    ).order_by('-created_at')


def scoped_access_requests(account):
    qs = AccessRequest.objects.select_related('document', 'applicant')
    if can_manage_party(account):
        return qs.order_by('status', '-created_at')
    if getattr(account, 'pk', None) is None:
        return qs.none()
    return qs.filter(applicant=account).order_by('-created_at')


def scoped_audit_logs(account):
    if not can_manage_party(account):
        return AccessLog.objects.none()
    return AccessLog.objects.select_related('document').order_by('-created_at')


def org_summary(org):
    return {
        'members': org.members.filter(status=MEMBER_ACTIVE).count(),
        'activities': org.activities.count(),
        'documents': org.documents.count(),
        'sensitive_documents': org.documents.filter(
            classification=CLASS_SENSITIVE).count(),
    }
