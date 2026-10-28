"""R6-05：浏览器 UI 走查（两条演示流程从配置到审批到通知）。

引擎由 ``R6_BROWSER`` 选择。
"""
import os
import unittest

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_workflow import services
from smass_workflow.models import ApprovalTask, Notification, WorkflowInstance

try:
    from playwright.sync_api import sync_playwright

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    sync_playwright = None
    _IMPORT_ERROR = exc

ENGINE = os.environ.get('R6_BROWSER', 'chromium').strip().lower()
SKIP_REASON = None if sync_playwright else 'playwright 不可用：{}'.format(_IMPORT_ERROR)

PASSWORD = 'R6E2E#2024'


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or '')
class R6BrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        launcher = getattr(cls._pw, ENGINE, None)
        if launcher is None:
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('未知引擎 {}'.format(ENGINE))
        try:
            cls.browser = launcher.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            cls._pw.stop()
            super().tearDownClass()
            raise unittest.SkipTest('{} 启动失败: {}'.format(ENGINE, str(exc)[:200]))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        core_services.ensure_role_groups()
        self.admin = self._account('R6E_ADM', RoleCode.SYSTEM_ADMIN, 'admin')
        self.staff = self._account('R6E_STAFF', RoleCode.TEACHER, 'teacher')
        self.context = None

    def _account(self, login, role, person_type):
        account = Account.objects.create_user(
            login, PASSWORD, display_name=login, person_type=person_type
        )
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        core_services.grant_role(account, role, granted_by='r6_e2e')
        return Account.objects.get(pk=account.pk)

    def _page(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 860})
        page = self.context.new_page()
        page.set_default_timeout(15000)
        return page

    def _login(self, page, login, landing):
        account = Account.objects.get(login_name=login)
        self.client.force_login(account)
        page.context.add_cookies([{
            'name': 'sessionid',
            'value': self.client.session.session_key,
            'url': self.live_server_url,
        }])
        page.goto('{}{}'.format(self.live_server_url, landing))
        page.wait_for_load_state('load')

    def tearDown(self):
        if self.context is not None:
            self.context.close()
        super().tearDown()

    def _publish_single(self, code='UI_A'):
        definition = services.create_definition(code, '演示流程A')
        version = services.create_draft_version(definition)
        services.add_node(version, 'start', '发起', 'start', order=0)
        services.add_node(version, 'approve', '审批', 'approval', order=1)
        services.add_node(version, 'end', '完成', 'end', order=2)
        services.add_transition(version, 'start', 'approve', 'submit')
        services.add_transition(version, 'approve', 'end', 'approve')
        services.add_transition(version, 'approve', 'end', 'reject')
        services.publish_version(version)
        return definition, version

    # ------------------------------------------------------------------
    def test_01_definition_page_renders(self):
        self._publish_single('UI_A')
        page = self._page()
        self._login(page, 'R6E_ADM', '/r6/definitions/')

        body = page.content()
        self.assertIn('UI_A', body)
        self.assertIsNotNone(page.query_selector('#definition-table'))

    def test_02_instance_page_renders(self):
        _d, version = self._publish_single('UI_B')
        services.start_instance(version, subject_type='demo', subject_id='B1')

        page = self._page()
        self._login(page, 'R6E_ADM', '/r6/instances/')

        body = page.content()
        self.assertIn('demo:B1', body)
        self.assertIsNotNone(page.query_selector('#instance-table'))

    def test_03_submit_and_approve_via_ui(self):
        _d, version = self._publish_single('UI_C')
        instance = services.start_instance(
            version, subject_type='demo', subject_id='C1', created_by='R6E_STAFF'
        )

        page = self._page()
        self._login(page, 'R6E_ADM', '/r6/instances/')

        def act(action):
            return page.evaluate(
                """([id, act]) => {
                    const token = (document.cookie.split('; ')
                        .find(c => c.startsWith('csrftoken=')) || '').split('=')[1] || '';
                    return fetch('/r6/instances/' + id + '/action/', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json',
                                  'X-CSRFToken': token,
                                  'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({action: act})
                    }).then(r => r.json());
                }""",
                [instance.pk, action],
            )

        submitted = act('submit')
        self.assertTrue(submitted['ok'])
        self.assertEqual(submitted['status'], 'pending')
        self.assertEqual(submitted['node'], 'approve')

        approved = act('approve')
        self.assertTrue(approved['ok'])
        self.assertEqual(approved['status'], 'approved')

    def test_04_task_page_shows_open_task(self):
        _d, version = self._publish_single('UI_D')
        instance = services.start_instance(version, subject_type='demo', subject_id='D1')
        services.transition(instance, 'submit', actor='R6E_STAFF')

        page = self._page()
        self._login(page, 'R6E_ADM', '/r6/tasks/')

        body = page.content()
        self.assertIn('approve', body)
        self.assertIsNotNone(page.query_selector('#task-table'))

    def test_05_notification_page_shows_message(self):
        services.notify('R6E_ADM', '您有一条待审批', body='演示', event_key='ui-e1')

        page = self._page()
        self._login(page, 'R6E_ADM', '/r6/notifications/')

        body = page.content()
        self.assertIn('您有一条待审批', body)
        self.assertIsNotNone(page.query_selector('#notification-table'))

    def test_06_illegal_transition_shows_error_in_browser(self):
        _d, version = self._publish_single('UI_E')
        instance = services.start_instance(version, subject_type='demo', subject_id='E1')

        page = self._page()
        self._login(page, 'R6E_ADM', '/r6/instances/')

        result = page.evaluate(
            """(id) => {
                const token = (document.cookie.split('; ')
                    .find(c => c.startsWith('csrftoken=')) || '').split('=')[1] || '';
                return fetch('/r6/instances/' + id + '/action/', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-CSRFToken': token,
                              'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify({action: 'approve'})
                }).then(r => r.json().then(j => ({status: r.status, code: j.code})));
            }""",
            instance.pk,
        )

        self.assertEqual(result['status'], 400)
        self.assertEqual(result['code'], 'TRANSITION')

    def test_07_unauthorized_cannot_view_definitions(self):
        page = self._page()
        self._login(page, 'R6E_STAFF', '/r6/definitions/')

        self.assertIn('无权限', page.content())
