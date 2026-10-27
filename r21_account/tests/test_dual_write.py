"""G2 双写一致性测试（含故障注入）。"""
from unittest.mock import patch

from django.test import TestCase

from app01 import models as legacy
from r21_account import dual_write, services
from r21_account.models import (
    Account,
    LegacyAccountLink,
    StudentProfile,
    TeacherProfile,
)

NEW_PASSWORD = 'DualWrite#2024'


class DualWriteBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.college = legacy.College.objects.create(name='信息工程学院')
        cls.grade = legacy.Grade.objects.create(name='2021级')
        cls.major = legacy.Major.objects.create(college=cls.college, name='信息安全技术')
        cls.classes = legacy.Classes.objects.create(
            name='信安2101', grade=cls.grade, major=cls.major
        )


class CreateStudentDualWriteTests(DualWriteBase):
    def test_create_writes_both_tables_with_same_hash(self):
        old, account = dual_write.create_student(
            student_id='S202500001',
            name='双写学生',
            classes=self.classes,
            raw_password=NEW_PASSWORD,
            card_id='500000200301010001',
            phone='13900000001',
        )

        old.refresh_from_db()
        account.refresh_from_db()

        self.assertEqual(old.password, account.password, '两表哈希必须完全一致')
        self.assertTrue(account.check_password(NEW_PASSWORD))
        self.assertTrue(account.must_change_password)
        self.assertTrue(StudentProfile.objects.filter(account=account).exists())
        self.assertTrue(
            LegacyAccountLink.objects.filter(
                account=account, source_pk='S202500001'
            ).exists()
        )
        self.assertTrue(account.roles.filter(role='student').exists())

    def test_duplicate_student_id_rejected(self):
        dual_write.create_student(
            student_id='S202500002', name='甲', classes=self.classes,
            raw_password=NEW_PASSWORD, card_id='500000200301010002',
        )
        with self.assertRaises(dual_write.DualWriteError):
            dual_write.create_student(
                student_id='S202500002', name='乙', classes=self.classes,
                raw_password=NEW_PASSWORD, card_id='500000200301010003',
            )


class CreateTeacherDualWriteTests(DualWriteBase):
    def test_create_teacher_writes_both_tables(self):
        old, account = dual_write.create_teacher(
            teacher_id='T950001',
            name='双写教师',
            college=self.college,
            raw_password=NEW_PASSWORD,
            card_id='500000199001010001',
            phone='13800000001',
        )

        old.refresh_from_db()
        account.refresh_from_db()

        self.assertEqual(old.password, account.password)
        self.assertTrue(account.check_password(NEW_PASSWORD))
        self.assertTrue(TeacherProfile.objects.filter(account=account).exists())
        self.assertTrue(account.roles.filter(role='teacher').exists())


class FaultInjectionTests(DualWriteBase):
    """故障注入：新表写失败时旧表必须回滚。"""

    def test_failure_on_new_table_rolls_back_old_table(self):
        student_id = 'S202500009'

        with patch.object(
            Account, 'save', side_effect=RuntimeError('simulated new-table failure')
        ):
            with self.assertRaises(RuntimeError):
                dual_write.create_student(
                    student_id=student_id,
                    name='应被回滚',
                    classes=self.classes,
                    raw_password=NEW_PASSWORD,
                    card_id='500000200301010009',
                )

        self.assertFalse(
            legacy.Student.objects.filter(pk=student_id).exists(),
            '新表失败时旧表必须回滚',
        )
        self.assertFalse(Account.objects.filter(login_name=student_id).exists())
        self.assertFalse(StudentProfile.objects.filter(student_no=student_id).exists())

    def test_failure_on_profile_rolls_back_both(self):
        student_id = 'S202500010'

        with patch.object(
            StudentProfile.objects, 'create', side_effect=RuntimeError('simulated profile failure')
        ):
            with self.assertRaises(RuntimeError):
                dual_write.create_student(
                    student_id=student_id,
                    name='应被回滚',
                    classes=self.classes,
                    raw_password=NEW_PASSWORD,
                    card_id='500000200301010010',
                )

        self.assertFalse(legacy.Student.objects.filter(pk=student_id).exists())
        self.assertFalse(Account.objects.filter(login_name=student_id).exists())


class ChangePasswordDualWriteTests(DualWriteBase):
    def test_change_password_updates_both_tables(self):
        old, account = dual_write.create_student(
            student_id='S202500003', name='改密学生', classes=self.classes,
            raw_password=NEW_PASSWORD, card_id='500000200301010003',
        )

        updated = dual_write.change_password('S202500003', 'ChangedOne#1')

        old.refresh_from_db()
        updated.refresh_from_db()

        self.assertEqual(old.password, updated.password, '改密后两表哈希必须一致')
        self.assertTrue(updated.check_password('ChangedOne#1'))
        self.assertFalse(updated.must_change_password)

    def test_change_password_unknown_login_raises(self):
        with self.assertRaises(dual_write.DualWriteError):
            dual_write.change_password('NO-SUCH-ACCOUNT', 'Whatever#1')


class DeactivateTests(DualWriteBase):
    def test_deactivate_sets_inactive(self):
        _, account = dual_write.create_teacher(
            teacher_id='T950002', name='停用教师', college=self.college,
            raw_password=NEW_PASSWORD, card_id='500000199001010002',
        )

        dual_write.deactivate('T950002', reason='离职')

        account.refresh_from_db()
        self.assertFalse(account.is_active)
        self.assertEqual(account.deactivated_reason, '离职')

    def test_activate_restores(self):
        _, account = dual_write.create_teacher(
            teacher_id='T950003', name='恢复教师', college=self.college,
            raw_password=NEW_PASSWORD, card_id='500000199001010003',
        )
        dual_write.deactivate('T950003', reason='测试')
        dual_write.activate('T950003')

        account.refresh_from_db()
        self.assertTrue(account.is_active)
        self.assertIsNone(account.deactivated_at)
