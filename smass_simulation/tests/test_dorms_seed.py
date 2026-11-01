"""P5 宿舍仿真测试：容量计算、分配唯一性、宿管范围、幂等。"""
from __future__ import annotations

import os

from django.test import TestCase

from smass_dormitory.models import (
    Bed,
    DormAssignment,
    DormBuilding,
    DormManagerScope,
    DormRoom,
)
from smass_simulation.generator import config as sim_config
from smass_simulation.generator import dorms, org, people
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch


class CapacityPlanTests(TestCase):
    def test_plan_for_medium(self):
        plan = dorms.capacity_plan(6480)
        self.assertEqual(plan['residents'], 5508)
        self.assertGreaterEqual(plan['beds'], plan['residents'])
        self.assertEqual(plan['buildings'], 13)
        self.assertEqual(plan['rooms'], 1560)


class DormSeedTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-dorms', profile='small', seed=20261101)
        self.ctx = BatchContext(self.batch)
        org.generate(self.config, self.ctx)
        people.generate_students(self.config, self.ctx)

    def test_assignments_unique_and_staffed(self):
        result = dorms.generate_dorms(self.config, self.ctx)
        self.assertEqual(result['assignments'], 10)  # 12 × 0.85 ≈ 10
        self.assertEqual(DormBuilding.objects.count(), 1)
        self.assertGreaterEqual(Bed.objects.filter(
            status='occupied').count(), 10)
        self.assertEqual(
            DormAssignment.objects.filter(active_slot=1).values('student')
            .distinct().count(), 10)
        self.assertEqual(DormManagerScope.objects.count(), 3)
        self.assertTrue(DormRoom.objects.exists())

    def test_dorms_idempotent(self):
        dorms.generate_dorms(self.config, self.ctx)
        rooms = DormRoom.objects.count()
        beds = Bed.objects.count()
        second = dorms.generate_dorms(self.config, self.ctx)
        self.assertEqual(DormRoom.objects.count(), rooms)
        self.assertEqual(Bed.objects.count(), beds)
        self.assertEqual(second['dorm_staff'], 0)
        self.assertEqual(second['assignments'], 10)
