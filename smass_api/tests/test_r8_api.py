"""R8：API 认证、授权、限流、幂等、同步与契约。"""
from datetime import date

from django.test import TestCase

from r21_account import services as core_services
from r21_account.models import Account, RoleCode
from smass_academic import services as academic_services
from smass_api import services
from smass_api.models import ApiCallLog, IdempotencyKey, ServiceAccount, SyncJob
from smass_organization import services as org_services
from smass_organization.models import StudentRecord

PASSWORD = 'R8Pass#2024'


def bearer(raw):
    return {'HTTP_AUTHORIZATION': 'Bearer {}'.format(raw)}


class ApiFixture(TestCase):
    def setUp(self):
        services.reset_rate_limits()

        self.college = org_services.create_unit(code='C1', name='学院', unit_type='college')
        for index in range(3):
            StudentRecord.objects.create(
                student_no='S{:03d}'.format(index), name='学生{}'.format(index),
                unit=self.college,
            )
        year = academic_services.create_year('Y1', date(2025, 9, 1), date(2026, 8, 31))
        term = academic_services.create_term(year, '1', date(2025, 9, 1), date(2026, 1, 15))
        course = academic_services.create_course('CS1', '课程1')
        academic_services.create_section(term, course, 'A')

        self.reader, self.reader_token = services.create_service_account(
            'reader', scopes=[services.SCOPE_READ_UNITS]
        )
        self.full, self.full_token = services.create_service_account(
            'full',
            scopes=[
                services.SCOPE_READ_UNITS, services.SCOPE_READ_STUDENTS,
                services.SCOPE_READ_SECTIONS, services.SCOPE_READ_WORKFLOW,
                services.SCOPE_WRITE_STUDENTS,
            ],
        )
        self.bare, self.bare_token = services.create_service_account('bare')


class AuthTests(ApiFixture):
    def test_missing_token_rejected(self):
        resp = self.client.get('/api/v1/units/')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'UNAUTHENTICATED')

    def test_invalid_token_rejected(self):
        resp = self.client.get('/api/v1/units/', **bearer('not-a-token'))
        self.assertEqual(resp.status_code, 401)

    def test_valid_token_allows_scoped_endpoint(self):
        resp = self.client.get('/api/v1/units/', **bearer(self.reader_token))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('rows', resp.json())

    def test_scope_missing_rejected(self):
        # reader 只有 read:units，没有 read:students
        resp = self.client.get('/api/v1/students/', **bearer(self.reader_token))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error']['code'], 'FORBIDDEN')

    def test_service_account_has_no_scope_by_default(self):
        self.assertEqual(self.bare.scopes, [])
        resp = self.client.get('/api/v1/units/', **bearer(self.bare_token))
        self.assertEqual(resp.status_code, 403)

    def test_inactive_account_rejected(self):
        self.reader.is_active = False
        self.reader.save(update_fields=['is_active'])
        resp = self.client.get('/api/v1/units/', **bearer(self.reader_token))
        self.assertEqual(resp.status_code, 401)

    def test_token_is_hashed_not_stored_plain(self):
        self.assertNotEqual(self.reader.token_hash, self.reader_token)
        self.assertEqual(len(self.reader.token_hash), 64)


class ListEndpointTests(ApiFixture):
    def test_units_pagination(self):
        resp = self.client.get(
            '/api/v1/units/?page=1&page_size=1', **bearer(self.reader_token)
        )
        body = resp.json()
        self.assertEqual(body['page'], 1)
        self.assertEqual(body['page_size'], 1)
        self.assertLessEqual(len(body['rows']), 1)

    def test_units_keyword_filter(self):
        resp = self.client.get('/api/v1/units/?q=学院', **bearer(self.reader_token))
        self.assertEqual(resp.json()['total'], 1)

    def test_page_size_capped(self):
        resp = self.client.get(
            '/api/v1/units/?page_size=9999', **bearer(self.reader_token)
        )
        self.assertEqual(resp.json()['page_size'], 100)

    def test_students_do_not_default_to_whole_school(self):
        """关键：给了 read:students 也不等于全校可见（默认空集）。"""
        resp = self.client.get('/api/v1/students/', **bearer(self.full_token))
        body = resp.json()
        self.assertEqual(body['total'], 0)
        self.assertEqual(body['rows'], [])

    def test_sections_list(self):
        resp = self.client.get('/api/v1/sections/', **bearer(self.full_token))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total'], 1)

    def test_workflow_instances_list(self):
        resp = self.client.get(
            '/api/v1/workflow/instances/', **bearer(self.full_token)
        )
        self.assertEqual(resp.status_code, 200)

    def test_rate_limit_enforced(self):
        self.full.rate_limit_per_minute = 2
        self.full.save(update_fields=['rate_limit_per_minute'])

        statuses = [
            self.client.get('/api/v1/units/', **bearer(self.full_token)).status_code
            for _ in range(4)
        ]
        self.assertIn(429, statuses)

    def test_call_logged(self):
        self.client.get('/api/v1/units/', **bearer(self.reader_token))
        self.assertTrue(ApiCallLog.objects.filter(path='/api/v1/units/').exists())


class IdempotencyTests(ApiFixture):
    def _payload(self):
        return {'records': [{'external_id': 'e1'}, {'external_id': 'e2'}]}

    def test_sync_without_key_runs_each_time(self):
        import json

        for _ in range(2):
            resp = self.client.post(
                '/api/v1/sync/', data=json.dumps(self._payload()),
                content_type='application/json', **bearer(self.full_token),
            )
            self.assertEqual(resp.status_code, 200)

        self.assertEqual(SyncJob.objects.count(), 2)

    def test_same_key_same_body_replays_first_result(self):
        import json

        headers = dict(bearer(self.full_token))
        headers['HTTP_IDEMPOTENCY_KEY'] = 'k1'
        body = json.dumps(self._payload())

        first = self.client.post('/api/v1/sync/', data=body,
                                 content_type='application/json', **headers)
        second = self.client.post('/api/v1/sync/', data=body,
                                  content_type='application/json', **headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get('Idempotent-Replayed'), 'true')
        self.assertEqual(SyncJob.objects.count(), 1)

    def test_same_key_different_body_conflicts(self):
        import json

        headers = dict(bearer(self.full_token))
        headers['HTTP_IDEMPOTENCY_KEY'] = 'k2'

        self.client.post('/api/v1/sync/', data=json.dumps(self._payload()),
                         content_type='application/json', **headers)
        resp = self.client.post(
            '/api/v1/sync/',
            data=json.dumps({'records': [{'external_id': 'other'}]}),
            content_type='application/json', **headers,
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error']['code'], 'IDEMPOTENCY_CONFLICT')


class SyncTests(ApiFixture):
    def test_mock_sync_accepts_records(self):
        import json

        resp = self.client.post(
            '/api/v1/sync/',
            data=json.dumps({'records': [
                {'external_id': 'a'}, {'external_id': 'b'}, {'external_id': 'a'},
            ]}),
            content_type='application/json', **bearer(self.full_token),
        )
        result = resp.json()['result']
        self.assertEqual(result['accepted'], 2)
        self.assertEqual(result['replayed'], 1)

    def test_sync_requires_write_scope(self):
        import json

        client_resp = self.client.post(
            '/api/v1/sync/', data=json.dumps({'records': []}),
            content_type='application/json', **bearer(self.reader_token),
        )
        self.assertEqual(client_resp.status_code, 403)

    def test_invalid_payload_rejected(self):
        import json

        resp = self.client.post(
            '/api/v1/sync/', data=json.dumps({'records': 'not-a-list'}),
            content_type='application/json', **bearer(self.full_token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error']['code'], 'INVALID_PAYLOAD')


class ContractTests(ApiFixture):
    def test_openapi_lists_actual_paths(self):
        resp = self.client.get('/api/v1/openapi.json')
        self.assertEqual(resp.status_code, 200)

        schema = resp.json()
        paths = set(schema['paths'].keys())
        for expected in ('/units/', '/students/', '/sections/',
                         '/workflow/instances/', '/sync/'):
            self.assertIn(expected, paths)

    def test_openapi_matches_real_endpoints(self):
        """契约：schema 里出现的路径，实际都应可达（至少不是 404）。"""
        schema = self.client.get('/api/v1/openapi.json').json()
        for path, methods in schema['paths'].items():
            if 'get' in methods:
                resp = self.client.get('/api/v1' + path, **bearer(self.reader_token))
                self.assertNotEqual(resp.status_code, 404, path)
