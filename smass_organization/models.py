"""R4：组织机构与学生档案中心（隔离模块，正式 app01 不动）。

核心设计（对应计划 D03/D04/D11）：
- ``OrganizationUnit`` 是树形结构，**防环 + 父子类型受控**在服务层与数据库约束双重保证；
- ``StudentRecord`` 是学籍档案，与 ``r21_account.Account`` 通过 FK 关联，
  **不新造密码源**（D02/D11）；
- 变更走 ``StudentRecordChange`` 追加历史，不原地覆盖；
- 敏感字段可见性由 ``StudentFieldDefinition`` 配置（B 类可配置，D05）。
"""
import uuid

from django.db import models
from django.db.models import Q

# ---------------------------------------------------------------------------
# 组织
# ---------------------------------------------------------------------------
UNIT_TYPE_COLLEGE = 'college'
UNIT_TYPE_MAJOR = 'major'
UNIT_TYPE_GRADE = 'grade'
UNIT_TYPE_CLASS = 'class'
UNIT_TYPE_DEPARTMENT = 'department'

UNIT_TYPES = (
    (UNIT_TYPE_COLLEGE, '学院'),
    (UNIT_TYPE_MAJOR, '专业'),
    (UNIT_TYPE_GRADE, '年级'),
    (UNIT_TYPE_CLASS, '班级'),
    (UNIT_TYPE_DEPARTMENT, '部门'),
)

#: 允许的父子类型关系（D04：防非法层级）
ALLOWED_CHILDREN = {
    None: {UNIT_TYPE_COLLEGE, UNIT_TYPE_DEPARTMENT},
    UNIT_TYPE_COLLEGE: {UNIT_TYPE_MAJOR, UNIT_TYPE_GRADE, UNIT_TYPE_DEPARTMENT},
    UNIT_TYPE_MAJOR: {UNIT_TYPE_CLASS},
    UNIT_TYPE_GRADE: {UNIT_TYPE_CLASS},
    UNIT_TYPE_CLASS: set(),
    UNIT_TYPE_DEPARTMENT: {UNIT_TYPE_DEPARTMENT},
}

STATUS_ACTIVE = 'active'
STATUS_INACTIVE = 'inactive'


class OrganizationUnit(models.Model):
    code = models.CharField('编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=100)
    unit_type = models.CharField('类型', max_length=16, choices=UNIT_TYPES)
    parent = models.ForeignKey(
        'self', verbose_name='上级', null=True, blank=True,
        on_delete=models.PROTECT, related_name='children',
    )
    status = models.CharField('状态', max_length=16, default=STATUS_ACTIVE)
    sort_order = models.IntegerField('排序', default=0)

    valid_from = models.DateField('生效日期', null=True, blank=True)
    valid_to = models.DateField('失效日期', null=True, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '组织单元'
        indexes = [
            models.Index(fields=['unit_type', 'status']),
            models.Index(fields=['parent', 'sort_order']),
        ]

    def __str__(self):
        return '{} {}'.format(self.code, self.name)

    def ancestors(self):
        """返回祖先链（含自身），带防御性深度上限。"""
        chain = []
        node = self
        guard = 0
        while node is not None and guard < 64:
            chain.append(node)
            node = node.parent
            guard += 1
        return chain


class OrganizationMembership(models.Model):
    """人员与组织的从属关系（可多归属，保留历史）。"""

    account = models.ForeignKey(
        'r21_account.Account', verbose_name='账号',
        on_delete=models.CASCADE, related_name='org_memberships',
    )
    unit = models.ForeignKey(
        OrganizationUnit, verbose_name='组织',
        on_delete=models.CASCADE, related_name='memberships',
    )
    role = models.CharField('在组织中的角色', max_length=32, blank=True, default='')
    started_at = models.DateField('开始日期', null=True, blank=True)
    ended_at = models.DateField('结束日期', null=True, blank=True)

    class Meta:
        verbose_name = '组织成员关系'
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'unit'],
                condition=Q(ended_at__isnull=True),
                name='r4_uniq_active_membership',
            ),
        ]
        indexes = [models.Index(fields=['unit', 'ended_at'])]


# ---------------------------------------------------------------------------
# 学籍档案
# ---------------------------------------------------------------------------
STUDENT_STATUS = (
    ('enrolled', '在读'),
    ('suspended', '休学'),
    ('graduated', '毕业'),
    ('withdrawn', '退学'),
)


class StudentRecord(models.Model):
    student_no = models.CharField('学号', max_length=20, unique=True)
    name = models.CharField('姓名', max_length=32)
    account = models.ForeignKey(
        'r21_account.Account', verbose_name='关联账号',
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name='student_records',
    )
    unit = models.ForeignKey(
        OrganizationUnit, verbose_name='所属组织',
        null=True, blank=True, on_delete=models.PROTECT,
        related_name='students',
    )
    status = models.CharField('学籍状态', max_length=16, choices=STUDENT_STATUS,
                              default='enrolled')
    enrolled_at = models.DateField('入学日期', null=True, blank=True)

    # 扩展字段值（字段字典驱动，B 类配置）
    extra = models.JSONField('扩展字段', default=dict, blank=True)

    version = models.IntegerField('版本号（乐观锁）', default=1)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '学籍档案'
        indexes = [
            models.Index(fields=['unit', 'status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return '{} {}'.format(self.student_no, self.name)


class StudentRecordChange(models.Model):
    """档案变更历史（append-only）。"""

    record = models.ForeignKey(
        StudentRecord, verbose_name='档案',
        on_delete=models.CASCADE, related_name='changes',
    )
    field_name = models.CharField('字段', max_length=64)
    old_value = models.CharField('原值', max_length=255, blank=True, default='')
    new_value = models.CharField('新值', max_length=255, blank=True, default='')
    reason = models.CharField('原因', max_length=255, blank=True, default='')
    changed_by = models.CharField('操作者', max_length=32, blank=True, default='')
    batch_id = models.CharField('批次', max_length=36, blank=True, default='')
    changed_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '档案变更'
        indexes = [models.Index(fields=['record', 'changed_at'])]


class StudentFieldDefinition(models.Model):
    """字段字典（B 类可配置）：定义字段类型与可见/可编辑角色。"""

    DATA_TYPES = (
        ('string', '文本'),
        ('int', '整数'),
        ('date', '日期'),
        ('bool', '布尔'),
    )

    code = models.CharField('字段编码', max_length=64, unique=True)
    label = models.CharField('显示名', max_length=100)
    data_type = models.CharField('类型', max_length=16, choices=DATA_TYPES,
                                 default='string')
    required = models.BooleanField('必填', default=False)
    is_sensitive = models.BooleanField('敏感字段', default=False)
    visible_roles = models.JSONField('可见角色', default=list, blank=True)
    editable_roles = models.JSONField('可编辑角色', default=list, blank=True)
    sort_order = models.IntegerField('排序', default=0)
    active = models.BooleanField('启用', default=True)

    class Meta:
        verbose_name = '学生字段定义'
        indexes = [models.Index(fields=['active', 'sort_order'])]

    def __str__(self):
        return '{} ({})'.format(self.code, self.label)


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------
IMPORT_PENDING = 'pending'
IMPORT_PREVIEWED = 'previewed'
IMPORT_COMMITTED = 'committed'
IMPORT_FAILED = 'failed'

IMPORT_STATUS = (
    (IMPORT_PENDING, '待处理'),
    (IMPORT_PREVIEWED, '已预检'),
    (IMPORT_COMMITTED, '已提交'),
    (IMPORT_FAILED, '失败'),
)


class DataImportJob(models.Model):
    batch_id = models.UUIDField('批次', default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField('类型', max_length=32, default='student_record')
    status = models.CharField('状态', max_length=16, choices=IMPORT_STATUS,
                              default=IMPORT_PENDING)
    total_rows = models.IntegerField('总行数', default=0)
    success_rows = models.IntegerField('成功行数', default=0)
    error_rows = models.IntegerField('错误行数', default=0)
    created_by = models.CharField('创建者', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    committed_at = models.DateTimeField('提交时间', null=True, blank=True)

    class Meta:
        verbose_name = '导入批次'
        indexes = [models.Index(fields=['status', 'created_at'])]


class DataImportRowError(models.Model):
    job = models.ForeignKey(DataImportJob, verbose_name='批次',
                            on_delete=models.CASCADE, related_name='errors')
    row_number = models.IntegerField('行号')
    column = models.CharField('列', max_length=64, blank=True, default='')
    error_code = models.CharField('错误码', max_length=32)
    message = models.CharField('说明', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = '导入错误行'
        indexes = [models.Index(fields=['job', 'row_number'])]
