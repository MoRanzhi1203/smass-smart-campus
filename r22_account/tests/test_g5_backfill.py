"""G5：回填演练的自动化验证（隔离测试库）。

覆盖：
- 目标库白名单（正式库被拒）
- dry-run / 实跑 / 幂等 / --since
- 密码哈希原样保留（只断言相等，不输出哈希）
- 故障注入：单行失败回滚、其余行继续
- 回滚范围：预存（非回填）账号存活
- 二次回填恢复
- 一致性校验的注入检测（JSON 模式）
"""
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from app01 import models as legacy
from r21_account.models import (
    Account,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
    TeacherProfile,
)

PASSWORD = 'InitPass#2024'


def run(*args):
    out = StringIO()
    call_command('backfill_accounts_r21', *args, stdout=out)
    return out.getvalue()


def verify_json(*extra):
    out = StringIO()
    call_command('verify_account_consistency', '--json', *extra, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


class G5Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.college = legacy.College.objects.create(name='信息工程学院')
        cls.grade = legacy.Grade.objects.create(name='2021级')
        cls.major = legacy.Major.objects.create(college=cls.college, name='信息安全技术')
        cls.classes = legacy.Classes.objects.create(
            name='信安2101', grade=cls.grade, major=cls.major
        )

        from django.contrib.auth.hashers import make_password

        hashed = make_password(PASSWORD)
        legacy.Admin.objects.create(id='001', name='管理员', password=hashed)
        legacy.Teacher.objects.create(
            id='T01', name='教师甲', password=hashed, pinyin='jsj', sex=0,
            nation=None, cardID='', phone='', qq='', address='',
            entry_time=None, college=cls.college, political=0,
        )
        legacy.Student.objects.create(
            id='S01', name='学生甲', password=hashed, pinyin='xsj', sex=0,
            nation=None, classes=cls.classes, cardID='', phone=None, qq=None,
            address=None, building=None, dormitory=None, political=0,
        )


class TargetGuardTests(TestCase):
    def test_formal_database_is_rejected(self):
        with patch.dict(connection.settings_dict, {'NAME': 'smass'}):
            with self.assertRaises(CommandError) as ctx:
                run()
        self.assertIn('拒绝', str(ctx.exception))

    def test_unknown_database_is_rejected(self):
        with patch.dict(connection.settings_dict, {'NAME': 'some_other_db'}):
            with self.assertRaises(CommandError):
                run()

    def test_consistency_command_rejects_formal_database(self):
        with patch.dict(connection.settings_dict, {'NAME': 'smass'}):
            out = StringIO()
            with self.assertRaises(CommandError):
                call_command('verify_account_consistency', stdout=out)


class BackfillFlowTests(G5Fixture):
    def test_dry_run_creates_nothing(self):
        text = run('--dry-run')

        self.assertIn('created=3', text)
        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(LegacyAccountLink.objects.count(), 0)

    def test_apply_creates_accounts_links_profiles(self):
        run()

        self.assertEqual(Account.objects.count(), 3)
        self.assertEqual(LegacyAccountLink.objects.count(), 3)
        self.assertEqual(StudentProfile.objects.count(), 1)
        self.assertEqual(TeacherProfile.objects.count(), 1)

        admin = Account.objects.get(login_name='001')
        self.assertEqual(admin.person_type, PersonType.ADMIN)
        self.assertTrue(admin.roles.filter(role=RoleCode.SYSTEM_ADMIN).exists())

    def test_repeat_run_is_idempotent(self):
        run()
        text = run()

        self.assertIn('created=0', text)
        self.assertIn('skipped=3', text)
        self.assertEqual(Account.objects.count(), 3)

    def test_since_filter_skips_prefix(self):
        text = run('--since', '2')
        # 三个来源各 1 行，since=2 时每种来源都跳过
        self.assertIn('created=0', text)
        self.assertEqual(Account.objects.count(), 0)

    def test_password_hash_is_preserved_verbatim(self):
        run()

        for link in LegacyAccountLink.objects.select_related('account'):
            model = {
                'app01_admin': legacy.Admin,
                'app01_teacher': legacy.Teacher,
                'app01_student': legacy.Student,
            }[link.source_table]
            legacy_hash = model.objects.values_list('password', flat=True).get(pk=link.source_pk)

            # 只断言相等，不打印任何哈希
            self.assertEqual(link.account.password, legacy_hash)

    def test_must_change_password_forced(self):
        run()
        self.assertTrue(all(a.must_change_password for a in Account.objects.all()))


class FaultInjectionTests(G5Fixture):
    def test_failure_on_profile_rolls_back_only_that_row(self):
        original_create = StudentProfile.objects.create

        def boom(**kwargs):
            raise RuntimeError('simulated profile failure')

        with patch.object(StudentProfile.objects, 'create', side_effect=boom):
            text = run()

        # 学生那一行失败，但管理员/教师仍成功
        self.assertIn('errors=1', text)
        self.assertEqual(Account.objects.count(), 2)
        self.assertFalse(Account.objects.filter(login_name='S01').exists())
        # 失败行不应留下映射
        self.assertFalse(LegacyAccountLink.objects.filter(source_pk='S01').exists())
        self.assertEqual(StudentProfile.objects.count(), 0)


class RollbackScopeTests(G5Fixture):
    def test_rollback_removes_only_backfilled_accounts(self):
        run()

        survivor = Account.objects.create_user(
            'PREEXIST', PASSWORD, display_name='预存', person_type='teacher'
        )
        survivor.must_change_password = False
        survivor.save(update_fields=['must_change_password'])

        run('--rollback')

        self.assertTrue(Account.objects.filter(login_name='PREEXIST').exists())
        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(LegacyAccountLink.objects.count(), 0)
        self.assertEqual(StudentProfile.objects.count(), 0)
        self.assertEqual(TeacherProfile.objects.count(), 0)

    def test_rollback_does_not_touch_legacy_tables(self):
        run()
        run('--rollback')

        self.assertEqual(legacy.Admin.objects.count(), 1)
        self.assertEqual(legacy.Teacher.objects.count(), 1)
        self.assertEqual(legacy.Student.objects.count(), 1)

    def test_second_backfill_restores(self):
        run()
        run('--rollback')
        self.assertEqual(Account.objects.count(), 0)

        run()

        self.assertEqual(Account.objects.count(), 3)
        self.assertEqual(LegacyAccountLink.objects.count(), 3)
        payload = verify_json()
        self.assertTrue(payload['ok'], payload['issues'])


class ConsistencyDetectionTests(G5Fixture):
    def setUp(self):
        run()

    def test_pristine_is_ok(self):
        payload = verify_json('--strict-count')
        self.assertTrue(payload['ok'])
        self.assertFalse(payload['repair_executed'])

    def test_missing_link_detected(self):
        LegacyAccountLink.objects.filter(source_table='app01_student').delete()

        payload = verify_json()
        codes = {i['code'] for i in payload['issues']}
        self.assertIn('UNLINKED_ACCOUNT', codes)
        self.assertIn('ORPHAN_PROFILE', codes)
        self.assertFalse(payload['repair_executed'])

    def test_wrong_role_detected(self):
        from django.utils import timezone

        from r21_account.models import AccountRole

        AccountRole.objects.filter(revoked_at__isnull=True).first()  # noqa: B018
        AccountRole.objects.update(revoked_at=timezone.now())

        payload = verify_json()
        self.assertIn('ROLE_MISMATCH', {i['code'] for i in payload['issues']})

    def test_status_inconsistency_detected(self):
        from django.utils import timezone

        account = Account.objects.filter(is_active=True).first()
        account.deactivated_at = timezone.now()
        account.save(update_fields=['deactivated_at'])

        payload = verify_json()
        self.assertIn('STATUS_INCONSISTENT', {i['code'] for i in payload['issues']})

    def test_strict_count_detects_extra_account(self):
        Account.objects.create_user(
            'EXTRA', PASSWORD, display_name='额外', person_type='teacher'
        )

        strict_payload = verify_json('--strict-count')
        self.assertIn('STRICT_COUNT_MISMATCH', {i['code'] for i in strict_payload['issues']})

        # 非 strict 模式不应把它当作问题
        normal_payload = verify_json()
        self.assertTrue(normal_payload['ok'])
