"""PM2：合成旧数据集生成器的单元测试（纯函数，不连数据库）。

生成器本体在 `scripts/pmr_synthetic_fixture.py`；本文件只测其**确定性**
与**无 PII** 保证，实际的库创建在 `scripts/pmr_synthetic_fixture.py` 运行时验证。
"""
import hashlib
import importlib.util
import os
import random
import re
from pathlib import Path

from django.test import TestCase

BASE = Path(__file__).resolve().parents[2]

# S01 治理后生成器不再硬编码历史密钥：测试时注入**合成密钥**，
# 使 fixture 模块在 exec_module 时能读到非空值。
_TEST_SECRET = 'pmr-pm2-synthetic-test-key'
os.environ.setdefault('SMASS_LEGACY_MD5_SECRET_KEY', _TEST_SECRET)


def tearDownModule():
    if os.environ.get('SMASS_LEGACY_MD5_SECRET_KEY') == _TEST_SECRET:
        os.environ.pop('SMASS_LEGACY_MD5_SECRET_KEY', None)


def load_fixture_module():
    # 幂等注入：不依赖其它测试模块的 tearDownModule 是否已经清理过环境变量。
    os.environ.setdefault('SMASS_LEGACY_MD5_SECRET_KEY', _TEST_SECRET)
    path = BASE / 'scripts' / 'pmr_synthetic_fixture.py'
    spec = importlib.util.spec_from_file_location('pmr_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixtureModuleTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_fixture_module()

    # ---- 密码编码 ----
    def test_legacy_md5_matches_independent(self):
        raw = 'Synth#2024'
        expected = hashlib.md5(
            (self.mod.LEGACY_MD5_SECRET_KEY + raw).encode('utf-8')).hexdigest()
        self.assertEqual(self.mod.legacy_md5(raw), expected)

    def test_legacy_md5_is_32_hex(self):
        self.assertRegex(self.mod.legacy_md5('x'), r'^[0-9a-f]{32}$')

    def test_double_md5_differs_from_single(self):
        raw = 'Synth#2024'
        once = self.mod.legacy_md5(raw)
        twice = self.mod.legacy_md5(once)
        self.assertNotEqual(once, twice)
        self.assertRegex(twice, r'^[0-9a-f]{32}$')

    def test_pbkdf2_is_django_format(self):
        encoded = self.mod.pbkdf2('Synth#2024')
        self.assertTrue(encoded.startswith('pbkdf2_sha256$'))

    def test_encode_password_dispatch(self):
        raw = 'Synth#2024'
        self.assertEqual(self.mod.encode_password(raw, 'legacy_md5_single'),
                         self.mod.legacy_md5(raw))
        self.assertEqual(self.mod.encode_password(raw, 'legacy_md5_double'),
                         self.mod.legacy_md5(self.mod.legacy_md5(raw)))
        self.assertTrue(
            self.mod.encode_password(raw, 'pbkdf2').startswith('pbkdf2_sha256$'))

    # ---- 合成内容 ----
    def test_synth_name_deterministic(self):
        rng = random.Random(1)
        a = self.mod.synth_name(rng, 7)
        rng2 = random.Random(1)
        b = self.mod.synth_name(rng2, 7)
        self.assertEqual(a, b)

    def test_synth_name_has_index_suffix(self):
        rng = random.Random(1)
        name = self.mod.synth_name(rng, 42)
        self.assertTrue(name.endswith('0042'), '合成姓名应带序号后缀，便于追溯')

    def test_synth_card_id_not_real_id_format(self):
        """合成证件号必须**不是** 18 位身份证格式。"""
        card = self.mod.synth_card_id(1)
        self.assertTrue(card.startswith('SYNTH'))
        self.assertFalse(re.match(r'^\d{17}[\dXx]$', card),
                         '合成证件号不得误用真实身份证格式')

    def test_synth_phone_not_real_mobile(self):
        """合成手机号以 000 开头，真实号码不会出现。"""
        phone = self.mod.synth_phone(1)
        self.assertTrue(phone.startswith('000'))
        self.assertFalse(re.match(r'^1[3-9]\d{9}$', phone))

    def test_synth_password_has_marker(self):
        pw = self.mod.synth_password(3)
        self.assertTrue(pw.startswith('PmrSynth#'))

    # ---- 格式分布 ----
    def test_pick_format_returns_known(self):
        rng = random.Random(99)
        known = {name for name, _ in self.mod.FORMAT_WEIGHTS}
        for _ in range(200):
            self.assertIn(self.mod.pick_format(rng), known)

    def test_pick_format_covers_all_branches(self):
        rng = random.Random(7)
        seen = {self.mod.pick_format(rng) for _ in range(500)}
        self.assertEqual(seen, {name for name, _ in self.mod.FORMAT_WEIGHTS},
                         '500 次抽样应覆盖全部三种格式')

    def test_format_weights_sum_to_one(self):
        total = sum(weight for _, weight in self.mod.FORMAT_WEIGHTS)
        self.assertAlmostEqual(total, 1.0, places=6)

    # ---- 守卫 ----
    def test_guard_rejects_non_pmr_prefix(self):
        for bad in ('smass', 'smass_r10_release', 'test_smass', 'smass_h5_clone_x'):
            with self.assertRaises(SystemExit):
                self.mod.guard_db_name(bad)

    def test_guard_accepts_pmr_prefix(self):
        self.mod.guard_db_name('smass_pmr_tiny_1')  # 不应抛

    # ---- 对抗用例 ----
    def test_adversarial_cases_complete(self):
        labels = {label for label, _ in self.mod.ADVERSARIAL_CASES}
        self.assertEqual(labels, {
            'empty_hash', 'short_hash', 'long_hash',
            'uppercase_hash', 'non_hex_hash',
        })

    def test_adversarial_cases_are_adversarial(self):
        mod = self.mod
        by_label = dict(mod.ADVERSARIAL_CASES)
        self.assertEqual(by_label['empty_hash'], '')
        self.assertEqual(len(by_label['short_hash']), 31)
        self.assertEqual(len(by_label['long_hash']), 33)
        self.assertEqual(by_label['uppercase_hash'], 'A' * 32)
        self.assertEqual(by_label['non_hex_hash'], 'z' * 32)

        # 除空串外，其余都不应被识别为合法 legacy MD5
        from app01.services.accounts import is_legacy_hash
        for label, value in mod.ADVERSARIAL_CASES:
            if label in ('short_hash', 'long_hash', 'uppercase_hash', 'non_hex_hash'):
                self.assertFalse(is_legacy_hash(value),
                                 '{} 不应被识别为 legacy MD5'.format(label))

    # ---- 规模 ----
    def test_scales_defined(self):
        self.assertEqual(sorted(self.mod.SCALES),
                         ['10k', '1k', 'medium', 'tiny'])
        self.assertEqual(self.mod.SCALES['tiny'], 10)
        self.assertEqual(self.mod.SCALES['10k'], 10000)

    def test_db_prefix_is_pmr(self):
        self.assertEqual(self.mod.DB_PREFIX, 'smass_pmr_')
