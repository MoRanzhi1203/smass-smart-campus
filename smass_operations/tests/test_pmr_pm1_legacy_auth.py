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

from django.test import TestCase

from app01.services import accounts as legacy
from app01.utils.encrypt import md5 as legacy_md5_util

SYNTHETIC_PASSWORD = 'PmrSynthetic#2024'


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


class KeyLeakRecordTests(TestCase):
    """记录事实：旧 MD5 密钥硬编码在源码中。

    这不是"测试通过"，而是**把风险固化成断言**，防止有人误以为密钥安全。
    """

    def test_legacy_key_is_hardcoded_in_source(self):
        """断言结构性特征，不硬编码长度（长度易变，特征不会）。"""
        key = legacy.LEGACY_MD5_SECRET_KEY
        self.assertTrue(key)
        self.assertTrue(key.startswith('django-insecure-'),
                        '旧密钥应带 Django 自动生成前缀')
        self.assertGreater(len(key), 40, '密钥长度异常')
        self.assertGreaterEqual(len(set(key)), 10, '密钥熵过低（可能是占位）')

    def test_legacy_key_differs_from_current_secret(self):
        """旧密钥与当前 SECRET_KEY 不同——否则会误判为"当前密钥仍安全"。"""
        from django.conf import settings
        self.assertNotEqual(legacy.LEGACY_MD5_SECRET_KEY, settings.SECRET_KEY)

    def test_key_present_in_repo_source(self):
        """确认密钥确实在仓库源码里（泄漏事实）。"""
        from pathlib import Path
        base = Path(__file__).resolve().parents[2]
        source = base / 'app01' / 'services' / 'accounts.py'
        text = source.read_text(encoding='utf-8')
        self.assertIn('LEGACY_MD5_SECRET_KEY', text)


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
