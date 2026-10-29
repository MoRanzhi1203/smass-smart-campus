"""PM4：双写与回滚的测试。

真实的双写执行由 `scripts/pmr_dual_write.py` 完成（9 项检查全过，见 PMR 命令日志）；
本文件验证其**契约层**：

- 幂等键的唯一约束（重复请求只产生一行的物理保证）
- 批次索引存在（回滚按批次筛选）
- 三个模式常量互斥
- 失败注入异常类型
"""
import importlib.util
from pathlib import Path

from django.db import connection
from django.test import TestCase, TransactionTestCase

BASE = Path(__file__).resolve().parents[2]


def load_dual_module():
    path = BASE / 'scripts' / 'pmr_dual_write.py'
    spec = importlib.util.spec_from_file_location('pmr_dual', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModeConstantsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_dual_module()

    def test_three_modes_distinct(self):
        modes = {self.mod.MODE_OFF, self.mod.MODE_DUAL, self.mod.MODE_R10}
        self.assertEqual(len(modes), 3)
        self.assertEqual(modes, {'off', 'dual', 'r10'})

    def test_injected_failure_is_runtime_error(self):
        self.assertTrue(issubclass(self.mod.InjectedFailure, RuntimeError))


class DualTableTests(TransactionTestCase):
    """在真实数据库上验证 DDL 的约束。"""

    def setUp(self):
        self.mod = load_dual_module()
        with connection.cursor() as cur:
            cur.execute(self.mod.DUAL_DDL)

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS pmr_dual_log')

    def _insert(self, idem, batch='b1', status='committed'):
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_dual_log '
                '(batch_id, idempotency_key, operation, legacy_ok, r10_ok, '
                ' status, note, created_at, updated_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())',
                [batch, idem, 'create_account', 1, 1, status, ''])

    def test_idempotency_key_unique(self):
        self._insert('create:X01')
        with self.assertRaises(Exception):
            self._insert('create:X01')

    def test_different_keys_allowed(self):
        self._insert('create:X01')
        self._insert('create:X02')
        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM pmr_dual_log')
            self.assertEqual(cur.fetchone()[0], 2)

    def test_batch_index_exists(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pmr_dual_log' "
                "AND INDEX_NAME='idx_dual_batch'")
            self.assertGreater(cur.fetchone()[0], 0)

    def test_status_can_be_updated(self):
        self._insert('create:X03', status='committed')
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE pmr_dual_log SET status='rolled_back' "
                "WHERE idempotency_key='create:X03'")
        with connection.cursor() as cur:
            cur.execute(
                "SELECT status FROM pmr_dual_log WHERE idempotency_key='create:X03'")
            self.assertEqual(cur.fetchone()[0], 'rolled_back')

    def test_legacy_and_r10_flags_independent(self):
        """legacy_ok 与 r10_ok 必须能表达"一边成功一边失败"。"""
        self._insert('create:X04')
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE pmr_dual_log SET legacy_ok=1, r10_ok=0, "
                "status='compensated' WHERE idempotency_key='create:X04'")
            cur.execute(
                "SELECT legacy_ok, r10_ok, status FROM pmr_dual_log "
                "WHERE idempotency_key='create:X04'")
            legacy_ok, r10_ok, status = cur.fetchone()

        self.assertEqual(legacy_ok, 1)
        self.assertEqual(r10_ok, 0)
        self.assertEqual(status, 'compensated')
