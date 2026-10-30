"""R15 服务层：组织、成员申请审批与干部任职。

规则摘要
--------
- 组织创建/归档：团委老师或管理员；
- 加入：学生申请 → 社团负责人/管理员审批（不能审批自己的申请）；
- 退出：本人或管理员；
- 任职：必须是该社团在册成员；同一社团同一任期同一职务只能一名在任者；
  主席/副主席/书记每社团每任期唯一；
- 所有写操作在 ``select_for_update`` 行锁内完成唯一性校验。
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from r21_account import authorization as authz
from r21_account.models import RoleCode
from smass_organization.models import StudentRecord

from .models import (
    CLUB_ACTIVE,
    CLUB_ARCHIVED,
    CLUB_CATEGORIES,
    MEMBER_ACTIVE,
    MEMBER_LEFT,
    MEMBER_PENDING,
    MEMBER_REJECTED,
    MEMBERSHIP_STATUS,
    POST_ACTIVE,
    POST_ENDED,
    POST_PRESIDENT,
    POST_TITLES,
    POST_VICE_PRESIDENT,
    ROLE_LEADER,
    ROLE_MEMBER,
    UNIQUE_POSTS,
    Club,
    ClubMembership,
    ClubPost,
)

logger = logging.getLogger('smass.audit')

MANAGER_ROLES = frozenset({
    RoleCode.TEACHER, RoleCode.SYSTEM_ADMIN, RoleCode.COLLEGE_ADMIN,
})


class ClubError(ValueError):
    def __init__(self, message, code='CLUB_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(ClubError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def _is_self(account, identity):
    if account is None or not identity:
        return False
    return str(getattr(account, 'pk', '')) == str(identity)


def can_manage(account):
    roles = authz.active_roles(account)
    if not roles:
        return False
    if set(roles) & MANAGER_ROLES:
        return True
    return authz.has_action(account, 'update')


def record_for_account(account):
    return StudentRecord.objects.filter(account=account).first()


def is_leader(account, club):
    record = record_for_account(account)
    if record is None:
        return False
    if ClubMembership.objects.filter(
            club=club, record=record, status=MEMBER_ACTIVE,
            role=ROLE_LEADER).exists():
        return True
    return ClubPost.objects.filter(
        club=club, record=record, status=POST_ACTIVE,
        title__in=[POST_PRESIDENT, POST_VICE_PRESIDENT],
    ).exists()


def can_admin_club(account, club):
    return can_manage(account) or is_leader(account, club)


def _require_club_admin(account, club):
    if not can_admin_club(account, club):
        raise PermissionDenied('只有社团负责人或管理员可以执行该操作')


# ---------------------------------------------------------------------------
# 组织
# ---------------------------------------------------------------------------
def create_club(actor, code, name, category, *, parent=None, advisor=None,
                description=''):
    if not can_manage(actor):
        raise PermissionDenied()
    if not str(code or '').strip() or not str(name or '').strip():
        raise ClubError('编码与名称不能为空', code='EMPTY_FIELD')
    if category not in dict(CLUB_CATEGORIES):
        raise ClubError('未知的组织类别', code='BAD_CATEGORY')
    if Club.objects.filter(code=str(code).strip()).exists():
        raise ClubError('组织编码已存在', code='DUPLICATE_CODE')

    club = Club.objects.create(
        code=str(code).strip()[:64],
        name=str(name).strip()[:100],
        category=category,
        parent=parent,
        advisor=advisor,
        description=str(description or '')[:500],
        status=CLUB_ACTIVE,
        created_by=_actor_id(actor),
    )
    logger.info('club_created id=%s code=%s by=%s',
                club.pk, club.code, _actor_id(actor))
    return club


def archive_club(club, actor):
    if not can_manage(actor):
        raise PermissionDenied()
    if club.status == CLUB_ARCHIVED:
        raise ClubError('组织已归档', code='BAD_STATE')
    club.status = CLUB_ARCHIVED
    club.save(update_fields=['status', 'updated_at'])
    logger.info('club_archived id=%s by=%s', club.pk, _actor_id(actor))
    return club


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------
def apply_join(club, record, actor):
    if record is None:
        raise ClubError('学籍档案不存在', code='NO_RECORD')
    if not _is_self(actor, getattr(record.account, 'pk', None)):
        _require_club_admin(actor, club)
    if club.status != CLUB_ACTIVE:
        raise ClubError('该组织已归档，不能加入', code='CLUB_ARCHIVED')

    with transaction.atomic():
        locked = Club.objects.select_for_update().get(pk=club.pk)
        existing = ClubMembership.objects.filter(
            club=locked, record=record).first()
        if existing is not None and existing.status in (MEMBER_ACTIVE, MEMBER_PENDING):
            raise ClubError('你已加入或已提交申请', code='DUPLICATE_MEMBERSHIP')

        if existing is None:
            membership = ClubMembership.objects.create(
                club=locked, record=record, role=ROLE_MEMBER,
                status=MEMBER_PENDING)
        else:
            existing.status = MEMBER_PENDING
            existing.role = ROLE_MEMBER
            existing.left_at = None
            existing.save(update_fields=['status', 'role', 'left_at'])
            membership = existing

    logger.info('club_join_applied club=%s record=%s by=%s',
                club.pk, record.student_no, _actor_id(actor))
    return membership


def approve_join(membership, actor):
    club = membership.club
    _require_club_admin(actor, club)
    if membership.status != MEMBER_PENDING:
        raise ClubError('只有待审批的申请可以批准', code='BAD_STATE')
    if _is_self(actor, membership.record.account_id):
        raise ClubError('不能审批自己的加入申请（职责分离）',
                        code='SELF_APPROVAL_DENIED')

    membership.status = MEMBER_ACTIVE
    membership.joined_at = timezone.now()
    membership.reviewed_by = _actor_id(actor)
    membership.reviewed_at = timezone.now()
    membership.save(update_fields=['status', 'joined_at', 'reviewed_by',
                                   'reviewed_at'])
    logger.info('club_join_approved club=%s record=%s by=%s',
                club.pk, membership.record.student_no, _actor_id(actor))
    return membership


def reject_join(membership, actor, reason):
    club = membership.club
    _require_club_admin(actor, club)
    if membership.status != MEMBER_PENDING:
        raise ClubError('只有待审批的申请可以驳回', code='BAD_STATE')
    if _is_self(actor, membership.record.account_id):
        raise ClubError('不能驳回自己的加入申请（职责分离）',
                        code='SELF_APPROVAL_DENIED')
    if not str(reason or '').strip():
        raise ClubError('驳回必须填写原因', code='EMPTY_REASON')

    membership.status = MEMBER_REJECTED
    membership.reviewed_by = _actor_id(actor)
    membership.reviewed_at = timezone.now()
    membership.reject_reason = str(reason).strip()[:255]
    membership.save(update_fields=['status', 'reviewed_by', 'reviewed_at',
                                   'reject_reason'])
    logger.info('club_join_rejected club=%s record=%s by=%s',
                club.pk, membership.record.student_no, _actor_id(actor))
    return membership


def leave_club(membership, actor):
    if not _is_self(actor, membership.record.account_id) and not can_manage(actor):
        raise PermissionDenied()
    if membership.status not in (MEMBER_ACTIVE, MEMBER_PENDING):
        raise ClubError('当前状态不能退出', code='BAD_STATE')

    membership.status = MEMBER_LEFT
    membership.left_at = timezone.now()
    membership.save(update_fields=['status', 'left_at'])
    logger.info('club_left club=%s record=%s', membership.club_id,
                membership.record.student_no)
    return membership


def promote_leader(membership, actor):
    """把在册成员设为负责人（社团负责人/管理员可操作）。"""
    _require_club_admin(actor, membership.club)
    if membership.status != MEMBER_ACTIVE:
        raise ClubError('只有在册成员可以设为负责人', code='BAD_STATE')
    membership.role = ROLE_LEADER
    membership.save(update_fields=['role'])
    logger.info('club_leader_promoted club=%s record=%s by=%s',
                membership.club_id, membership.record.student_no, _actor_id(actor))
    return membership


def demote_leader(membership, actor):
    _require_club_admin(actor, membership.club)
    if membership.role != ROLE_LEADER:
        raise ClubError('该成员不是负责人', code='BAD_STATE')
    membership.role = ROLE_MEMBER
    membership.save(update_fields=['role'])
    logger.info('club_leader_demoted club=%s record=%s by=%s',
                membership.club_id, membership.record.student_no, _actor_id(actor))
    return membership


# ---------------------------------------------------------------------------
# 干部任职
# ---------------------------------------------------------------------------
def appoint_post(club, record, title, term, actor, *, note=''):
    _require_club_admin(actor, club)
    if title not in dict(POST_TITLES):
        raise ClubError('未知职务', code='BAD_TITLE')
    if not str(term or '').strip():
        raise ClubError('任期不能为空', code='EMPTY_TERM')
    if record is None:
        raise ClubError('学籍档案不存在', code='NO_RECORD')

    with transaction.atomic():
        locked = Club.objects.select_for_update().get(pk=club.pk)
        if not ClubMembership.objects.filter(
                club=locked, record=record, status=MEMBER_ACTIVE).exists():
            raise ClubError('该学生不是本组织在册成员', code='NOT_MEMBER')

        term_value = str(term).strip()[:32]
        if title in UNIQUE_POSTS:
            if ClubPost.objects.filter(
                    club=locked, title=title, term=term_value,
                    status=POST_ACTIVE).exists():
                raise ClubError('该任期该职务已有在任者', code='POST_TAKEN')

            conflict = ClubPost.objects.filter(
                club=locked, term=term_value, status=POST_ACTIVE,
                title__in=UNIQUE_POSTS).first()
            if conflict is not None:
                raise ClubError(
                    '该任期已有 {}（{}），请先卸任'.format(
                        conflict.get_title_display(), conflict.record.student_no),
                    code='POST_TAKEN')

        post = ClubPost.objects.create(
            club=locked, record=record, title=title, term=term_value,
            status=POST_ACTIVE, appointed_by=_actor_id(actor),
            note=str(note or '')[:200])
    logger.info('club_post_appointed club=%s record=%s title=%s term=%s by=%s',
                club.pk, record.student_no, title, term_value, _actor_id(actor))
    return post


def end_post(post, actor):
    _require_club_admin(actor, post.club)
    if post.status != POST_ACTIVE:
        raise ClubError('该任职已结束', code='BAD_STATE')
    post.status = POST_ENDED
    post.ended_at = timezone.now()
    post.save(update_fields=['status', 'ended_at'])
    logger.info('club_post_ended id=%s by=%s', post.pk, _actor_id(actor))
    return post


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def scoped_clubs(account, category=None):
    qs = Club.objects.select_related('parent', 'advisor')
    if category:
        qs = qs.filter(category=category)
    if can_manage(account):
        return qs.order_by('category', 'code')
    return qs.filter(status=CLUB_ACTIVE).order_by('category', 'code')


def scoped_memberships(account, club=None):
    qs = ClubMembership.objects.select_related('club', 'record')
    if club is not None:
        qs = qs.filter(club=club)
    if can_manage(account):
        return qs.order_by('status', 'record__student_no')
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record)


def scoped_posts(account, club=None):
    qs = ClubPost.objects.select_related('club', 'record')
    if club is not None:
        qs = qs.filter(club=club)
    if can_manage(account):
        return qs.order_by('club__code', 'title')
    record = record_for_account(account)
    if record is None:
        return qs.none()
    return qs.filter(record=record)


def club_stats(club):
    members = club.memberships.all()
    return {
        'active': members.filter(status=MEMBER_ACTIVE).count(),
        'pending': members.filter(status=MEMBER_PENDING).count(),
        'leaders': members.filter(status=MEMBER_ACTIVE, role=ROLE_LEADER).count(),
        'posts': club.posts.filter(status=POST_ACTIVE).count(),
    }


def active_posts(club, term=None):
    qs = club.posts.filter(status=POST_ACTIVE).select_related('record')
    if term:
        qs = qs.filter(term=term)
    return qs.order_by('title', 'record__student_no')
