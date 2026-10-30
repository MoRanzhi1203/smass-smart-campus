"""S07：密钥与配置管理的可执行验收。

覆盖：
- 生产模式（DEBUG=False）缺少 SECRET_KEY 必须启动失败；
- 生产模式提供密钥后，安全 Cookie / nosniff 默认生效；
- 秘密扫描器的模式能命中合成凭据，开发默认值被正确识别；
- `.env.example` 不含真实密钥；
- 全仓扫描无 ISSUE（与 `scripts/r9_secret_scan.py` 同一实现）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE = Path(__file__).resolve().parents[2]
SCANNER = BASE / 'scripts' / 'r9_secret_scan.py'


def load_scanner():
    spec = importlib.util.spec_from_file_location('r9_secret_scan', SCANNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductionSecretTests(SimpleTestCase):
    def _run(self, env_extra, *, code, remove=()):
        env = os.environ.copy()
        for key in remove:
            env.pop(key, None)
        env.update(env_extra)
        env['PYTHONPATH'] = str(BASE)
        return subprocess.run(
            [sys.executable, '-c', code], cwd=str(BASE), env=env,
            capture_output=True, text=True, encoding='utf-8')

    def test_missing_secret_key_fails_fast(self):
        result = self._run(
            {'DJANGO_DEBUG': 'False'},
            code='import smass.settings',
            remove=('DJANGO_SECRET_KEY',))
        self.assertNotEqual(0, result.returncode)
        self.assertIn('DJANGO_SECRET_KEY', result.stderr + result.stdout)

    def test_production_defaults_enabled(self):
        code = (
            'import json, smass.settings as s;'
            'print(json.dumps({'
            '"debug": s.DEBUG,'
            '"session_httponly": s.SESSION_COOKIE_HTTPONLY,'
            '"session_secure": s.SESSION_COOKIE_SECURE,'
            '"csrf_secure": s.CSRF_COOKIE_SECURE,'
            '"nosniff": s.SECURE_CONTENT_TYPE_NOSNIFF,'
            '"samesite": s.SESSION_COOKIE_SAMESITE}))'
        )
        result = self._run(
            {'DJANGO_DEBUG': 'False',
             'DJANGO_SECRET_KEY': secrets.token_urlsafe(50),
             'DJANGO_ALLOWED_HOSTS': 'example.com'},
            code=code)
        self.assertEqual(0, result.returncode, result.stderr[-800:])
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(payload['debug'])
        self.assertTrue(payload['session_httponly'])
        self.assertTrue(payload['session_secure'])
        self.assertTrue(payload['csrf_secure'])
        self.assertTrue(payload['nosniff'])
        self.assertEqual('Lax', payload['samesite'])


class SecretScannerTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mod = load_scanner()

    def test_patterns_catch_synthetic_secret(self):
        text = 'password = "SuperSecret123"'
        names = [name for name, pattern in self.mod.PATTERNS
                 if pattern.search(text)]
        self.assertIn('HARDCODED_PASSWORD', names)

        aws = 'AKIA' + 'A' * 16
        names = [name for name, pattern in self.mod.PATTERNS
                 if pattern.search(aws)]
        self.assertIn('AWS_KEY', names)

    def test_dev_placeholder_recognized(self):
        self.assertTrue(self.mod.is_dev_placeholder(
            'django-insecure-dev-only-please-set-DJANGO_SECRET_KEY'))
        self.assertFalse(self.mod.is_dev_placeholder('real-secret-value'))

    def test_env_example_has_no_real_secret(self):
        text = (BASE / '.env.example').read_text(encoding='utf-8')
        self.assertNotIn('django-insecure-', text)
        self.assertNotIn('AKIA', text)
        self.assertNotIn('ghp_', text)

    def test_repository_scan_has_no_issue(self):
        findings = self.mod.scan()
        issues = [f for f in findings if f.get('severity') == 'ISSUE']
        self.assertEqual([], issues, issues[:5])
