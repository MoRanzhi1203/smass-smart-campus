"""路径 B 的最小可行性实验（**仅隔离库**，不进入正式配置）。

目的：回答 ADR 中的关键问题——"自定义 AUTH_USER_MODEL 在本项目是否可行"。
做法：在一个**全新的空库**上，用 ``AbstractBaseUser + PermissionsMixin`` 定义
唯一用户模型，并直接设 ``AUTH_USER_MODEL``，验证：

1. 从零 migrate 是否顺利（没有任何既有 auth 迁移包袱）；
2. 创建用户 / 超级用户是否正常；
3. ``PermissionsMixin`` 提供的 ``has_perm`` 是否可用；
4. Django admin 能否登录。

**重要边界**：本实验刻意**不安装 ``app01``**，因此它是"全新项目"场景，
不能直接等同于"给现有 4 个迁移的项目中途切换 AUTH_USER_MODEL"。
后者才是真正的风险所在——ADR 已据此判定 B 风险高。
"""
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class ProtoUserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, login_name, password=None, **extra_fields):
        if not login_name:
            raise ValueError('login_name 不能为空')
        user = self.model(login_name=login_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, login_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('超级用户必须 is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('超级用户必须 is_superuser=True')

        return self.create_user(login_name, password, **extra_fields)


class ProtoUser(AbstractBaseUser, PermissionsMixin):
    """路径 B 的代表性实现：单一用户模型 + 权限混入。"""

    PERSON_TYPES = (
        ('admin', '管理员'),
        ('teacher', '教师'),
        ('student', '学生'),
    )

    login_name = models.CharField('登录名', max_length=32, unique=True)
    display_name = models.CharField('显示名', max_length=32, blank=True, default='')
    person_type = models.CharField('人员类型', max_length=16, choices=PERSON_TYPES)

    is_active = models.BooleanField('可用', default=True)
    is_staff = models.BooleanField('可进管理后台', default=False)
    date_joined = models.DateTimeField('注册时间', auto_now_add=True)

    objects = ProtoUserManager()

    USERNAME_FIELD = 'login_name'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = '原型用户（路径 B）'

    def __str__(self):
        return '{} ({})'.format(self.login_name, self.person_type)
