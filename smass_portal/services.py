"""R20 服务层：门户区块、链接解析、公告与默认初始化。"""
from __future__ import annotations

import logging

from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from r21_account import authorization as authz

from .models import (
    ALL_ROLES,
    NOTICE_PUBLISHED,
    ROLE_COLLEGE_ADMIN,
    ROLE_STUDENT,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEACHER,
    PortalLink,
    PortalNotice,
    PortalSection,
)

logger = logging.getLogger('smass.audit')

ADMIN_ROLES = frozenset({ROLE_SYSTEM_ADMIN, ROLE_COLLEGE_ADMIN})


class PortalError(ValueError):
    def __init__(self, message, code='PORTAL_ERROR'):
        self.code = code
        super().__init__(message)


class PermissionDenied(PortalError):
    def __init__(self, message='当前账号没有该操作权限'):
        super().__init__(message, code='PERMISSION_DENIED')


def _actor_id(account):
    pk = getattr(account, 'pk', None)
    return '' if pk is None else str(pk)[:32]


def roles_of(account):
    return set(authz.active_roles(account))


def can_admin_portal(account):
    roles = roles_of(account)
    if not roles:
        return False
    if roles & ADMIN_ROLES:
        return True
    return authz.has_action(account, 'manage_roles')


def _tokens(raw):
    return {part.strip() for part in str(raw or '').split(',') if part.strip()}


def _visible(raw_roles, account_roles):
    if not account_roles:
        return False
    return bool(_tokens(raw_roles) & account_roles)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def visible_sections(account):
    roles = roles_of(account)
    if not roles:
        return PortalSection.objects.none()
    sections = []
    for section in PortalSection.objects.filter(enabled=True):
        if _visible(section.roles, roles):
            sections.append(section)
    return sections


def visible_links(section, account):
    roles = roles_of(account)
    if not roles:
        return []
    return [link for link in section.links.filter(enabled=True)
            if _visible(link.roles, roles)]


def resolve_link(link):
    """优先 reverse，失败回退 fallback_url，再失败返回 '#'。"""
    if link.url_name:
        try:
            return reverse(link.url_name)
        except NoReverseMatch:
            pass
    return link.fallback_url or '#'


def portal_context(account):
    sections = []
    for section in visible_sections(account):
        links = [{'link': link, 'href': resolve_link(link)}
                 for link in visible_links(section, account)]
        if not links:
            continue
        sections.append({'section': section, 'links': links})
    return {
        'sections': sections,
        'notices': visible_notices(account),
        'roles': sorted(roles_of(account)),
    }


def visible_notices(account):
    roles = roles_of(account)
    if not roles:
        return []
    if can_admin_portal(account):
        return list(PortalNotice.objects.all())
    return [notice for notice in PortalNotice.objects.filter(status=NOTICE_PUBLISHED)
            if _visible(notice.roles, roles)]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def create_section(actor, code, title, *, roles=ALL_ROLES, subtitle='',
                   sort_order=0):
    if not can_admin_portal(actor):
        raise PermissionDenied()
    if not str(code or '').strip() or not str(title or '').strip():
        raise PortalError('区块编码与标题不能为空', code='EMPTY_FIELD')
    if PortalSection.objects.filter(code=str(code).strip()).exists():
        raise PortalError('区块编码已存在', code='DUPLICATE_CODE')
    section = PortalSection.objects.create(
        code=str(code).strip()[:64], title=str(title).strip()[:64],
        subtitle=str(subtitle or '')[:120],
        roles=str(roles or ALL_ROLES)[:120], sort_order=int(sort_order or 0))
    logger.info('portal_section_created id=%s code=%s by=%s',
                section.pk, section.code, _actor_id(actor))
    return section


def create_link(section, label, *, url_name='', fallback_url='',
                roles=ALL_ROLES, actor=None, sort_order=0):
    if not can_admin_portal(actor):
        raise PermissionDenied()
    if not str(label or '').strip():
        raise PortalError('链接文字不能为空', code='EMPTY_LABEL')
    if not url_name and not fallback_url:
        raise PortalError('必须提供 URL 名或备用地址', code='EMPTY_TARGET')
    link = PortalLink.objects.create(
        section=section, label=str(label).strip()[:64],
        url_name=str(url_name or '')[:120],
        fallback_url=str(fallback_url or '')[:200],
        roles=str(roles or ALL_ROLES)[:120], sort_order=int(sort_order or 0))
    logger.info('portal_link_created id=%s section=%s by=%s',
                link.pk, section.code, _actor_id(actor))
    return link


def create_notice(actor, title, body, *, roles=ALL_ROLES):
    if not can_admin_portal(actor):
        raise PermissionDenied()
    if not str(title or '').strip() or not str(body or '').strip():
        raise PortalError('公告标题与内容不能为空', code='EMPTY_FIELD')
    notice = PortalNotice.objects.create(
        title=str(title).strip()[:120], body=str(body).strip()[:1000],
        roles=str(roles or ALL_ROLES)[:120], created_by=_actor_id(actor))
    logger.info('portal_notice_created id=%s by=%s',
                notice.pk, _actor_id(actor))
    return notice


def publish_notice(notice, actor):
    if not can_admin_portal(actor):
        raise PermissionDenied()
    if notice.status == NOTICE_PUBLISHED:
        raise PortalError('公告已发布', code='BAD_STATE')
    notice.status = NOTICE_PUBLISHED
    notice.published_at = timezone.now()
    notice.save(update_fields=['status', 'published_at'])
    logger.info('portal_notice_published id=%s by=%s',
                notice.pk, _actor_id(actor))
    return notice


# ---------------------------------------------------------------------------
# 默认门户
# ---------------------------------------------------------------------------
DEFAULT_SECTIONS = [
    ('student', '学生门户', '学籍、考勤、活动与生活服务', ROLE_STUDENT, 10, [
        ('我的学籍/异动', '', '/r12/status/'),
        ('转专业申请', '', '/r12/transfers/'),
        ('考勤与请假', '', '/r13/sessions/'),
        ('第二课堂与志愿', '', '/r14/activities/'),
        ('社团与学生会', '', '/r15/clubs/'),
        ('校园论坛', '', '/r17/forum/'),
        ('我的账单', '', '/r18/bills/'),
    ]),
    ('teacher', '教师/辅导员门户', '教学、考勤、活动与审批', ROLE_TEACHER, 20, [
        ('考勤管理', '', '/r13/sessions/'),
        ('活动组织', '', '/r14/activities/'),
        ('社团管理', '', '/r15/clubs/'),
        ('论坛管理', '', '/r17/forum/'),
        ('专项组织', '', '/r19/orgs/'),
    ]),
    ('admin', '管理人员门户', '教务、财务、审计与内容治理',
     '{},{}'.format(ROLE_COLLEGE_ADMIN, ROLE_SYSTEM_ADMIN), 30, [
         ('自动分班', '', '/r12/placement/'),
         ('考勤统计', '', '/r13/stats/'),
         ('活动认定', '', '/r14/credits/'),
         ('干部任职', '', '/r15/posts/'),
         ('举报处理', '', '/r17/reports/'),
         ('财务台账', '', '/r18/ledger/'),
         ('资料访问审计', '', '/r19/audit/'),
     ]),
]


def bootstrap_defaults():
    """幂等创建默认门户（区块 + 链接 + 欢迎公告）。"""
    created_sections = 0
    created_links = 0
    for code, title, subtitle, roles, order, links in DEFAULT_SECTIONS:
        section, is_new = PortalSection.objects.get_or_create(
            code=code,
            defaults={'title': title, 'subtitle': subtitle, 'roles': roles,
                      'sort_order': order, 'enabled': True})
        created_sections += 1 if is_new else 0
        for index, (label, url_name, fallback) in enumerate(links):
            _, link_new = PortalLink.objects.get_or_create(
                section=section, label=label,
                defaults={'url_name': url_name, 'fallback_url': fallback,
                          'roles': roles, 'sort_order': index * 10,
                          'enabled': True})
            created_links += 1 if link_new else 0

    notice, notice_new = PortalNotice.objects.get_or_create(
        title='欢迎使用 SMASS 智慧校园平台',
        defaults={'body': '请从左侧门户入口进入各业务系统；账号与权限由统一身份平台管理。',
                  'roles': ALL_ROLES, 'status': NOTICE_PUBLISHED,
                  'published_at': timezone.now(), 'created_by': 'system'})
    return {'sections': created_sections, 'links': created_links,
            'notice_created': notice_new}


def section_stats():
    return {
        'sections': PortalSection.objects.count(),
        'links': PortalLink.objects.count(),
        'notices': PortalNotice.objects.count(),
    }
