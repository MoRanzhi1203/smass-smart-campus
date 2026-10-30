"""R20：多角色统一门户（隔离模块）。

设计约定
--------
1. 门户内容由"区块 + 链接 + 公告"三类数据驱动，管理员可配置；
2. 可见性按角色：``roles`` 是逗号分隔的角色码，空角色账号看不到任何区块；
3. 链接目标优先用 Django ``reverse(url_name)``，失败回退 ``fallback_url``，
   因此门户不强依赖其他模块是否在同一 URLConf 中加载；
4. 默认门户用 ``bootstrap_defaults`` 幂等初始化（学生/教师/管理人员三套入口）。
"""
from __future__ import annotations

from django.db import models

#: 角色码（与 r21_account.RoleCode 对齐，避免跨 app 直接依赖）
ROLE_STUDENT = 'student'
ROLE_TEACHER = 'teacher'
ROLE_COLLEGE_ADMIN = 'college_admin'
ROLE_SYSTEM_ADMIN = 'system_admin'
ROLE_CHOICES = (
    (ROLE_STUDENT, '学生'),
    (ROLE_TEACHER, '教师/辅导员'),
    (ROLE_COLLEGE_ADMIN, '学院管理员'),
    (ROLE_SYSTEM_ADMIN, '系统管理员'),
)
ALL_ROLES = ','.join(code for code, _label in ROLE_CHOICES)


class PortalSection(models.Model):
    code = models.CharField('编码', max_length=64, unique=True)
    title = models.CharField('标题', max_length=64)
    subtitle = models.CharField('副标题', max_length=120, blank=True, default='')
    roles = models.CharField('可见角色（逗号分隔）', max_length=120,
                             default=ALL_ROLES,
                             help_text='student,teacher,college_admin,system_admin')
    sort_order = models.IntegerField('排序', default=0)
    enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '门户区块'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'code']
        indexes = [models.Index(fields=['enabled', 'sort_order'])]

    def __str__(self):
        return '{} {}'.format(self.code, self.title)


class PortalLink(models.Model):
    section = models.ForeignKey(
        PortalSection, verbose_name='区块', on_delete=models.CASCADE,
        related_name='links')
    label = models.CharField('链接文字', max_length=64)
    url_name = models.CharField('Django URL 名', max_length=120, blank=True, default='')
    fallback_url = models.CharField('备用地址', max_length=200, blank=True, default='')
    roles = models.CharField('可见角色（逗号分隔）', max_length=120,
                             default=ALL_ROLES)
    sort_order = models.IntegerField('排序', default=0)
    enabled = models.BooleanField('启用', default=True)

    class Meta:
        verbose_name = '门户链接'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [models.Index(fields=['section', 'enabled', 'sort_order'])]

    def __str__(self):
        return self.label


NOTICE_DRAFT = 'draft'
NOTICE_PUBLISHED = 'published'
NOTICE_STATUS = (
    (NOTICE_DRAFT, '草稿'),
    (NOTICE_PUBLISHED, '已发布'),
)


class PortalNotice(models.Model):
    title = models.CharField('标题', max_length=120)
    body = models.CharField('内容', max_length=1000)
    roles = models.CharField('可见角色（逗号分隔）', max_length=120,
                             default=ALL_ROLES)
    status = models.CharField('状态', max_length=16, choices=NOTICE_STATUS,
                              default=NOTICE_DRAFT)
    created_by = models.CharField('创建人', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)

    class Meta:
        verbose_name = '门户公告'
        verbose_name_plural = verbose_name
        ordering = ['-published_at', '-created_at']
        indexes = [models.Index(fields=['status', '-published_at'])]

    def __str__(self):
        return self.title
