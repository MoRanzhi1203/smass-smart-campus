"""岗位反推测试：公式、幂等、最小权限。"""
from __future__ import annotations

import os

from django.test import TestCase

from r21_account.models import Account, AccountRole, TeacherProfile
from smass_organization.models import OrganizationMembership
from smass_simulation.generator import config as sim_config
from smass_simulation.generator import org, people, staff
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch


class StaffPlanTests(TestCase):
    def test_formula_for_medium(self):
        result = staff.plan(216)
        self.assertEqual(result['sections_planned'], 1728)
        self.assertEqual(result['weekly_hours'], 5184)
        self.assertEqual(result['teachers'], 432)
        self.assertEqual(result['counselors'], 27)
        self.assertEqual(result['head_teachers'], 216)


class StaffGenerateTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-staff', profile='small', seed=20261101)
        self.ctx = BatchContext(self.batch)
        org.generate(self.config, self.ctx)
        people.generate_students(self.config, self.ctx)

    def test_generate_is_idempotent(self):
        from smass_organization.models import OrganizationUnit

        classes = list(OrganizationUnit.objects.filter(
            code__startswith='SIM-CLS-'))
        first = staff.generate_staff(self.config, self.ctx)
        second = staff.generate_staff(self.config, self.ctx)
        self.assertEqual(first['created'], 8)  # 4 班 × 2
        self.assertEqual(second['created'], 0)
        self.assertEqual(TeacherProfile.objects.count(), 8)
        rows = list(OrganizationMembership.objects.filter(
            role='counselor').values_list('unit_id', 'account_id'))
        self.assertEqual(
            len(rows), len(classes),
            'rows={} classes={}'.format(rows, [item.pk for item in classes]))
        self.assertEqual(
            OrganizationMembership.objects.filter(role='head_teacher').count(),
            len(classes))

    def test_minimum_privilege(self):
        staff.generate_staff(self.config, self.ctx)
        self.assertEqual(Account.objects.filter(
            login_name__startswith='sim_adm_').count(), 3)
        self.assertFalse(AccountRole.objects.filter(
            role='system_admin').exists())
        self.assertTrue(Account.objects.filter(
            login_name__startswith='sim_tea_').exists())
