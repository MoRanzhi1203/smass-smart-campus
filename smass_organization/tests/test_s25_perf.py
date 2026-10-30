"""S25-PERF：10,000 行 CSV 导出的真实性能与查询预算回归。

对比两条路径（同一份数据、同一进程）：

- **baseline**：旧实现风格——``list(queryset)`` 物化全部行，
  并对每行调用 ``filtered_extra``（逐行查询字段定义，N+1）；
- **optimized**：``iter_students_csv``——``iterator(chunk_size)`` 分批取数，
  字段可见性一次计算，逐块 yield 给 ``StreamingHttpResponse``。

断言查询数与内存上限，并在同一进程内比较耗时；不编造 SLA。
"""
from __future__ import annotations

import csv
import io
import time
import tracemalloc

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_organization import export, services
from smass_organization.models import StudentFieldDefinition, StudentRecord

PASSWORD = 'S25Perf#2026'
ROW_COUNT = 10000


def make_account(login, role):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin')
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    core_services.ensure_role_groups()
    core_services.grant_role(account, role, granted_by='s25_perf')
    return Account.objects.get(pk=account.pk)


class CsvPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unit = services.create_unit(
            code='PERF', name='性能学院', unit_type='college')
        StudentFieldDefinition.objects.create(
            code='phone', label='手机号', is_sensitive=True,
            visible_roles=['system_admin'])
        cls.sys = make_account('PERF_SYS', RoleCode.SYSTEM_ADMIN)
        StudentRecord.objects.bulk_create([
            StudentRecord(
                student_no='P{:05d}'.format(index),
                name='学生{:05d}'.format(index),
                unit=cls.unit,
                extra={'phone': '139{:08d}'.format(index)},
            )
            for index in range(ROW_COUNT)
        ], batch_size=2000)

    def _baseline_export(self):
        """旧实现：列表物化 + 逐行字段权限查询（N+1）。"""
        queryset = (services.scoped_students(self.sys)
                    .select_related('unit').order_by('student_no'))
        rows = list(queryset)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator='\n')
        writer.writerow(['student_no', 'name', 'unit', 'status'])
        for record in rows:
            services.filtered_extra(record, self.sys)  # 逐行查询，复现旧的 N+1
            writer.writerow([
                record.student_no, record.name,
                record.unit.code if record.unit else '', record.status,
            ])
        return buffer.getvalue()

    def test_stream_rows_complete(self):
        text = ''.join(export.iter_students_csv(self.sys, chunk_size=2000))
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(ROW_COUNT + 1, len(rows))
        self.assertEqual('P00000', rows[1][0])
        self.assertIn('phone', rows[0])

    def test_query_budget_is_constant(self):
        # 前面的 baseline 会产生上万条查询并触发日志上限；先清空再计数。
        connection.queries_log.clear()
        with CaptureQueriesContext(connection) as captured:
            for _chunk in export.iter_students_csv(self.sys, chunk_size=2000):
                pass
        self.assertGreater(len(captured.captured_queries), 0,
                           '查询捕获为空，预算断言无效')
        # 角色/范围/字段定义 + 5 个 iterator 分块 + 余量
        self.assertLessEqual(len(captured.captured_queries), 12,
                             [q['sql'][:80] for q in captured.captured_queries])

    def test_faster_than_baseline_and_bounded_memory(self):
        tracemalloc.start()
        started = time.perf_counter()
        baseline_text = self._baseline_export()
        baseline_seconds = time.perf_counter() - started
        _current, baseline_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        started = time.perf_counter()
        optimized_text = ''.join(
            export.iter_students_csv(self.sys, chunk_size=2000))
        optimized_seconds = time.perf_counter() - started
        _current, optimized_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertIn('13900000000', optimized_text)
        self.assertLess(optimized_seconds, baseline_seconds,
                        'optimized={:.3f}s baseline={:.3f}s'.format(
                            optimized_seconds, baseline_seconds))
        self.assertLess(optimized_peak, baseline_peak,
                        'optimized_peak={} baseline_peak={}'.format(
                            optimized_peak, baseline_peak))
        # 10k 行流式导出不应把整表物化进内存
        self.assertLess(optimized_peak, 20 * 1024 * 1024)
