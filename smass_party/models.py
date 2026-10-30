"""R19：党建及专项组织的**受控通用功能**（隔离模块）。

边界声明
--------
本模块只实现"通用机制"，**不承载真实党建敏感资料**：

- 资料正文用``summary`` 字段保存合成摘要，不存真实名单/谈话记录/审查材料；
- 敏感级别资料必须显式授权（``AccessGrant``）或按次借阅审批（``AccessRequest``）；
- 未授权访问返回脱敏占位，且每次访问写 ``AccessLog``（append-only）；
- 真实党建数据接入需另行授权，不在本轮范围。
"""
from __future__ import annotations

from django.db import models

# ---------------------------------------------------------------------------
# 组织
# ---------------------------------------------------------------------------
ORG_BRANCH = 'branch'
ORG_COMMITTEE = 'committee'
ORG_SPECIAL = 'special'
ORG_TYPES = (
    (ORG_BRANCH, '党支部'),
    (ORG_COMMITTEE, '党委/党总支'),
    (ORG_SPECIAL, '专项工作组'),
)

ORG_ACTIVE = 'active'
ORG_ARCHIVED = 'archived'

SENSITIVITY_NORMAL = 'normal'
SENSITIVITY_SENSITIVE = 'sensitive'
SENSITIVITY_LEVELS = (
    (SENSITIVITY_NORMAL, '普通'),
    (SENSITIVITY_SENSITIVE, '敏感（受控）'),
)


class PartyOrg(models.Model):
    code = models.CharField('编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=100)
    org_type = models.CharField('类型', max_length=16, choices=ORG_TYPES,
                                default=ORG_BRANCH)
    parent = models.ForeignKey(
        'self', verbose_name='上级组织', null=True, blank=True,
        on_delete=models.PROTECT, related_name='children')
    sensitivity = models.CharField('敏感级别', max_length=16,
                                    choices=SENSITIVITY_LEVELS,
                                    default=SENSITIVITY_NORMAL)
    status = models.CharField('状态', max_length=16, default=ORG_ACTIVE)
    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '党建/专项组织'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['org_type', 'status']),
            models.Index(fields=['parent', 'status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------
POLITICAL_PARTY_MEMBER = 'party_member'
POLITICAL_LEAGUE = 'league_member'
POLITICAL_ACTIVIST = 'activist'
POLITICAL_MASSES = 'masses'
POLITICAL_STATUS = (
    (POLITICAL_PARTY_MEMBER, '党员'),
    (POLITICAL_LEAGUE, '团员'),
    (POLITICAL_ACTIVIST, '入党积极分子'),
    (POLITICAL_MASSES, '群众'),
)

MEMBER_ACTIVE = 'active'
MEMBER_LEFT = 'left'


class PartyMember(models.Model):
    org = models.ForeignKey(
        PartyOrg, verbose_name='组织', on_delete=models.CASCADE,
        related_name='members')
    record = models.ForeignKey(
        'smass_organization.StudentRecord', verbose_name='学籍档案',
        on_delete=models.PROTECT, related_name='party_memberships')
    political_status = models.CharField('政治面貌', max_length=24,
                                         choices=POLITICAL_STATUS,
                                         default=POLITICAL_PARTY_MEMBER)
    joined_at = models.DateField('加入日期', null=True, blank=True)
    status = models.CharField('状态', max_length=16, default=MEMBER_ACTIVE)
    note = models.CharField('备注', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = '组织成员'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['org', 'record'], name='r19_uniq_org_record'),
        ]
        indexes = [models.Index(fields=['org', 'status'])]

    def __str__(self):
        return '{} @ {}'.format(self.record.student_no, self.org.code)


# ---------------------------------------------------------------------------
# 组织生活/活动
# ---------------------------------------------------------------------------
ACT_MEETING = 'meeting'
ACT_THEME_DAY = 'theme_party_day'
ACT_VOLUNTEER = 'volunteer'
ACT_TRAINING = 'training'
ACTIVITY_TYPES = (
    (ACT_MEETING, '三会一课'),
    (ACT_THEME_DAY, '主题党日'),
    (ACT_VOLUNTEER, '志愿服务'),
    (ACT_TRAINING, '教育培训'),
)

ACT_PLANNED = 'planned'
ACT_DONE = 'done'
ACT_CANCELLED = 'cancelled'
ACTIVITY_STATUS = (
    (ACT_PLANNED, '计划中'),
    (ACT_DONE, '已完成'),
    (ACT_CANCELLED, '已取消'),
)


class PartyActivity(models.Model):
    org = models.ForeignKey(
        PartyOrg, verbose_name='组织', on_delete=models.CASCADE,
        related_name='activities')
    title = models.CharField('主题', max_length=120)
    activity_type = models.CharField('类型', max_length=24, choices=ACTIVITY_TYPES,
                                      default=ACT_MEETING)
    held_on = models.DateField('开展日期')
    summary = models.CharField('纪要摘要（合成）', max_length=500, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=ACTIVITY_STATUS,
                              default=ACT_PLANNED)
    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '组织生活/专项活动'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['org', '-held_on'])]

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# 受控资料
# ---------------------------------------------------------------------------
CLASS_PUBLIC = 'public'
CLASS_INTERNAL = 'internal'
CLASS_SENSITIVE = 'sensitive'
CLASSIFICATIONS = (
    (CLASS_PUBLIC, '公开'),
    (CLASS_INTERNAL, '内部'),
    (CLASS_SENSITIVE, '敏感（受控）'),
)

DOC_DRAFT = 'draft'
DOC_PUBLISHED = 'published'
DOC_ARCHIVED = 'archived'
DOC_STATUS = (
    (DOC_DRAFT, '草稿'),
    (DOC_PUBLISHED, '已归档'),
    (DOC_ARCHIVED, '已封存'),
)


class PartyDocument(models.Model):
    org = models.ForeignKey(
        PartyOrg, verbose_name='组织', on_delete=models.CASCADE,
        related_name='documents')
    title = models.CharField('标题', max_length=120)
    classification = models.CharField('密级', max_length=16,
                                       choices=CLASSIFICATIONS,
                                       default=CLASS_INTERNAL)
    summary = models.CharField('摘要（合成，不含真实材料）', max_length=500,
                                blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=DOC_STATUS,
                              default=DOC_PUBLISHED)
    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '受控资料'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['org', 'classification'])]

    def __str__(self):
        return '{} [{}]'.format(self.title, self.get_classification_display())


# ---------------------------------------------------------------------------
# 授权与借阅
# ---------------------------------------------------------------------------
GRANT_NORMAL = 'normal'
GRANT_SENSITIVE = 'sensitive'
GRANT_LEVELS = (
    (GRANT_NORMAL, '普通资料'),
    (GRANT_SENSITIVE, '敏感资料'),
)


class AccessGrant(models.Model):
    """账号级长期授权（敏感资料访问）。"""

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='账号', on_delete=models.CASCADE,
        related_name='party_grants')
    level = models.CharField('级别', max_length=16, choices=GRANT_LEVELS,
                              default=GRANT_SENSITIVE)
    granted_by = models.CharField('授予人', max_length=32, blank=True, default='')
    granted_at = models.DateTimeField('授予时间', auto_now_add=True)
    expires_at = models.DateTimeField('到期时间', null=True, blank=True)
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)

    class Meta:
        verbose_name = '资料访问授权'
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=['account', 'level', 'revoked_at'])]

    def __str__(self):
        return '{} {}'.format(self.account_id, self.level)


REQ_SUBMITTED = 'submitted'
REQ_APPROVED = 'approved'
REQ_REJECTED = 'rejected'
REQ_EXPIRED = 'expired'
REQ_STATUS = (
    (REQ_SUBMITTED, '待审批'),
    (REQ_APPROVED, '已批准'),
    (REQ_REJECTED, '已驳回'),
    (REQ_EXPIRED, '已过期'),
)


class AccessRequest(models.Model):
    """按次借阅申请：敏感资料必须审批且有有效期。"""

    document = models.ForeignKey(
        PartyDocument, verbose_name='资料', on_delete=models.CASCADE,
        related_name='access_requests')
    applicant = models.ForeignKey(
        'r21_account.Account', verbose_name='申请人', on_delete=models.CASCADE,
        related_name='party_access_requests')
    purpose = models.CharField('用途', max_length=500)
    status = models.CharField('状态', max_length=16, choices=REQ_STATUS,
                              default=REQ_SUBMITTED)
    reviewed_by = models.CharField('审批人', max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    reject_reason = models.CharField('驳回原因', max_length=255, blank=True, default='')
    valid_until = models.DateTimeField('有效期至', null=True, blank=True)
    created_at = models.DateTimeField('申请时间', auto_now_add=True)

    class Meta:
        verbose_name = '资料借阅申请'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['applicant', 'status']),
        ]

    def __str__(self):
        return '{} 借阅 {}'.format(self.applicant_id, self.document_id)


# ---------------------------------------------------------------------------
# 访问审计
# ---------------------------------------------------------------------------
LOG_VIEW = 'view'
LOG_REQUEST = 'request'
LOG_APPROVE = 'approve'
LOG_REJECT = 'reject'
LOG_DENY = 'deny'
LOG_ACTIONS = (
    (LOG_VIEW, '查看'),
    (LOG_REQUEST, '申请借阅'),
    (LOG_APPROVE, '批准借阅'),
    (LOG_REJECT, '驳回借阅'),
    (LOG_DENY, '拒绝访问'),
)


class AccessLog(models.Model):
    """受控资料访问审计：append-only。"""

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='账号', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='party_access_logs')
    account_id_text = models.CharField('账号标识', max_length=32, blank=True, default='')
    document = models.ForeignKey(
        PartyDocument, verbose_name='资料', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='access_logs')
    action = models.CharField('动作', max_length=16, choices=LOG_ACTIONS)
    purpose = models.CharField('用途/说明', max_length=200, blank=True, default='')
    ip = models.CharField('来源 IP', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '资料访问审计'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['document', '-created_at']),
        ]

    def __str__(self):
        return '{} {}'.format(self.get_action_display(), self.created_at)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('访问审计为 append-only，不允许修改')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('访问审计为 append-only，不允许删除')
