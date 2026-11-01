"""P9 清理测试：dry-run 不动数据，confirm 后仿真数据清零。"""
from __future__ import annotations

import os

from django.test import TestCase

from r21_account.models import Account, StudentProfile
from smass_academic.models import TeachingSection
from smass_dormitory.models import Bed, DormAssignment
from smass_finance.models import Bill
from smass_organization.models import OrganizationUnit, StudentRecord
from smass_simulation.generator import (
    campus_life, cleanup, config as sim_config, dorms, org, people, staff,
    teaching,
)
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch


class CleanupTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-cleanup', profile='small', seed=20261101)
        ctx = BatchContext(self.batch)
        org.generate(self.config, ctx)
        people.generate_students(self.config, ctx)
        staff.generate_staff(self.config, ctx)
        teaching.generate_teaching(self.config, ctx)
        dorms.generate_dorms(self.config, ctx)
        campus_life.generate_campus_life(self.config, ctx)

    def test_dry_run_keeps_data(self):
        result = cleanup.cleanup(confirm=False)
        self.assertTrue(result['dry_run'])
        self.assertGreater(result['plan']['students'], 0)
        self.assertEqual(StudentRecord.objects.count(), 12)

    def test_confirm_removes_simulated_data(self):
        cleanup.cleanup(confirm=True)
        self.assertEqual(StudentRecord.objects.filter(
            student_no__startswith='S').count(), 0)
        self.assertEqual(StudentProfile.objects.count(), 0)
        self.assertEqual(Account.objects.filter(
            login_name__startswith='sim_').count(), 0)
        self.assertEqual(OrganizationUnit.objects.filter(
            code__startswith='SIM-').count(), 0)
        self.assertEqual(TeachingSection.objects.filter(
            code__startswith='SEC-').count(), 0)
        self.assertEqual(Bill.objects.count(), 0)
        self.assertEqual(DormAssignment.objects.count(), 0)
        self.assertEqual(Bed.objects.count(), 0)
        self.assertEqual(SimulationBatch.objects.count(), 0)
