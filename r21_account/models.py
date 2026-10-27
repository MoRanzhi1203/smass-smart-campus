"""R2.1 统一账号与 RBAC 原型（**仅隔离库** ``smass_r21_proto``）。

与 R2.0 的 ``proto_account`` 的关系：
- ``proto_account`` 是「独立业务 Account + 自定义 Backend」的最简验证（路径 A 雏形），
  它**没有**继承 ``AbstractBaseUser``，因此无法直接复用 Django 的 ``login()`` /
  ``get_session_auth_hash()`` 等契约；
- 本模块是 R2.1 的正式原型：``Account(AbstractBaseUser, PermissionsMixin)``，
  从而可以用**标准 Django 认证机制**（不做任何 ``request.user`` 的 hack），
  并具备 ``has_perm`` / ``Group`` / ``Permission`` 能力；
- 旧表 ``app01.Admin/Student/Teacher`` **一行不改**，通过 ``LegacyAccountLink``
  建立可追溯映射。

明确边界（计划 §3 末段）：正式 ``smass`` 库的账号读写路径**未切换**，
``AUTH_USER_MODEL`` **未修改**（本 app 只被 ``smass/settings_r21.py`` 加载）。
"""
import hashlib

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    Group,
    Permission,
    PermissionsMixin,
)
from django.db import models


class PersonType(models.TextChoices):
    ADMIN = 'admin', '管理员'
    TEACHER = 'teacher', '教师'
    STUDENT = 'student', '学生'


class RoleCode(models.TextChoices):
    """角色编码（与权限矩阵一一对应）。"""

    SYSTEM_ADMIN = 'system_admin', '系统管理员'
    COLLEGE_ADMIN = 'college_admin', '学院管理员'
    TEACHER = 'teacher', '辅导员/教师'
    STUDENT = 'student', '学生'


class RoleName(models.TextChoices):
    """Django Group 名称（角色到权限的桥接载体）。"""

    SYSTEM_ADMIN = 'r21_system_admin', '系统管理员'
    COLLEGE_ADMIN = 'r21_college_admin', '学院管理员'
    TEACHER = 'r21_teacher', '教师'
    STUDENT = 'r21_student', '学生'


ROLE_TO_GROUP = {
    RoleCode.SYSTEM_ADMIN: RoleName.SYSTEM_ADMIN,
    RoleCode.COLLEGE_ADMIN: RoleName.COLLEGE_ADMIN,
    RoleCode.TEACHER: RoleName.TEACHER,
    RoleCode.STUDENT: RoleName.STUDENT,
}


class AccountManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, login_name, password=None, **extra_fields):
        if not login_name:
            raise ValueError('login_name 不能为空')
        account = self.model(login_name=login_name, **extra_fields)
        account.set_password(password)
        account.save(using=self._db)
        return account

    def create_superuser(self, login_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('person_type', PersonType.ADMIN)
        extra_fields.setdefault('must_change_password', False)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('超级用户必须 is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('超级用户必须 is_superuser=True')

        return self.create_user(login_name, password, **extra_fields)


class Account(AbstractBaseUser, PermissionsMixin):
    """统一认证主体（唯一登录凭证持有者）。

    继承 ``AbstractBaseUser`` 是为了**直接满足 Django 的认证契约**：
    ``password`` / ``last_login`` / ``get_session_auth_hash()`` / ``set_password()``
    都由基类或本类提供，因此 ``django.contrib.auth.login()`` 与
    ``AuthenticationMiddleware`` 无需任何定制即可工作。
    """

    login_name = models.CharField('登录名', max_length=32, unique=True)
    display_name = models.CharField('显示名', max_length=32)
    person_type = models.CharField(
        '人员类型', max_length=16, choices=PersonType.choices
    )

    is_active = models.BooleanField('账号可用', default=True)
    is_staff = models.BooleanField('可进管理后台', default=False)

    must_change_password = models.BooleanField('需强制改密', default=True)
    password_changed_at = models.DateTimeField('密码变更时间', null=True, blank=True)

    # 对象级授权范围（学院管理员/辅导员用；系统管理员为空表示全局）
    scope_college = models.CharField(
        '授权学院', max_length=100, blank=True, default=''
    )

    # 停用审计
    deactivated_at = models.DateTimeField('停用时间', null=True, blank=True)
    deactivated_reason = models.CharField(
        '停用原因', max_length=64, blank=True, default=''
    )

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    # ------------------------------------------------------------------
    # 覆盖 PermissionsMixin 的两个 M2M，原因（G1 实测发现）：
    # `PermissionsMixin.groups` / `user_permissions` 的默认反向名为 `user_set`，
    # 而默认 `auth.User` 已占用该名字，两套用户模型共存时会报
    # `fields.E304 Reverse accessor ... clashes`。
    # 指定独立 related_name 是"共存"的标准做法，也说明 A 路径并非零成本。
    # ------------------------------------------------------------------
    groups = models.ManyToManyField(
        Group,
        verbose_name='角色组',
        blank=True,
        related_name='r21_accounts',
        related_query_name='r21_account',
        help_text='由 AccountRole 同步而来，承载 Django Permission。',
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='附加权限',
        blank=True,
        related_name='r21_accounts',
        related_query_name='r21_account',
    )

    objects = AccountManager()

    USERNAME_FIELD = 'login_name'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'R2.1 统一账号'
        indexes = [
            models.Index(fields=['person_type', 'is_active']),
            models.Index(fields=['scope_college']),
        ]

    def __str__(self):
        return '{} ({})'.format(self.login_name, self.person_type)

    # ------------------------------------------------------------------
    def get_session_auth_hash(self):
        """与 ``AbstractBaseUser`` 保持一致的会话哈希（密码变更即失效）。"""
        return hashlib.sha256(
            '{}:{}'.format(self.password, self.pk).encode('utf-8')
        ).hexdigest()

    def set_password(self, raw_password):
        super().set_password(raw_password)
        from django.utils import timezone

        self.password_changed_at = timezone.now()
        # 首次设置密码后不再强制改密（由服务层在"临时口令"场景下重新置 True）
        self.must_change_password = False

    def has_role(self, role_code):
        return self.roles.filter(role=role_code, revoked_at__isnull=True).exists()

    def active_roles(self):
        return list(
            self.roles.filter(revoked_at__isnull=True).values_list('role', flat=True)
        )


class AccountRole(models.Model):
    """角色授予记录（含撤销审计，不物理删除）。"""

    account = models.ForeignKey(
        Account, verbose_name='账号', on_delete=models.CASCADE, related_name='roles'
    )
    role = models.CharField('角色', max_length=32, choices=RoleCode.choices)
    granted_at = models.DateTimeField('授予时间', auto_now_add=True)
    granted_by = models.CharField('授予人', max_length=32, blank=True, default='')
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)
    revoked_by = models.CharField('撤销人', max_length=32, blank=True, default='')

    class Meta:
        verbose_name = '角色授予'
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'role'],
                condition=models.Q(revoked_at__isnull=True),
                name='r21_uniq_active_role',
            ),
        ]
        indexes = [models.Index(fields=['account', 'revoked_at'])]

    def __str__(self):
        return '{} -> {}'.format(self.account.login_name, self.role)


class LegacyAccountLink(models.Model):
    """旧表 → 统一账号的唯一映射（可追溯、可回滚）。"""

    account = models.OneToOneField(
        Account, verbose_name='账号', on_delete=models.CASCADE, related_name='legacy_link'
    )
    source_table = models.CharField('来源表', max_length=32)
    source_pk = models.CharField('来源主键', max_length=32)
    backfilled_at = models.DateTimeField('回填时间', auto_now_add=True)
    checksum = models.CharField(
        '密码哈希指纹（不可逆）', max_length=32, blank=True, default=''
    )

    class Meta:
        verbose_name = '旧账号映射'
        constraints = [
            models.UniqueConstraint(
                fields=['source_table', 'source_pk'], name='r21_uniq_legacy_origin'
            ),
        ]
        indexes = [models.Index(fields=['source_table', 'source_pk'])]

    def __str__(self):
        return '{}/{} -> {}'.format(
            self.source_table, self.source_pk, self.account.login_name
        )


class StudentProfile(models.Model):
    account = models.OneToOneField(
        Account,
        verbose_name='账号',
        on_delete=models.CASCADE,
        related_name='student_profile',
    )
    student_no = models.CharField('学号', max_length=10, unique=True)
    name = models.CharField('姓名', max_length=16)
    college_name = models.CharField('学院', max_length=100, blank=True, default='')
    classes_name = models.CharField('班级', max_length=100, blank=True, default='')
    phone = models.CharField('手机号', max_length=11, blank=True, default='')
    card_id = models.CharField('身份证号', max_length=18, blank=True, default='')

    class Meta:
        verbose_name = '学生档案'

    def __str__(self):
        return '{} {}'.format(self.student_no, self.name)


class TeacherProfile(models.Model):
    account = models.OneToOneField(
        Account,
        verbose_name='账号',
        on_delete=models.CASCADE,
        related_name='teacher_profile',
    )
    teacher_no = models.CharField('工号', max_length=7, unique=True)
    name = models.CharField('姓名', max_length=16)
    college_name = models.CharField('学院', max_length=100, blank=True, default='')
    phone = models.CharField('手机号', max_length=11, blank=True, default='')

    class Meta:
        verbose_name = '教师档案'

    def __str__(self):
        return '{} {}'.format(self.teacher_no, self.name)


class AccountAuditLog(models.Model):
    """账号域审计（角色变更、停用、密码重置、强制改密等）。"""

    ACTIONS = (
        ('create', '创建账号'),
        ('backfill', '回填账号'),
        ('login', '登录'),
        ('login_failed', '登录失败'),
        ('login_locked', '登录锁定'),
        ('password_change', '修改密码'),
        ('password_reset', '重置密码'),
        ('role_grant', '授予角色'),
        ('role_revoke', '撤销角色'),
        ('deactivate', '停用账号'),
        ('activate', '启用账号'),
        ('must_change', '要求强制改密'),
        ('dangerous_blocked', '高危操作被拒'),
    )

    action = models.CharField('动作', max_length=32, choices=ACTIONS)
    actor = models.CharField('操作者', max_length=32, blank=True, default='')
    target = models.CharField('目标账号', max_length=32, blank=True, default='')
    detail = models.CharField('说明', max_length=255, blank=True, default='')
    ip = models.CharField('来源 IP', max_length=45, blank=True, default='')
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '账号审计'
        indexes = [models.Index(fields=['action', 'created_at'])]

    def __str__(self):
        return '{} {} {}'.format(self.created_at, self.action, self.target)


class LoginAttempt(models.Model):
    """持久化登录限速记录（跨会话有效）。

    设计要点（计划 G4）：
    - 按 ``(login_name, ip)`` 组合计数，避免"恶意锁定他人账号"（攻击者换 IP 才计数）；
    - 同时在账号维度设更高阈值，防止分布式撞库；
    - 记录过期由时间窗查询实现（不依赖定时清理）。
    """

    login_name = models.CharField('登录名', max_length=32)
    ip = models.CharField('来源 IP', max_length=45, blank=True, default='')
    success = models.BooleanField('是否成功', default=False)
    created_at = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = '登录尝试'
        indexes = [
            models.Index(fields=['login_name', 'ip', 'created_at']),
            models.Index(fields=['login_name', 'created_at']),
        ]

    def __str__(self):
        return '{} {} {}'.format(self.login_name, self.ip, self.success)
