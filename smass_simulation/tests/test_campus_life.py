"""P6 校园生活测试：考勤/请假/社团/活动/财务/通知规模与幂等。"""
from __future__ import annotations

import os

from django.test import TestCase

from smass_activities.models import Activity, ActivityRegistration
from smass_attendance.models import AttendanceRecord, AttendanceSession, LeaveRequest
from smass_clubs.models import Club, ClubMembership
from smass_finance.models import Bill
from smass_simulation.generator import campus_life
from smass_simulation.generator import config as sim_config
from smass_simulation.generator import org, people, staff
from smass_simulation.generator.batch import BatchContext
from smass_simulation.models import SimulationBatch
from smass_workflow.models import Notification


class CampusLifeTests(TestCase):
    def setUp(self):
        os.environ['SIM_SEED'] = '20261101'
        self.config = sim_config.resolve('small', {
            'colleges': 1, 'majors': 2, 'grades': 2,
            'classes_per_major_grade': 1, 'students_per_class': 3,
        })
        self.batch = SimulationBatch.objects.create(
            code='test-campus', profile='small', seed=20261101)
        self.ctx = BatchContext(self.batch)
        org.generate(self.config, self.ctx)
        people.generate_students(self.config, self.ctx)
        staff.generate_staff(self.config, self.ctx)

    def test_generate_campus_life(self):
        result = campus_life.generate_campus_life(self.config, self.ctx)
        self.assertEqual(AttendanceSession.objects.count(), 8)
        self.assertEqual(AttendanceRecord.objects.count(), 24)
        self.assertEqual(LeaveRequest.objects.count(), 12)
        self.assertEqual(Club.objects.count(), 20)
        self.assertEqual(ClubMembership.objects.count(), 240)
        self.assertEqual(Activity.objects.count(), 40)
        self.assertEqual(ActivityRegistration.objects.count(), 480)
        self.assertEqual(Bill.objects.count(), 12)
        self.assertGreater(Notification.objects.count(), 0)
        self.assertEqual(result['attendance_sessions'], 8)

    def test_campus_life_idempotent(self):
        campus_life.generate_campus_life(self.config, self.ctx)
        counts = (AttendanceSession.objects.count(),
                  AttendanceRecord.objects.count(),
                  ClubMembership.objects.count(),
                  ActivityRegistration.objects.count(),
                  Bill.objects.count())
        campus_life.generate_campus_life(self.config, self.ctx)
        self.assertEqual(counts, (AttendanceSession.objects.count(),
                                  AttendanceRecord.objects.count(),
                                  ClubMembership.objects.count(),
                                  ActivityRegistration.objects.count(),
                                  Bill.objects.count()))
