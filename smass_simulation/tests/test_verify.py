"""P7 完整性校验测试：小规模全阶段生成后校验必须 100% 通过。"""
from __future__ import annotations

import os

from django.test import TestCase

from smass_simulation.generator import (
    campus_life, config as sim_config, dorms, org, people, staff, teaching,
    verify,
)
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch


class VerifyTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-verify', profile='small', seed=20261101)
        ctx = BatchContext(self.batch)
        org.generate(self.config, ctx)
        people.generate_students(self.config, ctx)
        staff.generate_staff(self.config, ctx)
        teaching.generate_teaching(self.config, ctx)
        dorms.generate_dorms(self.config, ctx)
        campus_life.generate_campus_life(self.config, ctx)

    def test_verify_all_checks_pass(self):
        report = verify.run_verify()
        failed = [item for item in report['checks'] if not item['passed']]
        self.assertEqual(failed, [], 'failed={}'.format(failed))
        self.assertEqual(report['passed'], report['total'])
        self.assertEqual(report['pass_rate'], 100.0)

    def test_distribution_present(self):
        report = verify.run_verify()
        distribution = report['distribution']
        for key in ('by_college', 'student_status', 'dorm', 'finance',
                    'activities', 'attendance'):
            self.assertIn(key, distribution)
        self.assertEqual(distribution['dorm']['buildings'], 1)
        self.assertGreater(distribution['dorm']['occupied'], 0)
