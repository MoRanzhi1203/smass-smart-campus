"""S05：真正跨库双写的可回归测试。

与 PM4（同库双表）不同，这里为 legacy / R10 各建一个独立数据库，
验证跨库写入失败、补偿、队列重放、进程崩溃与不确定提交的收敛。

需要真实 MySQL；未设置 ``SMASS_DB_PASSWORD`` / ``DB_PASSWORD`` 时跳过。
"""
import importlib.util
import os
import unittest
import uuid
from pathlib import Path

from django.test import SimpleTestCase

BASE = Path(__file__).resolve().parent.parent.parent
DB_PASSWORD_AVAILABLE = bool(
    os.environ.get('SMASS_DB_PASSWORD') or os.environ.get('DB_PASSWORD'))


def _load_script():
    path = BASE / 'scripts' / 'pmr_cross_db_dual_write.py'
    spec = importlib.util.spec_from_file_location('pmr_cross_db_dual_write', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DB_PASSWORD_AVAILABLE,
                     '需要真实 MySQL 凭据（SMASS_DB_PASSWORD/DB_PASSWORD）')
class CrossDbDualWriteTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('SMASS_DB_PASSWORD', os.environ.get('DB_PASSWORD', ''))
        cls.mod = _load_script()
        suffix = uuid.uuid4().hex[:8]
        cls.legacy_db = cls.mod.LEGACY_PREFIX + suffix
        cls.r10_db = cls.mod.R10_PREFIX + suffix
        cls.mod.create_db(cls.legacy_db)
        cls.mod.create_db(cls.r10_db)
        cls.report = cls.mod.scenario_all(cls.legacy_db, cls.r10_db)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.mod.drop_db(cls.legacy_db)
            cls.mod.drop_db(cls.r10_db)
        finally:
            super().tearDownClass()

    def test_all_scenarios_pass(self):
        failed = [c for c in self.report['checks'] if not c['ok']]
        self.assertEqual([], failed, failed)
        self.assertTrue(self.report['ok'])

    def test_independent_databases(self):
        """两侧必须位于不同数据库，避免再次退化为同库双表。"""
        self.assertNotEqual(self.report['legacy_db'], self.report['r10_db'])
        with self.mod.admin_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT table_name FROM information_schema.tables '
                    'WHERE table_schema=%s', [self.report['legacy_db']])
                legacy_tables = {r[0] for r in cur.fetchall()}
                cur.execute(
                    'SELECT table_name FROM information_schema.tables '
                    'WHERE table_schema=%s', [self.report['r10_db']])
                r10_tables = {r[0] for r in cur.fetchall()}
        self.assertIn('app01_admin', legacy_tables)
        self.assertNotIn('r21_account_account', legacy_tables)
        self.assertIn('r21_account_account', r10_tables)
        self.assertNotIn('app01_admin', r10_tables)

    def test_compensation_queue_drained(self):
        w = self.mod.CrossDbDualWriter(
            self.report['legacy_db'], self.report['r10_db'], 'assert')
        try:
            with w.r10.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM pmr_compensation_queue "
                    "WHERE status='pending'")
                self.assertEqual(0, cur.fetchone()[0])
            self.assertEqual(0, w.drift()['drift_count'])
        finally:
            w.close()
