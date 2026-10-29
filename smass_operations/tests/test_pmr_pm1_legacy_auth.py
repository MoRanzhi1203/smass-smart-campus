"""PM1：旧密码格式兼容（全合成，不涉及任何真实哈希）。

源码依据（`app01/services/accounts.py` + `app01/utils/encrypt.py`）：

- 旧格式：32 位小写十六进制 MD5
- 计算：`md5(LEGACY_MD5_SECRET_KEY.encode() + raw.encode())`
- 兼容两种历史数据：
  - 单次哈希：`md5(secret + raw)`
  - **双重哈希**（旧 `save()` 重复哈希的坏数据）：`md5(secret + md5(secret + raw))`
- 比较用 `secrets.compare_digest`（常量时间）
- 命中后懒惰升级为 Django PBKDF2
- 密钥 `LEGACY_MD5_SECRET_KEY` **硬编码在源码中且已泄漏**（历史事实，本测试只记录不断言可利用）

所有哈希均由本测试用**合成明文**现场计算，不读取任何真实行。
"""
import hashlib
import json
import os
from unittest import mock

from django.test import TestCase

# S01 治理后历史密钥不再硬编码：本测试用**合成测试密钥**注入。
# 这样既不需要、也不依赖真实泄漏值，同时覆盖"注入后才可用"的路径。
_TEST_SECRET = 'pmr-pm1-synthetic-test-key'
os.environ.setdefault('SMASS_LEGACY_MD5_SECRET_KEY', _TEST_SECRET)
os.environ.setdefault('SMASS_LEGACY_MD5_COMPAT', '1')

from app01.services import accounts as legacy  # noqa: E402
from app01.utils.encrypt import md5 as legacy_md5_util  # noqa: E402

SYNTHETIC_PASSWORD = 'PmrSynthetic#2024'


def tearDownModule():
    """不把测试用的密钥/开关泄漏给其它测试模块。"""
    if os.environ.get('SMASS_LEGACY_MD5_SECRET_KEY') == _TEST_SECRET:
        os.environ.pop('SMASS_LEGACY_MD5_SECRET_KEY', None)
    if os.environ.get('SMASS_LEGACY_MD5_COMPAT') == '1':
        os.environ.pop('SMASS_LEGACY_MD5_COMPAT', None)


def synth_md5(raw, secret=None):
    """合成 MD5，与 `app01.utils.encrypt.md5` 等价（此处独立实现以做交叉验证）。"""
    key = secret if secret is not None else legacy.LEGACY_MD5_SECRET_KEY
    return hashlib.md5(key.encode('utf-8') + raw.encode('utf-8')).hexdigest()


class FormatDetectionTests(TestCase):
    def test_32_hex_is_legacy(self):
        value = synth_md5(SYNTHETIC_PASSWORD)
        self.assertEqual(len(value), 32)
        self.assertTrue(legacy.is_legacy_hash(value))

    def test_uppercase_hex_not_matched(self):
        """正则只认小写：大写 32 位不被识别为 legacy（避免误升级）。"""
        self.assertFalse(legacy.is_legacy_hash(synth_md5('x').upper()))

    def test_django_hash_not_legacy(self):
        from django.contrib.auth.hashers import make_password
        encoded = make_password('anything')
        self.assertFalse(legacy.is_legacy_hash(encoded))
        self.assertTrue(legacy.is_preferred_hash(encoded))

    def test_short_or_long_hex_not_legacy(self):
        self.assertFalse(legacy.is_legacy_hash('a' * 31))
        self.assertFalse(legacy.is_legacy_hash('a' * 33))

    def test_non_hex_not_legacy(self):
        self.assertFalse(legacy.is_legacy_hash('z' * 32))
        self.assertFalse(legacy.is_legacy_hash(''))

    def test_none_not_legacy(self):
        self.assertFalse(legacy.is_legacy_hash(None))


class Md5EquivalenceTests(TestCase):
    """交叉验证：服务层 `legacy_md5` 与独立实现一致。"""

    def test_service_matches_independent(self):
        self.assertEqual(
            legacy.legacy_md5(SYNTHETIC_PASSWORD),
            synth_md5(SYNTHETIC_PASSWORD))

    def test_util_matches_independent(self):
        self.assertEqual(
            legacy_md5_util(SYNTHETIC_PASSWORD,
                            secret_key=legacy.LEGACY_MD5_SECRET_KEY),
            synth_md5(SYNTHETIC_PASSWORD))

    def test_different_password_different_hash(self):
        self.assertNotEqual(
            synth_md5('a'), synth_md5('b'))

    def test_secret_affects_hash(self):
        self.assertNotEqual(synth_md5('x', secret='k1'),
                            synth_md5('x', secret='k2'))


class _FakeAccount:
    """最小替身：只提供 verify_password 需要的字段。"""

    def __init__(self, encoded):
        self.password = encoded
        self.pk = 1
        self._state = type('S', (), {'adding': False})()
        self.saved = []

    def save(self, update_fields=None):
        self.saved.append(tuple(update_fields or ()))


class LegacyVerifyTests(TestCase):
    def test_single_md5_accepted(self):
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        self.assertTrue(legacy.verify_password(account, SYNTHETIC_PASSWORD))

    def test_single_md5_upgraded_on_success(self):
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        legacy.verify_password(account, SYNTHETIC_PASSWORD)

        self.assertFalse(legacy.is_legacy_hash(account.password),
                         '命中后未升级为官方哈希')
        self.assertTrue(legacy.is_preferred_hash(account.password))
        self.assertIn(('password',), account.saved)

    def test_double_md5_accepted(self):
        """旧 save() 重复哈希的坏数据：md5(secret + md5(secret + raw))。"""
        once = synth_md5(SYNTHETIC_PASSWORD)
        twice = synth_md5(once)

        account = _FakeAccount(twice)
        self.assertTrue(legacy.verify_password(account, SYNTHETIC_PASSWORD))

    def test_double_md5_also_upgraded(self):
        once = synth_md5(SYNTHETIC_PASSWORD)
        twice = synth_md5(once)
        account = _FakeAccount(twice)

        legacy.verify_password(account, SYNTHETIC_PASSWORD)
        self.assertTrue(legacy.is_preferred_hash(account.password))

    def test_wrong_password_rejected(self):
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        self.assertFalse(legacy.verify_password(account, 'WrongPass#2024'))
        # 拒绝时不得改动存储
        self.assertTrue(legacy.is_legacy_hash(account.password))
        self.assertEqual(account.saved, [])

    def test_empty_password_rejected(self):
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        self.assertFalse(legacy.verify_password(account, ''))
        self.assertFalse(legacy.verify_password(None, SYNTHETIC_PASSWORD))

    def test_empty_stored_hash_rejected(self):
        self.assertFalse(legacy.verify_password(_FakeAccount(''), SYNTHETIC_PASSWORD))

    def test_upgraded_hash_accepts_same_password(self):
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        legacy.verify_password(account, SYNTHETIC_PASSWORD)

        # 升级后仍能验证（走官方哈希分支）
        self.assertTrue(legacy.verify_password(account, SYNTHETIC_PASSWORD))
        self.assertFalse(legacy.is_legacy_hash(account.password))

    def test_upgraded_hash_rejects_old_md5_reuse(self):
        """升级后，把旧 MD5 当密码传入必须被拒绝。"""
        old = synth_md5(SYNTHETIC_PASSWORD)
        account = _FakeAccount(old)
        legacy.verify_password(account, SYNTHETIC_PASSWORD)

        self.assertFalse(legacy.verify_password(account, old))

    def test_unknown_format_rejected_not_crash(self):
        account = _FakeAccount('not-a-valid-encoded-hash')
        # Django check_password 对无法识别的编码返回 False 或抛错，
        # 服务层必须拒绝且不崩
        try:
            result = legacy.verify_password(account, SYNTHETIC_PASSWORD)
        except Exception as exc:  # noqa: BLE001
            self.fail('未知格式导致异常: {}'.format(type(exc).__name__))
        self.assertFalse(result)


class OfficialHashTests(TestCase):
    def test_pbkdf2_accepted(self):
        from django.contrib.auth.hashers import make_password
        encoded = make_password(SYNTHETIC_PASSWORD)

        account = _FakeAccount(encoded)
        self.assertTrue(legacy.verify_password(account, SYNTHETIC_PASSWORD))

    def test_pbkdf2_wrong_rejected(self):
        from django.contrib.auth.hashers import make_password
        encoded = make_password(SYNTHETIC_PASSWORD)

        account = _FakeAccount(encoded)
        self.assertFalse(legacy.verify_password(account, 'nope'))

    def test_set_password_writes_official_hash(self):
        account = _FakeAccount('')
        legacy.set_password(account, SYNTHETIC_PASSWORD)

        self.assertTrue(legacy.is_preferred_hash(account.password))
        self.assertNotIn(SYNTHETIC_PASSWORD, account.password,
                         '存储中出现了明文')

    def test_set_password_empty_rejected(self):
        account = _FakeAccount('')
        with self.assertRaises(legacy.PasswordError):
            legacy.set_password(account, '')


class KeyLeakGovernanceTests(TestCase):
    """S01 治理后的事实：旧 MD5 密钥**不再硬编码**，只能从受限来源注入。

    这组断言把"治理是否真的生效"固定下来，防止后续把密钥塞回源码，
    也防止有人误以为密钥仍以明文常量形式存在。
    """

    def test_no_django_insecure_literal_in_accounts_source(self):
        """accounts.py 中不得残留任何 django-insecure- 密钥字面量。"""
        import re
        from pathlib import Path
        base = Path(__file__).resolve().parents[2]
        source = base / 'app01' / 'services' / 'accounts.py'
        text = source.read_text(encoding='utf-8')
        literals = re.findall(
            r'django-insecure-[A-Za-z0-9_\-()*^=!@#$%&+.,:;?/\\|~`\[\]{}<>]{20,}',
            text,
        )
        self.assertEqual(literals, [],
                         'accounts.py 中仍存在 django-insecure- 字面量（应改为环境注入）')

    def test_no_django_insecure_literal_in_fixture_tool(self):
        """生成合成数据的脚本同样不得硬编码密钥。"""
        import re
        from pathlib import Path
        base = Path(__file__).resolve().parents[2]
        source = base / 'scripts' / 'pmr_synthetic_fixture.py'
        text = source.read_text(encoding='utf-8')
        literals = re.findall(
            r'django-insecure-[A-Za-z0-9_\-()*^=!@#$%&+.,:;?/\\|~`\[\]{}<>]{20,}',
            text,
        )
        self.assertEqual(literals, [])

    def test_secret_read_from_environment(self):
        """密钥来自环境变量，模块属性是它的动态镜像。"""
        self.assertEqual(legacy.legacy_md5_secret(), _TEST_SECRET)
        self.assertEqual(legacy.LEGACY_MD5_SECRET_KEY, _TEST_SECRET)

    def test_compat_flag_is_off_without_env(self):
        """迁移开关默认关闭。"""
        with mock.patch.dict(os.environ, {'SMASS_LEGACY_MD5_COMPAT': ''}, clear=False):
            self.assertFalse(legacy.legacy_md5_compat_enabled())

    def test_legacy_verify_denied_when_compat_off(self):
        """未开启迁移模式时，历史 MD5 账号必须被拒绝（安全默认），且不得升级。"""
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        with mock.patch.dict(os.environ, {'SMASS_LEGACY_MD5_COMPAT': ''}, clear=False):
            self.assertFalse(legacy.verify_password(account, SYNTHETIC_PASSWORD))
        self.assertEqual(account.saved, [], '被拒绝时不得写入/升级')
        self.assertTrue(legacy.is_legacy_hash(account.password))

    def test_legacy_verify_denied_when_secret_missing(self):
        """未注入密钥时同样拒绝，而不是抛异常。"""
        account = _FakeAccount(synth_md5(SYNTHETIC_PASSWORD))
        with mock.patch.dict(os.environ, {'SMASS_LEGACY_MD5_SECRET_KEY': ''}, clear=False):
            self.assertFalse(legacy.verify_password(account, SYNTHETIC_PASSWORD))
        self.assertEqual(account.saved, [])

    def test_legacy_md5_raises_without_secret(self):
        """无密钥时低层工具明确报错，而不是静默算出可误用的哈希。"""
        with mock.patch.dict(os.environ, {'SMASS_LEGACY_MD5_SECRET_KEY': ''}, clear=False):
            with self.assertRaises(legacy.LegacyHashUnavailable):
                legacy.legacy_md5('any-plain')

    def test_compat_status_never_contains_secret(self):
        """运维状态摘要不得回显密钥本身。"""
        status = legacy.legacy_md5_compat_status()
        blob = json.dumps(status, ensure_ascii=False)
        self.assertNotIn(_TEST_SECRET, blob)
        self.assertTrue(status['secret_injected'])
        self.assertTrue(status['compat_enabled'])
        self.assertTrue(status['available'])
        self.assertIn('SMASS_LEGACY_MD5_SECRET_KEY', status['secret_env'])


class RateLimitConstantsTests(TestCase):
    """限速参数存在且为合理值（不做时间依赖的集成测试）。"""

    def test_limits_defined(self):
        self.assertEqual(legacy.LOGIN_MAX_FAILURES, 5)
        self.assertEqual(legacy.LOGIN_LOCK_SECONDS, 300)

    def test_session_lock_and_unlock(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        factory = RequestFactory()
        request = factory.get('/')
        request.session = SessionStore()

        self.assertEqual(legacy.login_lock_remaining(request), 0)

        for _ in range(legacy.LOGIN_MAX_FAILURES):
            legacy.register_login_failure(request)

        self.assertGreater(legacy.login_lock_remaining(request), 0,
                           '达到阈值后未锁定')

        legacy.clear_login_failures(request)
        self.assertEqual(legacy.login_lock_remaining(request), 0)
