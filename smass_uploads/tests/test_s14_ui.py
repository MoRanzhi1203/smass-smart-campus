"""S14 页面层：上传、下载、删除与越权拒绝。

运行::

    python manage.py test smass_uploads.tests.test_s14_ui --settings=smass.settings_s14
"""
from __future__ import annotations

import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_uploads.models import UploadedFile

PASSWORD = 'S14Ui#2026'
LOGIN = '/r21/login/'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


def login(client, login_name):
    return client.post(LOGIN, {'login_name': login_name, 'password': PASSWORD})


class UploadUiTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='smass-s14-ui-')
        self.override = override_settings(SMASS_PRIVATE_MEDIA_ROOT=self.tmpdir)
        self.override.enable()

        self.admin = make_account('s14uiadmin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s14uistu', [RoleCode.STUDENT])
        self.other = make_account('s14uiother', [RoleCode.STUDENT])

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def test_requires_login(self):
        response = self.client.get('/uploads/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_upload_png_via_page(self):
        login(self.client, 's14uistu')
        response = self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('me.png', PNG_BYTES, content_type='image/png'),
        })
        self.assertEqual(302, response.status_code)
        record = UploadedFile.objects.get(owner=self.student)
        self.assertEqual(record.original_name, 'me.png')
        self.assertEqual(record.status, 'ready')

    def test_upload_fake_png_shows_error(self):
        login(self.client, 's14uistu')
        response = self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('fake.png', b'not a png'),
        })
        self.assertEqual(302, response.status_code)
        self.assertIn('error=', response['Location'])
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_owner_downloads(self):
        login(self.client, 's14uistu')
        self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('me.png', PNG_BYTES, content_type='image/png'),
        })
        record = UploadedFile.objects.get(owner=self.student)
        response = self.client.get('/uploads/{}/download/'.format(record.pk))
        self.assertEqual(200, response.status_code)
        self.assertEqual(b''.join(response.streaming_content), PNG_BYTES)

    def test_other_cannot_download(self):
        login(self.client, 's14uistu')
        self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('me.png', PNG_BYTES, content_type='image/png'),
        })
        record = UploadedFile.objects.get(owner=self.student)

        other = Client()
        login(other, 's14uiother')
        response = other.get('/uploads/{}/download/'.format(record.pk))
        self.assertEqual(403, response.status_code)

    def test_admin_can_download_others(self):
        login(self.client, 's14uistu')
        self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('me.png', PNG_BYTES, content_type='image/png'),
        })
        record = UploadedFile.objects.get(owner=self.student)

        admin = Client()
        login(admin, 's14uiadmin')
        response = admin.get('/uploads/{}/download/'.format(record.pk))
        self.assertEqual(200, response.status_code)

    def test_delete_own_file(self):
        login(self.client, 's14uistu')
        self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('me.png', PNG_BYTES, content_type='image/png'),
        })
        record = UploadedFile.objects.get(owner=self.student)
        response = self.client.post('/uploads/{}/delete/'.format(record.pk))
        self.assertEqual(302, response.status_code)
        record.refresh_from_db()
        self.assertEqual(record.status, 'deleted')
        self.assertFalse(os.path.exists(os.path.join(
            self.tmpdir, 'avatar', record.stored_name)))

    def test_list_scoped_to_owner(self):
        login(self.client, 's14uistu')
        self.client.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('mine.png', PNG_BYTES, content_type='image/png'),
        })
        other = Client()
        login(other, 's14uiother')
        other.post('/uploads/upload/', {
            'purpose': 'avatar',
            'file': SimpleUploadedFile('theirs.png', PNG_BYTES, content_type='image/png'),
        })

        login(self.client, 's14uistu')
        response = self.client.get('/uploads/')
        self.assertContains(response, 'mine.png')
        self.assertNotContains(response, 'theirs.png')
