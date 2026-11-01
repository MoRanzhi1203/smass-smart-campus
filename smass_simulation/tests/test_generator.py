"""组织与学生生成测试（隔离仿真配置）。"""
from __future__ import annotations

import os

from django.test import TestCase

from r21_account.models import Account, RoleCode, StudentProfile
from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
    StudentRecord,
)
from smass_simulation.generator import config as sim_config
from smass_simulation.generator import org, people
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch, SimulationObject


class GeneratorTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-batch', profile='small', seed=20261101)

    def _ctx(self):
        return BatchContext(self.batch)

    def test_org_tree_and_class_parent(self):
        ctx = self._ctx()
        result = org.generate(self.config, ctx)
        self.assertEqual(len(result['colleges']), 1)
        self.assertEqual(len(result['majors']), 2)
        self.assertEqual(len(result['classes']), 4)
        for class_unit in result['classes']:
            self.assertEqual(class_unit.unit_type, UNIT_TYPE_CLASS)
            self.assertEqual(class_unit.parent.unit_type, UNIT_TYPE_MAJOR)

    def test_students_created_once_and_pii_safe(self):
        ctx = self._ctx()
        org.generate(self.config, ctx)
        first = people.generate_students(self.config, ctx)
        second = people.generate_students(self.config, ctx)
        self.assertEqual(first['created'], 12)
        self.assertEqual(second['created'], 0)
        self.assertEqual(
            StudentRecord.objects.filter(student_no__startswith='S').count(), 12)
        record = StudentRecord.objects.filter(student_no__startswith='S').first()
        self.assertTrue(record.extra['phone'].startswith('100'))
        self.assertEqual(len(record.extra['phone']), 11)
        profile = StudentProfile.objects.get(account=record.account)
        self.assertEqual(profile.student_no, record.student_no)
        self.assertTrue(record.account.login_name.startswith('sim_stu_'))
        self.assertTrue(record.account.check_password(
            os.environ.get('SIMULATION_PASSWORD', 'Sim#2026demo')))

    def test_object_index_and_stage(self):
        ctx = self._ctx()
        org.generate(self.config, ctx)
        people.generate_students(self.config, ctx)
        self.batch.refresh_from_db()
        self.assertTrue(self.batch.stage_done.get('org'))
        self.assertTrue(self.batch.stage_done.get('students'))
        labels = set(SimulationObject.objects.filter(
            batch=self.batch).values_list('model_label', flat=True))
        self.assertIn('organization.StudentRecord', labels)
        self.assertIn('r21_account.Account', labels)
        self.assertIn('organization.OrganizationUnit', labels)
