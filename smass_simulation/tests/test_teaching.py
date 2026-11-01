"""P4 教学数据测试：规模、排课冲突、选课、幂等。"""
from __future__ import annotations

import os

from django.test import TestCase

from smass_academic.models import Enrollment, TeachingAssignment, TeachingSection
from smass_scheduling.models import ScheduleEntry
from smass_simulation.generator import config as sim_config
from smass_simulation.generator import org, people, staff, teaching
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch


class TeachingGenerateTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-teaching', profile='small', seed=20261101)
        self.ctx = BatchContext(self.batch)
        org.generate(self.config, self.ctx)
        people.generate_students(self.config, self.ctx)
        staff.generate_staff(self.config, self.ctx)

    def test_generate_teaching_and_no_conflicts(self):
        result = teaching.generate_teaching(self.config, self.ctx)
        self.assertEqual(result['sections'], 32)  # 4 班 × 8 门
        self.assertEqual(result['entries'], 64)   # 32 × 2 节
        self.assertEqual(result['conflicts'], 0)
        self.assertEqual(
            TeachingSection.objects.filter(code__startswith='SEC-').count(), 32)
        self.assertEqual(ScheduleEntry.objects.count(), 64)
        self.assertEqual(TeachingAssignment.objects.filter(
            section__code__startswith='SEC-').count(), 32)
        self.assertEqual(Enrollment.objects.filter(
            section__code__startswith='SEC-').count(), 96)  # 32 × 3 人

    def test_teaching_is_idempotent(self):
        teaching.generate_teaching(self.config, self.ctx)
        teaching.generate_teaching(self.config, self.ctx)
        self.assertEqual(
            TeachingSection.objects.filter(code__startswith='SEC-').count(), 32)
        self.assertEqual(ScheduleEntry.objects.count(), 64)
        self.assertEqual(Enrollment.objects.filter(
            section__code__startswith='SEC-').count(), 96)

    def test_capacity_covers_students(self):
        teaching.generate_teaching(self.config, self.ctx)
        section = TeachingSection.objects.filter(
            code__startswith='SEC-').first()
        enrolled = Enrollment.objects.filter(section=section).count()
        self.assertLessEqual(enrolled, section.capacity)
