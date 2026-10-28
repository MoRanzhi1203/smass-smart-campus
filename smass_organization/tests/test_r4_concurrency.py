"""R4-02：并发安全（乐观锁）与导入事务边界。"""
from django.test import TestCase

from smass_organization import services
from smass_organization.models import (
    OrganizationUnit,
    StudentRecord,
    StudentRecordChange,
)


class OptimisticLockTests(TestCase):
    def setUp(self):
        self.college = services.create_unit(code='C1', name='学院', unit_type='college')
        self.record = StudentRecord.objects.create(
            student_no='S001', name='原名', unit=self.college
        )

    def test_successful_update_bumps_version(self):
        record, changes = services.update_student(
            self.record, name='新名', expected_version=1, actor='tester'
        )
        self.assertEqual(record.name, '新名')
        self.assertEqual(record.version, 2)
        self.assertEqual(len(changes), 1)
        self.assertTrue(
            StudentRecordChange.objects.filter(record=self.record, field_name='name').exists()
        )

    def test_stale_version_rejected_without_lost_update(self):
        # 写者 A 先成功
        services.update_student(self.record, name='A改名', expected_version=1, actor='A')

        # 写者 B 仍持旧版本 -> 必须失败
        stale = StudentRecord.objects.get(pk=self.record.pk)
        with self.assertRaises(services.ConcurrencyError):
            services.update_student(stale, name='B改名', expected_version=1, actor='B')

        # 数据是 A 的值，没有被 B 覆盖
        final = StudentRecord.objects.get(pk=self.record.pk)
        self.assertEqual(final.name, 'A改名')
        self.assertEqual(final.version, 2)

    def test_no_change_no_version_bump(self):
        record, changes = services.update_student(
            self.record, name='原名', expected_version=1
        )
        self.assertEqual(changes, [])
        self.assertEqual(record.version, 1)

    def test_update_without_expected_version_still_works(self):
        record, _ = services.update_student(self.record, name='无锁更新')
        self.assertEqual(record.name, '无锁更新')

    def test_status_and_unit_change_recorded(self):
        other = services.create_unit(code='C2', name='学院2', unit_type='college')
        record, changes = services.update_student(
            self.record, status='suspended', unit=other, expected_version=1
        )
        names = {c[0] for c in changes}
        self.assertEqual(names, {'status', 'unit'})
        self.assertEqual(record.status, 'suspended')
        self.assertEqual(record.unit, other)


class ImportConcurrencyTests(TestCase):
    def setUp(self):
        services.create_unit(code='C1', name='学院', unit_type='college')

    def _csv(self, rows):
        return '\n'.join(['student_no,name,unit_code,status'] + rows)

    def test_sequential_import_same_row_is_idempotent(self):
        text = self._csv(['S100,学生,C1,enrolled'])
        services.import_commit(text, actor='a')
        services.import_commit(text, actor='b')

        self.assertEqual(StudentRecord.objects.filter(student_no='S100').count(), 1)

    def test_import_update_respects_existing_version(self):
        text = self._csv(['S200,原名,C1,enrolled'])
        services.import_commit(text, actor='a')

        record = StudentRecord.objects.get(student_no='S200')
        self.assertEqual(record.version, 1)

        services.import_commit(self._csv(['S200,新名,C1,enrolled']), actor='b')

        record.refresh_from_db()
        self.assertEqual(record.name, '新名')
        self.assertEqual(record.version, 2)

    def test_import_partial_failure_does_not_lose_good_rows(self):
        text = self._csv([
            'S301,好行,C1,enrolled',
            'S302,坏行,NOPE,enrolled',
            'S303,也好,C1,enrolled',
        ])
        job, stats = services.import_commit(text, actor='a')

        self.assertEqual(stats['created'], 2)
        self.assertTrue(StudentRecord.objects.filter(student_no='S301').exists())
        self.assertTrue(StudentRecord.objects.filter(student_no='S303').exists())
        self.assertFalse(StudentRecord.objects.filter(student_no='S302').exists())
        self.assertEqual(job.error_rows, 1)
