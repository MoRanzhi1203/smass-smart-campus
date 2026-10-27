"""R2.1 认证后端。

关键点（计划 G1 第 1 条，必须实测而非假设）：
设置 ``AUTHENTICATION_BACKENDS`` 并让 backend 返回 **非** ``AUTH_USER_MODEL``
的 ``Account`` 实例，是否能让 ``request.user`` 变成该 Account？

本 backend 继承 ``ModelBackend``：
- ``authenticate`` 用 ``Account`` 查库并校验密码；
- ``get_user`` 按主键返回 ``Account``；
- 继承来的 ``has_perm`` / ``has_module_perms`` 依赖 ``PermissionsMixin`` 提供的
  ``groups`` / ``user_permissions``，因此权限能力与标准用户一致。

是否真的可用，由 ``r21_account/tests/test_auth_integration.py`` 实证。
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class AccountBackend(ModelBackend):
    """以统一 Account 作为认证主体的后端。"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        from .models import Account

        login_name = username or kwargs.get('login_name')
        if not login_name or password is None:
            return None

        account = Account.objects.filter(login_name=login_name).first()
        if account is None:
            # 与"密码错误"返回同样的 None，避免账号枚举
            return None

        if account.check_password(password) and self.user_can_authenticate(account):
            return account
        return None

    def get_user(self, user_id):
        from .models import Account

        try:
            return Account.objects.get(pk=user_id)
        except Account.DoesNotExist:
            return None


def default_user_model_is_swapped():
    """辅助判断：当前是否真的把 AUTH_USER_MODEL 换成了 Account。"""
    return get_user_model()._meta.app_label == 'r21_account'
