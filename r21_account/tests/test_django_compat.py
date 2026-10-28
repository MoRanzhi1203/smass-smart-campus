"""G1-A：AccountBackend 与 Django 认证体系的兼容性审计。

不是"能登录就算兼容"。本文件逐个验证 Django 依赖 `AUTH_USER_MODEL` 或
`request.user` 契约的组件，找出路径 A（继续自定义 Backend、不改
`AUTH_USER_MODEL`）的真实边界。

已验证过的（R2.1，不重复）：login/logout、request.user 类型、session hash、
has_perm、角色→Group。

本文件新增验证：
1. `ModelBackend` 继承来的 `has_module_perms` / `get_all_permissions` 是否可用；
2. `get_user_model()` 仍指向 `auth.User`（说明 Django 组件仍认旧模型）；
3. **`django_admin_log` 外键**：以 Account 的 pk 写 admin 日志会发生什么；
4. `AuthenticationForm`（Django 自带登录表单）能否配合 Account；
5. `Permission`/`Group` 在 `auth.User` 与 `Account` 之间是否串用。
"""
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase

from r21_account.models import Account, RoleCode
from r21_account.services import ensure_role_groups, grant_role

PASSWORD = 'Compat#2024'


def make_account(login_name='C900001', person_type='teacher'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name='兼容测试', person_type=person_type
    )
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    return account


class ModelBackendSurfaceTests(TestCase):
    """ModelBackend 的其余方法对 Account 是否成立。"""

    def setUp(self):
        ensure_role_groups()
        self.account = make_account('C900001')
        grant_role(self.account, RoleCode.TEACHER, granted_by='compat')
        self.account = Account.objects.get(pk=self.account.pk)

    def test_has_module_perms(self):
        self.assertTrue(self.account.has_module_perms('r21_account'))

    def test_get_all_permissions_returns_codenames(self):
        perms = self.account.get_all_permissions()
        self.assertIn('r21_account.view_data', perms)

    def test_get_group_permissions(self):
        groups = list(self.account.groups.values_list('name', flat=True))
        self.assertIn('r21_teacher', groups)


class DefaultUserModelTests(TestCase):
    """确认 AUTH_USER_MODEL 未被改动，Django 组件仍指向 auth.User。"""

    def test_get_user_model_is_auth_user(self):
        model = get_user_model()
        self.assertEqual(model._meta.app_label, 'auth')
        self.assertEqual(model._meta.model_name, 'user')

    def test_account_is_not_default_user_model(self):
        self.assertNotEqual(Account._meta.label_lower, get_user_model()._meta.label_lower)


class AdminLogEntryForeignKeyTests(TestCase):
    """路径 A 的关键边界：django_admin_log.user_id 指向 auth_user。

    Django admin 在每次增删改时调用 ``LogEntry.objects.log_action(user_id=request.user.pk, ...)``。
    若 ``request.user`` 是 ``Account``，写入的 user_id 会去校验 ``auth_user(id)``。
    """

    def test_admin_log_entry_with_account_pk(self):
        account = make_account('C900002')
        content_type = ContentType.objects.get_for_model(Account)

        try:
            with transaction.atomic():
                LogEntry.objects.log_action(
                    user_id=account.pk,
                    content_type_id=content_type.pk,
                    object_id='1',
                    object_repr='compat probe',
                    action_flag=ADDITION,
                    change_message='probe',
                )
            wrote = True
            error = None
        except IntegrityError as exc:
            wrote = False
            error = exc

        # 记录事实，而不是假设：无论成功失败都输出，供报告引用
        print('ADMIN_LOG_PROBE account_pk={} wrote={} error={}'.format(
            account.pk, wrote, type(error).__name__ if error else None
        ))

        if wrote:
            # 若写成功，说明 auth_user 中存在同 id 行（测试库里不应发生）→ 记录歧义风险
            entry = LogEntry.objects.latest('id')
            self.assertEqual(entry.user_id, account.pk)
        else:
            self.assertIsInstance(error, IntegrityError)

    def test_admin_log_without_matching_auth_user_is_rejected(self):
        """确认 auth_user 为空时写日志会失败（证明 FK 指向 auth_user）。"""
        account = make_account('C900003')
        content_type = ContentType.objects.get_for_model(Account)
        user_model = get_user_model()

        self.assertFalse(user_model.objects.filter(pk=account.pk).exists())

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LogEntry.objects.log_action(
                    user_id=account.pk,
                    content_type_id=content_type.pk,
                    object_id='1',
                    object_repr='probe2',
                    action_flag=ADDITION,
                    change_message='probe2',
                )


class AuthenticationFormTests(TestCase):
    """Django 自带登录表单能否配合 Account。"""

    def setUp(self):
        self.account = make_account('C900004')

    def test_authentication_form_accepts_account(self):
        form = AuthenticationForm(
            data={'username': 'C900004', 'password': PASSWORD}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsInstance(form.get_user(), Account)

    def test_authentication_form_rejects_wrong_password(self):
        form = AuthenticationForm(
            data={'username': 'C900004', 'password': 'wrong'}
        )
        self.assertFalse(form.is_valid())


class PermissionIsolationTests(TestCase):
    """auth.User 与 Account 的权限/组是否互相串用。"""

    def setUp(self):
        ensure_role_groups()
        self.account = make_account('C900005')
        grant_role(self.account, RoleCode.TEACHER, granted_by='compat')
        self.account = Account.objects.get(pk=self.account.pk)

    def test_auth_user_has_no_account_permissions(self):
        user_model = get_user_model()
        legacy_user = user_model.objects.create_user(
            username='legacy_probe', password='Legacy#2024'
        )
        self.assertFalse(legacy_user.has_perm('r21_account.view_data'))

    def test_account_groups_do_not_attach_to_auth_user(self):
        user_model = get_user_model()
        legacy_user = user_model.objects.create_user(
            username='legacy_probe2', password='Legacy#2024'
        )
        teacher_group = Group.objects.get(name='r21_teacher')

        self.assertNotIn(teacher_group, legacy_user.groups.all())
        self.assertIn(teacher_group, self.account.groups.all())

    def test_permission_rows_are_shared_table(self):
        """两个模型共用 auth_permission 表（同一个 content_type 绑定 Account）。"""
        content_type = ContentType.objects.get_for_model(Account)
        perm = Permission.objects.get(
            content_type=content_type, codename='view_data'
        )
        self.assertEqual(perm.content_type, content_type)
