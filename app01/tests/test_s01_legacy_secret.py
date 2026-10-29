"""S01：历史 MD5 密钥泄漏治理的专项测试。

主任务书 S01 的验收点：
1. HEAD 与全历史的密钥使用范围枚举（G0 扫描完成，证据在归档目录）；
2. 新代码禁止硬编码，密钥只能从受限来源注入且**默认不可用**；
3. 密钥不得进入日志、异常文本或审计载荷；
4. MD5 兼容路径**仅**在受控迁移模式下启用；
5. Django ``SECRET_KEY`` 的复用与轮换独立评估（本文件断言两者不共用）。

本文件把上述约定固化为可执行断言，防止治理被回退。
"""
import json
import os
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase

from app01.services import accounts

#: 合成测试密钥：与任何真实历史值无关。
SECRET = 's01-synthetic-test-secret-value'
BASE = Path(__file__).resolve().parents[2]

WITH_SECRET_AND_COMPAT = {
    'SMASS_LEGACY_MD5_SECRET_KEY': SECRET,
    'SMASS_LEGACY_MD5_COMPAT': '1',
}
WITHOUT_ANY = {
    'SMASS_LEGACY_MD5_SECRET_KEY': '',
    'SMASS_LEGACY_MD5_COMPAT': '',
}


class _Account:
    """最小替身，满足 verify_password 的字段需求。"""

    def __init__(self, encoded):
        self.password = encoded
        self.pk = 42
        self._state = type('S', (), {'adding': False})()
        self.saved = []

    def save(self, update_fields=None):
        self.saved.append(tuple(update_fields or ()))


class NoHardcodedSecretTests(TestCase):
    """验收点 2：源码中不得存在可用的历史密钥字面量。"""

    LITERAL_RX = re.compile(
        r'django-insecure-[A-Za-z0-9_\-()*^=!@#$%&+.,:;?/\\|~`\[\]{}<>]{20,}')

    def _scan(self, rel):
        text = (BASE / rel).read_text(encoding='utf-8')
        return self.LITERAL_RX.findall(text)

    def test_accounts_service_has_no_literal(self):
        self.assertEqual(self._scan('app01/services/accounts.py'), [])

    def test_fixture_tool_has_no_literal(self):
        self.assertEqual(self._scan('scripts/pmr_synthetic_fixture.py'), [])

    def test_pmr_report_has_no_literal(self):
        self.assertEqual(self._scan('docs/SMASS_PMR_Executive_Report.md'), [])

    def test_env_loader_does_not_default_the_legacy_key(self):
        """任何生产代码路径都不得为历史密钥提供默认值。"""
        text = (BASE / 'app01/services/accounts.py').read_text(encoding='utf-8')
        # 只允许 os.environ.get(...) 且不出现第二个参数形式的默认值
        for m in re.finditer(r"environ\.get\(\s*LEGACY_MD5_SECRET_KEY_ENV\s*([^)]*)\)", text):
            self.assertEqual(m.group(1).strip(), '',
                             '历史密钥的环境变量读取不得带默认值')


class SecureByDefaultTests(TestCase):
    """验收点 2/4：未注入或未开启迁移模式时，历史 MD5 一律不可用。"""

    def test_status_is_unavailable_without_env(self):
        with mock.patch.dict(os.environ, WITHOUT_ANY, clear=False):
            status = accounts.legacy_md5_compat_status()
            self.assertFalse(status['secret_injected'])
            self.assertFalse(status['compat_enabled'])
            self.assertFalse(status['available'])

    def test_status_unavailable_with_secret_but_compat_off(self):
        env = dict(WITH_SECRET_AND_COMPAT)
        env['SMASS_LEGACY_MD5_COMPAT'] = ''
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertFalse(accounts.legacy_md5_compat_status()['available'])

    def test_status_unavailable_with_compat_but_no_secret(self):
        env = dict(WITH_SECRET_AND_COMPAT)
        env['SMASS_LEGACY_MD5_SECRET_KEY'] = ''
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertFalse(accounts.legacy_md5_compat_status()['available'])

    def test_available_only_when_both_present(self):
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            self.assertTrue(accounts.legacy_md5_compat_status()['available'])

    def test_legacy_verify_rejects_by_default(self):
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            encoded = accounts.legacy_md5('Plain#2024')
        account = _Account(encoded)

        with mock.patch.dict(os.environ, WITHOUT_ANY, clear=False):
            self.assertFalse(accounts.verify_password(account, 'Plain#2024'))
        self.assertEqual(account.saved, [], '拒绝路径不得写库')
        self.assertTrue(accounts.is_legacy_hash(account.password))


class SecretNeverLeaksTests(TestCase):
    """验收点 3：密钥不得出现在日志、异常或状态摘要中。"""

    def test_rejection_log_does_not_contain_secret(self):
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            encoded = accounts.legacy_md5('Plain#2024')
        account = _Account(encoded)

        with mock.patch.dict(os.environ, WITHOUT_ANY, clear=False):
            with self.assertLogs('smass.audit', level='WARNING') as ctx:
                accounts.verify_password(account, 'Plain#2024')
        joined = '\n'.join(ctx.output)
        self.assertNotIn(SECRET, joined)
        self.assertIn('legacy_md5_rejected', joined)
        self.assertIn('reason=compat_disabled', joined)

    def test_secret_not_in_injected_log_does_not_echo_plaintext(self):
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            encoded = accounts.legacy_md5('Plain#2024')
            account = _Account(encoded)
            with self.assertLogs('smass.audit', level='INFO') as ctx:
                accounts.verify_password(account, 'Plain#2024')
        joined = '\n'.join(ctx.output)
        self.assertNotIn(SECRET, joined)
        self.assertNotIn('Plain#2024', joined, '日志中出现明文口令')

    def test_unavailable_exception_does_not_contain_secret(self):
        with mock.patch.dict(os.environ, WITHOUT_ANY, clear=False):
            with self.assertRaises(accounts.LegacyHashUnavailable) as ctx:
                accounts.legacy_md5('x')
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_status_summary_is_metadata_only(self):
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            status = accounts.legacy_md5_compat_status()
        blob = json.dumps(status, ensure_ascii=False)
        self.assertNotIn(SECRET, blob)
        self.assertEqual(set(status), {
            'secret_injected', 'compat_enabled', 'available', 'secret_env', 'compat_env',
        })


class SecretKeySeparationTests(TestCase):
    """验收点 5：Django SECRET_KEY 与历史 MD5 密钥必须独立。"""

    def test_django_secret_differs_from_legacy_secret(self):
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            self.assertNotEqual(accounts.legacy_md5_secret(), settings.SECRET_KEY)

    def test_legacy_secret_is_not_read_from_django_settings(self):
        """历史密钥只能来自环境变量，不得复用 settings.SECRET_KEY。"""
        text = (BASE / 'app01/services/accounts.py').read_text(encoding='utf-8')
        self.assertIn('LEGACY_MD5_SECRET_KEY_ENV', text)
        self.assertNotIn('secret_key=settings.SECRET_KEY', text)

    def test_encrypt_util_requires_explicit_secret_for_legacy(self):
        """底层工具在显式传密钥时才复现历史实现（不隐式取当前 SECRET_KEY）。"""
        from app01.utils.encrypt import md5 as legacy_md5_util
        with mock.patch.dict(os.environ, WITH_SECRET_AND_COMPAT, clear=False):
            explicit = legacy_md5_util('x', secret_key=accounts.legacy_md5_secret())
            implicit = legacy_md5_util('x')
        self.assertEqual(len(explicit), 32)
        self.assertNotEqual(explicit, implicit,
                            '显式历史密钥与当前 SECRET_KEY 求出的哈希不应相同')
