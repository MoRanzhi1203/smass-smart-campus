"""G3 审计模型：与 ``django_admin_log`` 完全分离。

为什么不复用 ``r21_account.AccountAuditLog``：
- 该表是 R2.1 已验收的迁移产物，本轮不修改 R2.1 原型；
- G3 需要 ``outcome`` / ``request_id``（请求关联）/ ``actor_kind`` 三个新语义；
- 独立表可单独回滚，不影响 R2.1。

为什么不用 ``django_admin_log``（L1）：
- 其 ``user_id`` 外键指向 ``auth_user``，写入 ``Account.pk`` 会违反外键；
- 两表 pk 都是自增整数，**同号时会把日志记到错误的人名下**——这是数据完整性问题，
  不是配置问题。
"""
from django.db import models

OUTCOME_SUCCESS = 'success'
OUTCOME_DENIED = 'denied'
OUTCOME_ERROR = 'error'

OUTCOME_CHOICES = (
    (OUTCOME_SUCCESS, '成功'),
    (OUTCOME_DENIED, '被拒'),
    (OUTCOME_ERROR, '异常'),
)

ACTOR_KIND_ACCOUNT = 'account'
ACTOR_KIND_LEGACY = 'legacy'
ACTOR_KIND_SYSTEM = 'system'
ACTOR_KIND_UNKNOWN = 'unknown'

ACTOR_KIND_CHOICES = (
    (ACTOR_KIND_ACCOUNT, '统一账号'),
    (ACTOR_KIND_LEGACY, '旧身份'),
    (ACTOR_KIND_SYSTEM, '系统'),
    (ACTOR_KIND_UNKNOWN, '未知'),
)


class AccountAuditEvent(models.Model):
    action = models.CharField('动作', max_length=48)
    outcome = models.CharField('结果', max_length=16, choices=OUTCOME_CHOICES)

    actor_kind = models.CharField(
        '操作者类型', max_length=16, choices=ACTOR_KIND_CHOICES, default=ACTOR_KIND_UNKNOWN
    )
    # 允许为空：表示"未知/无操作者"，**不伪造** auth_user 记录
    actor_login = models.CharField('操作者登录名', max_length=32, blank=True, default='')

    target = models.CharField('目标类型', max_length=32, blank=True, default='')
    target_id = models.CharField('目标标识', max_length=64, blank=True, default='')

    # 已脱敏的上下文（JSON），禁止写入密码/哈希/令牌/会话
    context = models.JSONField('上下文', default=dict, blank=True)

    ip = models.CharField('来源 IP', max_length=45, blank=True, default='')
    request_id = models.CharField('请求关联 ID', max_length=36, blank=True, default='')

    # ---- H1：批次追溯（append-only，回滚不删除历史）----
    batch_id = models.CharField('批次 ID', max_length=36, blank=True, default='', db_index=True)
    operation = models.CharField('批次操作', max_length=16, blank=True, default='')
    source_batch_id = models.CharField(
        '来源批次 ID', max_length=36, blank=True, default='',
        help_text='回滚事件指向被回滚的回填批次，保证因果可追溯',
    )
    counts = models.JSONField('脱敏计数', default=dict, blank=True)

    created_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'R2.2 账号审计事件'
        indexes = [
            models.Index(fields=['action', 'outcome', 'created_at']),
            models.Index(fields=['actor_login', 'created_at']),
            models.Index(fields=['batch_id', 'created_at']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.created_at, self.action, self.outcome)
