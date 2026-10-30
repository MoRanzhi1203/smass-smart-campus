"""R15：团委、学生会、学生社团与干部任职（隔离模块）。

设计约定
--------
1. 组织（团委/学生会/社团/协会）用 ``Club`` 表示，可自引用形成上级关系；
2. 加入要"申请 → 审批"；成员角色分 ``member`` / ``leader``；
3. 干部任职单独建模 ``ClubPost``（职务 + 任期），与成员身份解耦，
   便于"同一人多个职务"和"任期结束后保留历史"；
4. 同一社团同一任期同一职务只能有一名在任者（服务层行锁内校验，
   MySQL 不支持条件唯一约束）；
5. 社团负责人可审批本社团加入申请与任命，但不能审批自己的申请（职责分离）。
"""
from __future__ import annotations

from django.db import models

# ---------------------------------------------------------------------------
# 组织
# ---------------------------------------------------------------------------
CATEGORY_LEAGUE = 'league'
CATEGORY_UNION = 'student_union'
CATEGORY_CLUB = 'club'
CATEGORY_ASSOCIATION = 'association'
CLUB_CATEGORIES = (
    (CATEGORY_LEAGUE, '团委'),
    (CATEGORY_UNION, '学生会'),
    (CATEGORY_CLUB, '学生社团'),
    (CATEGORY_ASSOCIATION, '协会'),
)

CLUB_ACTIVE = 'active'
CLUB_ARCHIVED = 'archived'
CLUB_STATUS = (
    (CLUB_ACTIVE, '正常'),
    (CLUB_ARCHIVED, '已归档'),
)


class Club(models.Model):
    code = models.CharField('编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=100)
    category = models.CharField('类别', max_length=16, choices=CLUB_CATEGORIES,
                                default=CATEGORY_CLUB)
    parent = models.ForeignKey(
        'self', verbose_name='上级组织', null=True, blank=True,
        on_delete=models.PROTECT, related_name='children')
    advisor = models.ForeignKey(
        'r21_account.Account', verbose_name='指导教师',
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name='advised_clubs')
    description = models.CharField('简介', max_length=500, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=CLUB_STATUS,
                              default=CLUB_ACTIVE)

    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '群团组织'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['category', 'status']),
            models.Index(fields=['parent', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------
MEMBER_PENDING = 'pending'
MEMBER_ACTIVE = 'active'
MEMBER_LEFT = 'left'
MEMBER_REJECTED = 'rejected'
MEMBERSHIP_STATUS = (
    (MEMBER_PENDING, '待审批'),
    (MEMBER_ACTIVE, '在册'),
    (MEMBER_LEFT, '已退出'),
    (MEMBER_REJECTED, '已驳回'),
)

ROLE_MEMBER = 'member'
ROLE_LEADER = 'leader'
MEMBER_ROLES = (
    (ROLE_MEMBER, '成员'),
    (ROLE_LEADER, '负责人'),
)


class ClubMembership(models.Model):
    club = models.ForeignKey(
        Club, verbose_name='组织', on_delete=models.CASCADE,
        related_name='memberships')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='club_memberships')
    role = models.CharField('成员角色', max_length=16, choices=MEMBER_ROLES,
                            default=ROLE_MEMBER)
    status = models.CharField('状态', max_length=16, choices=MEMBERSHIP_STATUS,
                              default=MEMBER_PENDING)

    applied_at = models.DateTimeField('申请时间', auto_now_add=True)
    joined_at = models.DateTimeField('加入时间', null=True, blank=True)
    left_at = models.DateTimeField('退出时间', null=True, blank=True)
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = '组织成员'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['club', 'record'], name='r15_uniq_club_record'),
        ]
        indexes = [
            models.Index(fields=['club', 'status']),
            models.Index(fields=['record', 'status']),
        ]

    def __str__(self):
        return '{} @ {}'.format(self.record.student_no, self.club.code)


# ---------------------------------------------------------------------------
# 干部任职
# ---------------------------------------------------------------------------
POST_PRESIDENT = 'president'
POST_VICE_PRESIDENT = 'vice_president'
POST_MINISTER = 'minister'
POST_SECRETARY = 'secretary'
POST_TITLES = (
    (POST_PRESIDENT, '主席/会长'),
    (POST_VICE_PRESIDENT, '副主席/副会长'),
    (POST_MINISTER, '部长'),
    (POST_SECRETARY, '书记/秘书长'),
)
#: 每个社团同一任期只能有一人的职务
UNIQUE_POSTS = {POST_PRESIDENT, POST_VICE_PRESIDENT, POST_SECRETARY}

POST_ACTIVE = 'active'
POST_ENDED = 'ended'
POST_STATUS = (
    (POST_ACTIVE, '在任'),
    (POST_ENDED, '已卸任'),
)


class ClubPost(models.Model):
    club = models.ForeignKey(
        Club, verbose_name='组织', on_delete=models.CASCADE,
        related_name='posts')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='club_posts')
    title = models.CharField('职务', max_length=24, choices=POST_TITLES)
    term = models.CharField('任期', max_length=32, help_text='如 2026-2027 学年')
    status = models.CharField('状态', max_length=16, choices=POST_STATUS,
                              default=POST_ACTIVE)

    appointed_by = models.CharField('任命人', max_length=32, blank=True, default='')
    appointed_at = models.DateTimeField('任命时间', auto_now_add=True)
    ended_at = models.DateTimeField('卸任时间', null=True, blank=True)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '干部任职'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['club', 'term', 'status']),
            models.Index(fields=['record', 'status']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.club.code, self.get_title_display(), self.term)
