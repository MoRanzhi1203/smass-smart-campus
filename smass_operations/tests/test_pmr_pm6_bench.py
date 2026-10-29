"""PM6/PM7：性能与并发的测试（契约层）。

真实测量由 `scripts/pmr_bench.py` 执行（1k/10k 两规模，见 PMR 命令日志）；
本文件验证基准工具的**可测契约**：

- 百分位函数在边界输入下正确（空、单值、已知序列）
- 主机画像函数返回合理字段
- 多进程 worker 用 `os.getpid()` 报告真实进程（不是线程伪装）
- 库名前缀守卫
"""
import importlib.util
import os
from pathlib import Path

from django.test import TestCase

BASE = Path(__file__).resolve().parents[2]


def load_bench():
    path = BASE / 'scripts' / 'pmr_bench.py'
    spec = importlib.util.spec_from_file_location('pmr_bench', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PercentileTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_bench()

    def test_empty_returns_zero_count(self):
        self.assertEqual(self.mod.percentiles([]), {'count': 0})

    def test_single_value(self):
        result = self.mod.percentiles([0.01])
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['p50_ms'], 10.0)
        self.assertEqual(result['p95_ms'], 10.0)
        self.assertEqual(result['p99_ms'], 10.0)
        self.assertEqual(result['max_ms'], 10.0)

    def test_known_sequence(self):
        # 100 个值：0.001s 到 0.100s
        samples = [(i + 1) / 1000.0 for i in range(100)]
        result = self.mod.percentiles(samples)

        self.assertEqual(result['count'], 100)
        self.assertAlmostEqual(result['min_ms'], 1.0, places=2)
        self.assertAlmostEqual(result['max_ms'], 100.0, places=2)
        # p50 = 第 50、51 个的均值 -> 50.5ms
        self.assertAlmostEqual(result['p50_ms'], 50.5, places=1)
        # p95 = ordered[94] = 95ms
        self.assertAlmostEqual(result['p95_ms'], 95.0, places=1)
        # p99 = ordered[98] = 99ms
        self.assertAlmostEqual(result['p99_ms'], 99.0, places=1)

    def test_monotonic_percentiles(self):
        samples = [0.005, 0.010, 0.050, 0.100, 0.200, 0.500]
        result = self.mod.percentiles(samples)
        self.assertLessEqual(result['min_ms'], result['p50_ms'])
        self.assertLessEqual(result['p50_ms'], result['p95_ms'])
        self.assertLessEqual(result['p95_ms'], result['p99_ms'])
        self.assertLessEqual(result['p99_ms'], result['max_ms'])


class HostProfileTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_bench()

    def test_returns_expected_keys(self):
        profile = self.mod.host_profile()
        for key in ('platform', 'python', 'cpu_count'):
            self.assertIn(key, profile)
        self.assertIsInstance(profile['cpu_count'], int)
        self.assertGreater(profile['cpu_count'], 0, 'CPU 数应为正')


class ShowValueTests(TestCase):
    """`SHOW ... LIKE` 返回两列，取值必须取第二列。"""

    def test_show_value_reads_second_column(self):
        from django.db import connection

        mod = load_bench()
        with connection.cursor() as cur:
            value = mod.show_value(cur, "SHOW VARIABLES LIKE 'version'")
        self.assertIsNotNone(value)
        self.assertNotEqual(value, 'version', '取到了变量名而不是值')
        self.assertRegex(str(value), r'^\d+\.\d+')

    def test_scalar_reads_first_column(self):
        from django.db import connection

        mod = load_bench()
        with connection.cursor() as cur:
            value = mod.scalar(cur, 'SELECT 42')
        self.assertEqual(value, 42)


class MultiprocessWorkerContractTests(TestCase):
    """worker 必须报告真实 pid，且以进程方式运行（不是线程）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_bench()

    def test_worker_grant_importable_and_pid_aware(self):
        source = (BASE / 'scripts' / 'pmr_bench.py').read_text(encoding='utf-8')
        # worker 必须报告 os.getpid()，否则无法证明是多进程
        self.assertIn("'pid': os.getpid()", source)
        # 且必须用 ProcessPoolExecutor（不是 ThreadPoolExecutor）
        self.assertIn('ProcessPoolExecutor', source)
        self.assertNotIn('ThreadPoolExecutor', source)

    def test_worker_uses_time_barrier(self):
        """用时间对齐降低调度抖动（不强求严格同时）。"""
        source = (BASE / 'scripts' / 'pmr_bench.py').read_text(encoding='utf-8')
        self.assertIn('barrier_at', source)
        self.assertIn('time.sleep', source)


class GuardTests(TestCase):
    def test_prefix_enforced_in_main(self):
        source = (BASE / 'scripts' / 'pmr_bench.py').read_text(encoding='utf-8')
        self.assertIn("startswith('smass_pmr_')", source)


class IsolationAwarenessTests(TestCase):
    """基准脚本必须记录服务器隔离级别（避免"以为测的是 READ COMMITTED"）。"""

    def test_records_transaction_isolation(self):
        source = (BASE / 'scripts' / 'pmr_bench.py').read_text(encoding='utf-8')
        self.assertIn('@@transaction_isolation', source)

    def test_records_deadlock_counter(self):
        source = (BASE / 'scripts' / 'pmr_bench.py').read_text(encoding='utf-8')
        self.assertIn('Innodb_deadlocks', source)

    def test_records_lock_waits(self):
        source = (BASE / 'scripts' / 'pmr_bench.py').read_text(encoding='utf-8')
        self.assertIn('data_lock_waits', source)
