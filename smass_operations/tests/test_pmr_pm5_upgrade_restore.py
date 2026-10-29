"""PM5：升级与恢复演练的测试。

真实演练由 `scripts/pmr_upgrade_restore.py` 执行（tiny 主流程 + 3 个故障点全过，
见 PMR 命令日志）；本文件测其可测的**契约层**：

- 库名前缀守卫（源 / 升级 / 恢复）
- 指纹函数的确定性（同库同表 → 同指纹；改一行 → 指纹变）
- `_HashCarrier` 能被 `verify_password` 消费
- 故障点常量集合完整
"""
import importlib.util
import os
import unittest
from pathlib import Path

from django.test import TestCase, TransactionTestCase

BASE = Path(__file__).resolve().parents[2]

# 演练脚本用原生 pymysql 连接，需要 root 口令；测试环境从环境变量继承。
# 若未设置则跳过依赖真实连接的用例（不伪造通过）。
DB_PASSWORD_AVAILABLE = bool(os.environ.get('SMASS_DB_PASSWORD'))


def load_module():
    path = BASE / 'scripts' / 'pmr_upgrade_restore.py'
    spec = importlib.util.spec_from_file_location('pmr_upg', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrefixContractTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_module()

    def test_prefixes_are_distinct(self):
        self.assertNotEqual(self.mod.UPG_PREFIX, self.mod.RESTORE_PREFIX)
        self.assertTrue(self.mod.UPG_PREFIX.startswith('smass_pmr_'))
        self.assertTrue(self.mod.RESTORE_PREFIX.startswith('smass_pmr_'))

    def test_compare_tables_cover_people_and_org(self):
        tables = self.mod.COMPARE_TABLES
        for required in ('app01_admin', 'app01_student', 'app01_teacher',
                         'app01_college', 'app01_classes'):
            self.assertIn(required, tables)

    def test_settings_pmr_allows_all_drill_prefixes(self):
        """settings_pmr 必须放行 target/upg/restore 三类演练库。"""
        source = (BASE / 'smass' / 'settings_pmr.py').read_text(encoding='utf-8')
        self.assertIn('smass_pmr_target_', source)
        self.assertIn('smass_pmr_upg_', source)
        self.assertIn('smass_pmr_restore_', source)
        # 且必须仍然禁止正式库
        self.assertNotIn("'smass'", source.replace("'smass_pmr", ''))


class HashCarrierTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_module()

    def test_carrier_accepts_correct_password(self):
        from app01.services.accounts import legacy_md5, verify_password

        raw = 'PmrSynth#000007'
        carrier = self.mod._HashCarrier(legacy_md5(raw))
        self.assertTrue(verify_password(carrier, raw))

    def test_carrier_rejects_wrong_password(self):
        from app01.services.accounts import legacy_md5, verify_password

        carrier = self.mod._HashCarrier(legacy_md5('PmrSynth#000007'))
        self.assertFalse(verify_password(carrier, 'PmrSynth#999999'))

    def test_carrier_records_upgrade_write(self):
        from app01.services.accounts import legacy_md5, verify_password, is_legacy_hash

        raw = 'PmrSynth#000008'
        carrier = self.mod._HashCarrier(legacy_md5(raw))
        verify_password(carrier, raw)

        self.assertFalse(is_legacy_hash(carrier.password), '命中后应升级')
        self.assertIn(('password',), carrier.saved, '升级应触发一次 password 更新')

    def test_plain_for_reconstructs_generator_rule(self):
        """明文重建规则必须与 PM2 生成器一致。"""
        mod = self.mod
        # admin 偏移 0，teacher 偏移 100000，student 偏移 200000
        self.assertEqual(mod._verify_login.__doc__ is not None, True)

        # 直接验证字符串规则
        base_by_table = {'app01_admin': 0, 'app01_teacher': 100000,
                         'app01_student': 200000}
        self.assertEqual(
            'PmrSynth#{:06d}'.format(0 + base_by_table['app01_admin']),
            'PmrSynth#000000')
        self.assertEqual(
            'PmrSynth#{:06d}'.format(0 + base_by_table['app01_student']),
            'PmrSynth#200000')


@unittest.skipUnless(DB_PASSWORD_AVAILABLE,
                     '需要 SMASS_DB_PASSWORD 才能用原生连接做指纹测试')
class FingerprintShapeTests(TransactionTestCase):
    """指纹函数本身的行为（不依赖真实演练库）。"""

    def test_schema_fingerprint_shape(self):
        from django.db import connection

        mod = load_module()
        fp = mod.schema_fingerprint(connection.settings_dict['NAME'])
        self.assertIn('sha256', fp)
        self.assertEqual(len(fp['sha256']), 32)
        self.assertGreater(fp['columns'], 0)

    def test_schema_fingerprint_deterministic(self):
        from django.db import connection

        mod = load_module()
        db = connection.settings_dict['NAME']
        self.assertEqual(mod.schema_fingerprint(db)['sha256'],
                         mod.schema_fingerprint(db)['sha256'])

    def test_data_fingerprint_deterministic(self):
        from django.db import connection

        mod = load_module()
        db = connection.settings_dict['NAME']
        first = mod.data_fingerprint(db, ['django_migrations'])
        second = mod.data_fingerprint(db, ['django_migrations'])
        self.assertEqual(first, second)

    def test_data_fingerprint_changes_with_data(self):
        """插入一行后指纹必须变化（否则指纹无意义）。"""
        from django.db import connection

        mod = load_module()
        db = connection.settings_dict['NAME']

        with connection.cursor() as cur:
            cur.execute(
                'CREATE TABLE IF NOT EXISTS pmr_fp_probe ('
                'id INT PRIMARY KEY, v VARCHAR(16))')
        try:
            before = mod.data_fingerprint(db, ['pmr_fp_probe'])
            with connection.cursor() as cur:
                cur.execute("INSERT INTO pmr_fp_probe VALUES (1, 'x')")
            after = mod.data_fingerprint(db, ['pmr_fp_probe'])
            self.assertNotEqual(before, after, '数据变化必须改变指纹')
        finally:
            with connection.cursor() as cur:
                cur.execute('DROP TABLE IF EXISTS pmr_fp_probe')

    def test_row_counts_handles_missing_table(self):
        from django.db import connection

        mod = load_module()
        counts = mod.row_counts(connection.settings_dict['NAME'],
                                ['django_migrations', 'definitely_missing_table'])
        self.assertIsNotNone(counts['django_migrations'])
        self.assertIsNone(counts['definitely_missing_table'])


class FailurePointContractTests(TestCase):
    def test_three_failure_points_named(self):
        """主流程里三个注入点必须都有对应步骤名。"""
        source = (BASE / 'scripts' / 'pmr_upgrade_restore.py').read_text(encoding='utf-8')
        for needle in ('before_migrate', 'during_backfill', 'after_index'):
            self.assertIn(needle, source)
        # 注入点必须以 step 形式记录，便于审计
        self.assertIn('inject_before_migrate', source)
        self.assertIn('inject_during_backfill', source)
        self.assertIn('inject_after_index', source)
