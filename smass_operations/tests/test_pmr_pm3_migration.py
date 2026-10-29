"""PM3：迁移与对账的单元/集成测试。

真实的跨库迁移由 `scripts/pmr_migrate_rows.py` 执行（见 PMR 命令日志）；
本文件在测试库内验证迁移器的**关键契约**：

- 哈希可用性判定（决定 rejected 还是 created）
- 库名前缀守卫
- 映射表唯一约束（幂等的物理保证）
- `lookup` / `record` / `bump` 行为与计数语义
"""
import importlib.util
import os
from pathlib import Path

from django.db import connection
from django.test import TestCase, TransactionTestCase

BASE = Path(__file__).resolve().parents[2]


def load_migrator_module():
    path = BASE / 'scripts' / 'pmr_migrate_rows.py'
    spec = importlib.util.spec_from_file_location('pmr_migrate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UsableHashTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_migrator_module()

    def test_single_md5_is_usable(self):
        self.assertTrue(self.mod._is_usable_hash('a' * 32))

    def test_pbkdf2_is_usable(self):
        self.assertTrue(
            self.mod._is_usable_hash('pbkdf2_sha256$720000$salt$hash'))

    def test_django_argon2_is_usable(self):
        self.assertTrue(self.mod._is_usable_hash('argon2$argon2id$v=19$m=102400'))

    def test_empty_not_usable(self):
        self.assertFalse(self.mod._is_usable_hash(''))
        self.assertFalse(self.mod._is_usable_hash(None))

    def test_adversarial_not_usable(self):
        for value in ('a' * 31, 'a' * 33, 'A' * 32, 'z' * 32):
            self.assertFalse(self.mod._is_usable_hash(value),
                             '{} 不应被判定为可用'.format(value[:8]))


class GuardTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_migrator_module()

    def test_source_prefix_enforced(self):
        for bad in ('smass', 'smass_r10_release', 'smass_h5_clone_x'):
            with self.assertRaises(SystemExit):
                self.mod.guard(bad, self.mod.SOURCE_PREFIX)

    def test_target_prefix_enforced(self):
        # 源前缀不能冒充目标前缀
        with self.assertRaises(SystemExit):
            self.mod.guard('smass_pmr_tiny_1', self.mod.TARGET_PREFIX)

    def test_correct_prefixes_accepted(self):
        self.mod.guard('smass_pmr_tiny_1', self.mod.SOURCE_PREFIX)
        self.mod.guard('smass_pmr_target_1', self.mod.TARGET_PREFIX)


class MapTableTests(TransactionTestCase):
    """映射表的唯一约束是幂等的物理保证。"""

    def setUp(self):
        self.mod = load_migrator_module()
        with connection.cursor() as cur:
            cur.execute(self.mod.MAP_TABLE_DDL)

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS pmr_legacy_map')

    def _insert(self, source_table, source_id, pk=1, batch='b1'):
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO pmr_legacy_map '
                '(batch_id, source_table, source_id, target_table, target_pk, '
                ' status, note, created_at, updated_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())',
                [batch, source_table, str(source_id), 't', pk, 'created', ''])

    def test_duplicate_source_rejected(self):
        self._insert('app01_admin', 'A01')
        with self.assertRaises(Exception):
            self._insert('app01_admin', 'A01')

    def test_same_id_different_table_allowed(self):
        self._insert('app01_admin', 'A01')
        self._insert('app01_student', 'A01')  # 不应冲突

        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM pmr_legacy_map')
            self.assertEqual(cur.fetchone()[0], 2)

    def test_batch_index_exists(self):
        """批次索引存在（回滚按批次筛选用）。"""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pmr_legacy_map' "
                "AND INDEX_NAME='idx_pmr_batch'")
            self.assertGreater(cur.fetchone()[0], 0)


class CounterSemanticsTests(TestCase):
    """计数语义：纯内存验证，不建连接。

    `Migrator.__init__` 会连数据库；这里用 `__new__` 绕过构造器，
    只测 `bump` / `details` 封顶这类与 IO 无关的行为。
    """

    def _bare_migrator(self):
        mod = load_migrator_module()
        migrator = mod.Migrator.__new__(mod.Migrator)
        migrator.batch_id = 'test-batch'
        migrator.dry_run = True
        migrator.counters = {
            'created': 0, 'updated': 0, 'skipped': 0,
            'conflict': 0, 'rejected': 0,
        }
        migrator.details = {key: [] for key in migrator.counters}
        return migrator

    def test_bump_increments_and_records(self):
        migrator = self._bare_migrator()
        migrator.bump('created', 'app01_admin', 'A01', 'note')
        self.assertEqual(migrator.counters['created'], 1)
        self.assertEqual(len(migrator.details['created']), 1)
        self.assertIn('A01', migrator.details['created'][0]['source'])

    def test_bump_details_capped(self):
        migrator = self._bare_migrator()
        for i in range(300):
            migrator.bump('created', 'app01_admin', 'A{}'.format(i))
        self.assertEqual(migrator.counters['created'], 300)
        self.assertLessEqual(len(migrator.details['created']), 200,
                             '明细应封顶，避免 manifest 爆炸')

    def test_all_five_counters_exist(self):
        migrator = self._bare_migrator()
        self.assertEqual(
            set(migrator.counters),
            {'created', 'updated', 'skipped', 'conflict', 'rejected'})

    def test_bump_unknown_kind_raises(self):
        migrator = self._bare_migrator()
        with self.assertRaises(KeyError):
            migrator.bump('nonexistent', 'app01_admin', 'A1')
