"""S19 可访问性：规则、对比度、真实模板扫描与报告页。

运行::

    python manage.py test smass_a11y --settings=smass.settings_s19 --noinput
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_a11y import services

PASSWORD = 'S19Svc#2026'
LOGIN = '/r21/login/'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class ContrastTests(TestCase):
    def test_black_on_white(self):
        self.assertEqual(services.contrast_ratio('#000000', '#ffffff'), 21.0)

    def test_same_color(self):
        self.assertEqual(services.contrast_ratio('#123456', '#123456'), 1.0)

    def test_wcag_levels(self):
        self.assertEqual(services.wcag_level(7.5), 'AAA')
        self.assertEqual(services.wcag_level(5.0), 'AA')
        self.assertEqual(services.wcag_level(4.4), 'FAIL')
        self.assertEqual(services.wcag_level(3.2, large_text=True), 'AA')

    def test_design_system_pairs_pass_aa(self):
        for fg, bg, large in services.COLOR_PAIRS:
            with self.subTest(fg=fg, bg=bg):
                ratio = services.contrast_ratio(fg, bg)
                self.assertNotEqual(services.wcag_level(ratio, large), 'FAIL',
                                    '{} on {} = {}'.format(fg, bg, ratio))


class RuleTests(TestCase):
    def test_missing_lang(self):
        issues = services.audit_html('<html><body>x</body></html>')
        self.assertIn('html-lang', {item['rule'] for item in issues})

    def test_lang_ok(self):
        issues = services.audit_html('<html lang="zh-CN"><body>x</body></html>')
        self.assertNotIn('html-lang', {item['rule'] for item in issues})

    def test_partial_template_skips_lang(self):
        """子模板（extends）没有 <html>，不应误报 lang。"""
        issues = services.audit_html('{% extends "x.html" %}{% block c %}ok{% endblock %}')
        self.assertNotIn('html-lang', {item['rule'] for item in issues})

    def test_image_without_alt(self):
        issues = services.audit_html('<html lang="zh"><body><img src="a.png"></body></html>')
        self.assertIn('img-alt', {item['rule'] for item in issues})

    def test_input_without_label(self):
        issues = services.audit_html(
            '<html lang="zh"><body><input name="x"></body></html>')
        self.assertIn('control-label', {item['rule'] for item in issues})

    def test_input_with_aria_label(self):
        issues = services.audit_html(
            '<html lang="zh"><body><input name="x" aria-label="名称"></body></html>')
        self.assertNotIn('control-label', {item['rule'] for item in issues})

    def test_input_with_for_label(self):
        issues = services.audit_html(
            '<html lang="zh"><body><label for="x">名称</label>'
            '<input id="x" name="x"></body></html>')
        self.assertNotIn('control-label', {item['rule'] for item in issues})

    def test_empty_link(self):
        issues = services.audit_html(
            '<html lang="zh"><body><a href="/x"></a></body></html>')
        self.assertIn('link-name', {item['rule'] for item in issues})

    def test_positive_tabindex(self):
        issues = services.audit_html(
            '<html lang="zh"><body><a href="/x" tabindex="3">x</a></body></html>')
        self.assertIn('tabindex-positive', {item['rule'] for item in issues})


class TemplateScanTests(TestCase):
    def test_new_templates_have_no_error(self):
        root = Path(settings.BASE_DIR) / 'templates'
        results = services.audit_dir(root)
        summary = services.summarize(results)
        self.assertGreater(summary['new_templates'], 0)
        self.assertEqual(0, summary['new_errors'],
                         [item['path'] for item in results
                          if item['new_template']
                          for issue in item['issues'] if issue['level'] == 'error'])


class ReportViewTests(TestCase):
    def setUp(self):
        self.admin = make_account('s19admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s19stu', [RoleCode.STUDENT])

    def test_requires_login(self):
        response = self.client.get('/s19/')
        self.assertEqual(302, response.status_code)
        self.assertIn('/r21/login/', response['Location'])

    def test_student_forbidden(self):
        self.client.post(LOGIN, {'login_name': 's19stu', 'password': PASSWORD})
        self.assertEqual(403, self.client.get('/s19/').status_code)

    def test_admin_report(self):
        self.client.post(LOGIN, {'login_name': 's19admin', 'password': PASSWORD})
        response = self.client.get('/s19/')
        self.assertEqual(200, response.status_code)
        self.assertContains(response, '可访问性审计报告')
        self.assertContains(response, '对比度')
