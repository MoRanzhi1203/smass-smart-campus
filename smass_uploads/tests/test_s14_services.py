"""S14 服务层：扩展名/签名/大小/ZIP 炸弹/归属校验。

运行::

    python manage.py test smass_uploads.tests.test_s14_services --settings=smass.settings_s14
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_uploads import services
from smass_uploads.models import UploadedFile

PASSWORD = 'S14Svc#2026'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
PDF_BYTES = b'%PDF-1.4\n' + b'0' * 64


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def upload(name, data, content_type='application/octet-stream'):
    return SimpleUploadedFile(name, data, content_type=content_type)


def make_zip_bomb():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('big.txt', b'a' * (2 * 1024 * 1024))
    buffer.seek(0)
    return buffer.getvalue()


class UploadBase(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='smass-s14-')
        self.override = override_settings(SMASS_PRIVATE_MEDIA_ROOT=self.tmpdir)
        self.override.enable()

        self.admin = make_account('s14admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s14stu', [RoleCode.STUDENT])
        self.other = make_account('s14other', [RoleCode.STUDENT])

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()


class ValidateTests(UploadBase):
    def test_png_upload_ok(self):
        record = services.store(upload('头像.png', PNG_BYTES, 'image/png'),
                                self.student, 'avatar')
        self.assertEqual(record.status, 'ready')
        self.assertEqual(record.size, len(PNG_BYTES))
        self.assertTrue(record.stored_name.endswith('.png'))
        path = services.path_for(record)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.startswith(self.tmpdir))
        self.assertNotIn('头像', path)  # 落盘名不含原始名

    def test_fake_png_rejected(self):
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('fake.png', b'not a real png'),
                           self.student, 'avatar')
        self.assertEqual(ctx.exception.code, 'BAD_SIGNATURE')

    def test_exe_rejected(self):
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('evil.exe', b'MZ\x90\x00'), self.student, 'attachment')
        self.assertEqual(ctx.exception.code, 'EXTENSION_NOT_ALLOWED')

    def test_empty_file_rejected(self):
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('empty.png', b''), self.student, 'avatar')
        self.assertEqual(ctx.exception.code, 'EMPTY_FILE')

    def test_oversize_rejected(self):
        big = b'\x89PNG\r\n\x1a\n' + b'0' * (services.MAX_BYTES + 1)
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('big.png', big), self.student, 'avatar')
        self.assertEqual(ctx.exception.code, 'FILE_TOO_LARGE')

    def test_filename_sanitized(self):
        record = services.store(
            upload('../../etc/passwd.png', PNG_BYTES), self.student, 'avatar')
        self.assertEqual(record.original_name, 'passwd.png')
        self.assertFalse(record.original_name.startswith('.'))

    def test_zip_bomb_rejected(self):
        payload = make_zip_bomb()
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('bomb.zip', payload), self.student, 'attachment')
        self.assertEqual(ctx.exception.code, 'ZIP_BOMB')

    def test_valid_zip_ok(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('a.txt', b'hello')
        payload = buffer.getvalue()
        record = services.store(upload('ok.zip', payload), self.student, 'attachment')
        self.assertEqual(record.status, 'ready')

    def test_csv_binary_rejected(self):
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('data.csv', b'a,b\x00c'), self.student, 'import')
        self.assertEqual(ctx.exception.code, 'BAD_SIGNATURE')

    def test_csv_text_ok(self):
        record = services.store(upload('data.csv', '学号,姓名\n1,张三\n'.encode('utf-8')),
                                self.student, 'import')
        self.assertEqual(record.status, 'ready')

    def test_bad_purpose(self):
        with self.assertRaises(services.UploadError) as ctx:
            services.store(upload('a.png', PNG_BYTES), self.student, 'unknown')
        self.assertEqual(ctx.exception.code, 'BAD_PURPOSE')


class AccessTests(UploadBase):
    def setUp(self):
        super().setUp()
        self.record = services.store(upload('报告.pdf', PDF_BYTES, 'application/pdf'),
                                     self.student, 'report')

    def test_owner_can_download(self):
        handle = services.open_upload(self.record, self.student)
        self.assertEqual(handle.read(), PDF_BYTES)
        handle.close()

    def test_other_cannot_download(self):
        with self.assertRaises(services.PermissionDenied):
            services.open_upload(self.record, self.other)

    def test_admin_can_download(self):
        handle = services.open_upload(self.record, self.admin)
        handle.close()

    def test_other_cannot_delete(self):
        with self.assertRaises(services.PermissionDenied):
            services.delete_upload(self.record, self.other)

    def test_delete_removes_file(self):
        services.delete_upload(self.record, self.student)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'deleted')
        self.assertFalse(os.path.exists(services.path_for(self.record)))
        with self.assertRaises(services.UploadError) as ctx:
            services.open_upload(self.record, self.student)
        self.assertEqual(ctx.exception.code, 'FILE_DELETED')

    def test_scoping(self):
        services.store(upload('other.png', PNG_BYTES), self.other, 'avatar')
        self.assertEqual(services.scoped_files(self.student).count(), 1)
        self.assertEqual(services.scoped_files(self.admin).count(), 2)

    def test_storage_stats(self):
        stats = services.storage_stats(self.student)
        self.assertEqual(stats['count'], 1)
        self.assertEqual(stats['bytes'], len(PDF_BYTES))
