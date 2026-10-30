"""S04：迁移严格对账的端到端可回归测试。

覆盖：
- 孤儿专业/班级进入持久化隔离队列（不静默遗漏）；
- 字段截断被记录；
- 分区无损（mapped + isolated == source）；
- 补齐父级后受控重放，隔离行解除且不重复插入。

需要真实 MySQL；未设置凭据时跳过。
"""
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from django.test import SimpleTestCase

BASE = Path(__file__).resolve().parent.parent.parent
SCRIPT = BASE / 'scripts' / 'pmr_migrate_rows.py'
DB_PASSWORD_AVAILABLE = bool(
    os.environ.get('SMASS_DB_PASSWORD') or os.environ.get('DB_PASSWORD'))

LEGACY_DDL = [
    'CREATE TABLE app01_college (id INT PRIMARY KEY, name VARCHAR(100) NOT NULL) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    'CREATE TABLE app01_major (id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, '
    'college_id INT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    'CREATE TABLE app01_classes (id INT PRIMARY KEY, name VARCHAR(255) NOT NULL, '
    'grade_id INT NULL, major_id INT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    'CREATE TABLE app01_admin (id VARCHAR(3) PRIMARY KEY, name VARCHAR(16) NOT NULL, '
    'password VARCHAR(128) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    'CREATE TABLE app01_teacher (id VARCHAR(3) PRIMARY KEY, name VARCHAR(16) NOT NULL, '
    'password VARCHAR(128) NOT NULL, college_id INT NULL) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    'CREATE TABLE app01_student (id VARCHAR(20) PRIMARY KEY, name VARCHAR(16) NOT NULL, '
    'password VARCHAR(128) NOT NULL, classes_id INT NULL) '
    'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
]

LEGACY_DATA = [
    "INSERT INTO app01_college VALUES (1, '计算机学院')",
    "INSERT INTO app01_major VALUES (1, '软件工程', 1)",
    "INSERT INTO app01_major VALUES (2, '孤儿专业', 99)",
    "INSERT INTO app01_classes VALUES (1, '软工一班', 1, 1)",
    "INSERT INTO app01_classes VALUES (2, '孤儿班级', 1, 2)",
    "INSERT INTO app01_classes VALUES (3, '{}', 1, 1)".format('超长班级' * 30),
    "INSERT INTO app01_admin VALUES ('A01', '管理员', '{}')".format('a' * 32),
    "INSERT INTO app01_admin VALUES ('A02', '坏哈希', 'not-a-hash')",
    "INSERT INTO app01_teacher VALUES ('T01', '教师甲', '{}', 1)".format('b' * 32),
    "INSERT INTO app01_student VALUES ('S01', '学生甲', '{}', 1)".format('c' * 32),
    "INSERT INTO app01_student VALUES ('S02', '学生乙', '{}', 2)".format('d' * 32),
]


def _load_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location('pmr_migrate_rows', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DB_PASSWORD_AVAILABLE,
                     '需要真实 MySQL 凭据（SMASS_DB_PASSWORD/DB_PASSWORD）')
class MigrationPartitionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault('SMASS_DB_PASSWORD', os.environ.get('DB_PASSWORD', ''))
        cls.mod = _load_mod()
        suffix = uuid.uuid4().hex[:8]
        cls.source = 'smass_pmr_s04_{}'.format(suffix)
        cls.target = 'smass_pmr_target_s04_{}'.format(suffix)
        cls.batch = 's04-{}'.format(suffix)
        cls._admin('CREATE DATABASE `{}` DEFAULT CHARACTER SET utf8mb4'.format(cls.source))
        cls._source_exec(LEGACY_DDL + LEGACY_DATA)
        cls.first = cls._run(['--source', cls.source, '--target', cls.target,
                              '--batch-id', cls.batch, '--json'])

    @classmethod
    def tearDownClass(cls):
        try:
            cls._admin('DROP DATABASE IF EXISTS `{}`'.format(cls.source))
            cls._admin('DROP DATABASE IF EXISTS `{}`'.format(cls.target))
        finally:
            super().tearDownClass()

    @staticmethod
    def _admin(sql):
        c = _load_mod().conn()
        try:
            with c.cursor() as cur:
                cur.execute(sql)
            c.commit()
        finally:
            c.close()

    @classmethod
    def _source_exec(cls, statements):
        c = cls.mod.conn(cls.source)
        try:
            with c.cursor() as cur:
                for sql in statements:
                    cur.execute(sql)
            c.commit()
        finally:
            c.close()

    @classmethod
    def _run(cls, args):
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=str(BASE),
            capture_output=True, text=True, encoding='utf-8', env=env)
        return {'exit': result.returncode, 'stdout': result.stdout,
                'stderr': result.stderr,
                'json': json.loads(result.stdout) if result.stdout.strip().startswith('{')
                else None}

    def test_first_run_partitions_complete(self):
        self.assertEqual(0, self.first['exit'], self.first['stderr'][-1000:])
        recon = self.first['json']['reconciliation']
        self.assertTrue(recon['strict_ok'])
        self.assertTrue(recon['lossless_ok'])
        failed = [c for c in recon['partition']['checks'] if not c['ok']]
        self.assertEqual([], failed, failed)
        self.assertEqual(2, recon['partition']['isolated'].get('app01_major', 0)
                         + recon['partition']['isolated'].get('app01_classes', 0))

    def test_truncation_recorded(self):
        report = self.first['json']
        self.assertTrue(report['ok'])
        with self.mod.conn(self.target) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM pmr_rejected_queue "
                    "WHERE batch_id=%s AND status='truncated'", [self.batch])
                self.assertGreaterEqual(cur.fetchone()[0], 1)

    def test_replay_after_parent_fix(self):
        # 补齐缺失学院（只改合成源库），再受控重放。
        self._source_exec(["INSERT INTO app01_college VALUES (99, '补录学院')"])
        replay = self._run(['--source', self.source, '--target', self.target,
                            '--batch-id', self.batch, '--replay'])
        self.assertEqual(0, replay['exit'], replay['stderr'][-1000:])
        self.assertEqual(0, replay['json']['remaining_count'])
        self.assertGreaterEqual(replay['json']['resolved_count'], 1)

        again = self._run(['--source', self.source, '--target', self.target,
                           '--batch-id', self.batch, '--json'])
        self.assertEqual(0, again['exit'], again['stderr'][-1000:])
        recon = again['json']['reconciliation']
        self.assertTrue(recon['overall_ok'])
        failed = [c for c in recon['partition']['checks'] if not c['ok']]
        self.assertEqual([], failed, failed)
        # 重跑不得重复建组织单元
        self.assertGreaterEqual(again['json']['counters']['skipped'], 1)
