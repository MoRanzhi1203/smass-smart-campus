"""S14 真实浏览器 E2E（Playwright + Chromium）。

覆盖：学生通过浏览器上传 PNG → 列表显示 → 点击下载拿到原文件；
上传伪造 PNG 时页面显示拒绝原因。
"""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_uploads.models import UploadedFile

try:
    from playwright.sync_api import sync_playwright
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)
PASSWORD = 'S14Browser#2026'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='e2e')
    return Account.objects.get(pk=account.pk)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class S14BrowserFlowTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        try:
            cls.browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('Chromium 启动失败：{}'.format(exc))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp(prefix='smass-s14-e2e-')
        self.override = override_settings(SMASS_PRIVATE_MEDIA_ROOT=self.tmpdir)
        self.override.enable()

        self.student = make_account('S14E2ES', [RoleCode.STUDENT])
        self.context = self.browser.new_context(
            viewport={'width': 1366, 'height': 900})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def tearDown(self):
        try:
            self.context.close()
        finally:
            self.override.disable()
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            super().tearDown()

    def _login(self, page):
        page.goto(self.live_server_url + '/r21/login/')
        page.fill('input[name=login_name]', 'S14E2ES')
        page.fill('input[name=password]', PASSWORD)
        page.click('button[type=submit]')

    def _write_file(self, name, data):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'wb') as handle:
            handle.write(data)
        return path

    def test_upload_and_download(self):
        good = self._write_file('good.png', PNG_BYTES)
        bad = self._write_file('bad.png', b'not a png')

        self._login(self.page)
        self.page.goto(self.live_server_url + '/uploads/')
        self.page.set_input_files('input[name=file]', good)
        self.page.click('form[action="/uploads/upload/"] button[type=submit]')
        self.assertIn('上传成功', self.page.content())
        self.assertIn('good.png', self.page.content())

        record = UploadedFile.objects.get(owner=self.student)
        self.assertEqual(record.original_name, 'good.png')

        with self.page.expect_download() as download_info:
            self.page.click('a[href="/uploads/{}/download/"]'.format(record.pk))
        download = download_info.value
        path = download.path()
        with open(path, 'rb') as handle:
            self.assertEqual(handle.read(), PNG_BYTES)

        self.page.goto(self.live_server_url + '/uploads/')
        self.page.set_input_files('input[name=file]', bad)
        self.page.click('form[action="/uploads/upload/"] button[type=submit]')
        self.assertIn('文件签名与扩展名不符', self.page.content())
        self.assertEqual(UploadedFile.objects.count(), 1)
