"""R2.0 统一账号原型（**隔离库专用**）。

为什么不放在 ``app01``：
- ``app01`` 的迁移链已经应用到开发库 ``smass``，把实验性模型塞进去会污染正式迁移历史；
- 本 app 只被 ``smass/settings_proto.py`` 加载，目标库固定为 ``smass_proto_account``；
- 正式 ``settings.py`` 不包含本 app，因此对现有 109 条测试与生产代码零影响。

设计要点（对应计划 §6.2）：
1. ``Account`` 是唯一认证主体，``login_name`` 承载学号/工号/管理员号（可能重名的场景
   由命名空间字段 ``person_type`` 区分，登录时按角色入口过滤）；
2. 一人可多角色（``AccountRole``），登录后激活角色由服务端决定；
3. ``legacy_source`` + ``legacy_pk`` 记录来源表与主键，用于回填可追溯与回滚删除；
4. 认证相关字段（``must_change_password`` / ``is_active`` / 限速字段）集中在此，
   为后续 R2.1 的强制改密与持久化限速打基础。
"""
from django.db import models


class Role(models.TextChoices):
    """角色枚举（用 TextChoices 便于与 AccountRole 冗余存储做一致性校验）。"""

    ADMIN = 'admin', '管理员'
    TEACHER = 'teacher', '教师'
    STUDENT = 'student', '学生'


class PersonType(models.TextChoices):
    """人员类型：决定该账号的业务档案挂在哪个 Profile。"""

    ADMIN = 'admin', '管理员'
    TEACHER = 'teacher', '教师'
    STUDENT = 'student', '学生'


class Account(models.Model):
    """统一认证主体。"""

    login_name = models.CharField('登录名', max_length=32, unique=True)
    password = models.CharField('密码哈希', max_length=128)
    display_name = models.CharField('显示名', max_length=32)
    person_type = models.CharField(
        '人员类型', max_length=16, choices=PersonType.choices
    )

    is_active = models.BooleanField('账号可用', default=True)
    must_change_password = models.BooleanField('需强制改密', default=True)
    password_changed_at = models.DateTimeField('密码变更时间', null=True, blank=True)
    last_login_at = models.DateTimeField('最后登录时间', null=True, blank=True)

    # 持久化登录限速（替代当前基于 Session 的临时实现）
    failed_attempts = models.PositiveSmallIntegerField('连续失败次数', default=0)
    locked_until = models.DateTimeField('锁定截止时间', null=True, blank=True)

    # 回填溯源：来自哪张旧表、哪个主键
    legacy_source = models.CharField('来源表', max_length=32, blank=True, default='')
    legacy_pk = models.CharField('来源主键', max_length=32, blank=True, default='')

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '统一账号'
        constraints = [
            models.UniqueConstraint(
                fields=['legacy_source', 'legacy_pk'],
                name='proto_uniq_legacy_origin',
            ),
        ]
        indexes = [
            models.Index(fields=['person_type', 'is_active']),
        ]

    def __str__(self):
        return '{} ({})'.format(self.login_name, self.person_type)


class AccountRole(models.Model):
    """账号与角色的多对多关系。"""

    account = models.ForeignKey(
        Account, verbose_name='账号', on_delete=models.CASCADE, related_name='roles'
    )
    role = models.CharField('角色', max_length=16, choices=Role.choices)
    granted_at = models.DateTimeField('授予时间', auto_now_add=True)
    note = models.CharField('备注', max_length=64, blank=True, default='')

    class Meta:
        verbose_name = '账号角色'
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'role'], name='proto_uniq_account_role'
            ),
        ]

    def __str__(self):
        return '{} -> {}'.format(self.account.login_name, self.role)


class StudentProfile(models.Model):
    """学生业务档案（与凭据分离）。"""

    account = models.OneToOneField(
        Account, verbose_name='账号', on_delete=models.CASCADE, related_name='student_profile'
    )
    student_no = models.CharField('学号', max_length=10)
    name = models.CharField('姓名', max_length=16)
    pinyin = models.CharField('拼音', max_length=32, null=True, blank=True)
    sex = models.SmallIntegerField('性别', null=True, blank=True)
    nation = models.CharField('民族', max_length=10, null=True, blank=True)
    card_id = models.CharField('身份证号', max_length=18, blank=True, default='')
    phone = models.CharField('手机号', max_length=11, null=True, blank=True)
    qq = models.CharField('QQ号', max_length=11, null=True, blank=True)
    address = models.CharField('详细地址', max_length=64, null=True, blank=True)
    classes_name = models.CharField('班级（原型阶段用名称）', max_length=100, blank=True, default='')
    political = models.SmallIntegerField('政治面貌', default=0)

    class Meta:
        verbose_name = '学生档案'
        constraints = [
            models.UniqueConstraint(fields=['student_no'], name='proto_uniq_student_no'),
        ]

    def __str__(self):
        return '{} {}'.format(self.student_no, self.name)


class TeacherProfile(models.Model):
    """教师业务档案。"""

    account = models.OneToOneField(
        Account, verbose_name='账号', on_delete=models.CASCADE, related_name='teacher_profile'
    )
    teacher_no = models.CharField('教职员工编号', max_length=7)
    name = models.CharField('姓名', max_length=16)
    pinyin = models.CharField('拼音', max_length=32, null=True, blank=True)
    sex = models.SmallIntegerField('性别', null=True, blank=True)
    nation = models.CharField('民族', max_length=10, null=True, blank=True)
    card_id = models.CharField('身份证号', max_length=18, blank=True, default='')
    phone = models.CharField('手机号', max_length=11, blank=True, default='')
    qq = models.CharField('QQ号', max_length=11, blank=True, default='')
    address = models.CharField('详细地址', max_length=64, blank=True, default='')
    entry_time = models.DateField('入职时间', null=True, blank=True)
    college_name = models.CharField('院系（原型阶段用名称）', max_length=100, blank=True, default='')
    political = models.SmallIntegerField('政治面貌', default=0)

    class Meta:
        verbose_name = '教师档案'
        constraints = [
            models.UniqueConstraint(fields=['teacher_no'], name='proto_uniq_teacher_no'),
        ]

    def __str__(self):
        return '{} {}'.format(self.teacher_no, self.name)
