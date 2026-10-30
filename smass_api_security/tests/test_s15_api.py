"""S15 服务层与端点：令牌、scope、限流、幂等、重放与审计。

运行::

    python manage.py test smass_api_security --settings=smass.settings_s15 --noinput
"""
from __future__ import annotations

import json
import time

from django.test import Client, TestCase
from django.utils import timezone

from r21_account import services as account_services
from r21_account.models import Account, RoleCode

from smass_api_security import services
from smass_api_security.models import (
    ApiClient,
    ApiRequestLog,
    ApiToken,
    IdempotencyKey,
    Nonce,
)

PASSWORD = 'S15Svc#2026'
PING = '/s15/api/v1/ping'
COUNT = '/s15/api/v1/students/count'


def make_account(login_name, roles, person_type='student'):
    account = Account.objects.create_user(
        login_name, PASSWORD, display_name=login_name, person_type=person_type)
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    account_services.ensure_role_groups()
    for role in roles:
        account_services.grant_role(account, role, granted_by='test')
    return Account.objects.get(pk=account.pk)


class ApiBase(TestCase):
    def setUp(self):
        self.admin = make_account('s15admin', [RoleCode.SYSTEM_ADMIN],
                                  person_type='admin')
        self.student = make_account('s15stu', [RoleCode.STUDENT])
        self.client_obj = services.create_client(self.admin, '测试客户端')
        self.raw, self.token = services.issue_token(
            self.client_obj, ['students:read'], ttl_seconds=3600)

    def _headers(self, **overrides):
        headers = {
            'HTTP_AUTHORIZATION': 'Bearer {}'.format(self.raw),
            'HTTP_X_TIMESTAMP': str(int(time.time())),
            'HTTP_X_NONCE': 'nonce-{}'.format(timezone.now().timestamp()),
        }
        headers.update(overrides)
        return headers


class TokenTests(ApiBase):
    def test_create_client_requires_admin(self):
        with self.assertRaises(services.ApiError) as ctx:
            services.create_client(self.student, '非法')
        self.assertEqual(ctx.exception.code, 'PERMISSION_DENIED')

    def test_token_stored_hashed(self):
        self.assertNotEqual(self.token.token_hash, self.raw)
        self.assertEqual(self.token.token_hash, services.hash_token(self.raw))

    def test_authenticate_ok(self):
        request = type('R', (), {
            'META': {'HTTP_AUTHORIZATION': 'Bearer {}'.format(self.raw)}})()
        token, error = services.authenticate(request)
        self.assertIsNone(error)
        self.assertEqual(token.pk, self.token.pk)

    def test_missing_token(self):
        request = type('R', (), {'META': {}})()
        _token, error = services.authenticate(request)
        self.assertEqual(error.code, 'NO_TOKEN')
        self.assertEqual(error.status, 401)

    def test_bad_token(self):
        request = type('R', (), {
            'META': {'HTTP_AUTHORIZATION': 'Bearer tok_wrong'}})()
        _token, error = services.authenticate(request)
        self.assertEqual(error.code, 'BAD_TOKEN')

    def test_expired_token(self):
        ApiToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() - timezone.timedelta(seconds=1))
        request = type('R', (), {
            'META': {'HTTP_AUTHORIZATION': 'Bearer {}'.format(self.raw)}})()
        _token, error = services.authenticate(request)
        self.assertEqual(error.code, 'TOKEN_EXPIRED')

    def test_revoked_token(self):
        services.revoke_token(self.token, self.admin)
        request = type('R', (), {
            'META': {'HTTP_AUTHORIZATION': 'Bearer {}'.format(self.raw)}})()
        _token, error = services.authenticate(request)
        self.assertEqual(error.code, 'TOKEN_REVOKED')

    def test_scope(self):
        self.assertTrue(services.has_scope(self.token, 'students:read'))
        self.assertFalse(services.has_scope(self.token, 'students:write'))
        self.assertTrue(services.has_scope(self.token, None))

    def test_rate_limit(self):
        allowed = [services.check_rate(self.token, 3)[0] for _ in range(4)]
        self.assertEqual(allowed, [True, True, True, False])

    def test_replay_detected(self):
        now = int(time.time())
        services.check_replay(self.token, str(now), 'once')
        with self.assertRaises(services.ApiError) as ctx:
            services.check_replay(self.token, str(now), 'once')
        self.assertEqual(ctx.exception.code, 'REPLAY_DETECTED')

    def test_stale_timestamp(self):
        with self.assertRaises(services.ApiError) as ctx:
            services.check_replay(self.token, str(int(time.time()) - 1000), 'n1')
        self.assertEqual(ctx.exception.code, 'STALE_TIMESTAMP')

    def test_missing_replay_headers(self):
        with self.assertRaises(services.ApiError) as ctx:
            services.check_replay(self.token, None, None)
        self.assertEqual(ctx.exception.code, 'NO_REPLAY_HEADERS')


class EndpointTests(ApiBase):
    def test_ping_requires_token(self):
        response = self.client.get(PING)
        self.assertEqual(401, response.status_code)
        self.assertEqual('NO_TOKEN', response.json()['error'])

    def test_ping_ok(self):
        response = self.client.get(PING, **self._headers())
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()['status'])

    def test_scope_denied(self):
        client_obj = services.create_client(self.admin, '无 scope 客户端')
        raw, token = services.issue_token(client_obj, [], ttl_seconds=600)
        response = self.client.post(
            COUNT, data='{}', content_type='application/json',
            **self._headers(HTTP_AUTHORIZATION='Bearer {}'.format(raw),
                            HTTP_IDEMPOTENCY_KEY='k1'))
        self.assertEqual(403, response.status_code)
        self.assertEqual('SCOPE_DENIED', response.json()['error'])

    def test_missing_replay_headers(self):
        response = self.client.get(
            PING, HTTP_AUTHORIZATION='Bearer {}'.format(self.raw))
        self.assertEqual(400, response.status_code)
        self.assertEqual('NO_REPLAY_HEADERS', response.json()['error'])

    def test_replay_blocked(self):
        headers = self._headers(HTTP_X_NONCE='fixed-nonce')
        first = self.client.get(PING, **headers)
        self.assertEqual(200, first.status_code)
        second = self.client.get(PING, **headers)
        self.assertEqual(409, second.status_code)
        self.assertEqual('REPLAY_DETECTED', second.json()['error'])

    def test_rate_limited(self):
        codes = []
        for index in range(12):
            response = self.client.get(
                PING, **self._headers(HTTP_X_NONCE='n{}'.format(index)))
            codes.append(response.status_code)
        self.assertIn(429, codes)
        self.assertEqual(codes[-1], 429)

    def test_idempotent_replay_returns_cached(self):
        headers = self._headers(HTTP_IDEMPOTENCY_KEY='idem-1',
                                HTTP_X_NONCE='i1')
        first = self.client.post(COUNT, data=json.dumps({'term': '2026'}),
                                 content_type='application/json', **headers)
        self.assertEqual(200, first.status_code)
        self.assertNotIn('Idempotent-Replayed', first)

        second = self.client.post(COUNT, data=json.dumps({'term': '2026'}),
                                  content_type='application/json',
                                  **self._headers(HTTP_IDEMPOTENCY_KEY='idem-1',
                                                  HTTP_X_NONCE='i2'))
        self.assertEqual(200, second.status_code)
        self.assertEqual('true', second['Idempotent-Replayed'])
        self.assertEqual(first.json(), second.json())
        self.assertEqual(IdempotencyKey.objects.filter(
            token=self.token, key='idem-1').count(), 1)

    def test_idempotency_conflict(self):
        headers = self._headers(HTTP_IDEMPOTENCY_KEY='idem-2',
                                HTTP_X_NONCE='c1')
        self.client.post(COUNT, data=json.dumps({'term': '2026'}),
                         content_type='application/json', **headers)
        conflict = self.client.post(
            COUNT, data=json.dumps({'term': '2027'}),
            content_type='application/json',
            **self._headers(HTTP_IDEMPOTENCY_KEY='idem-2',
                            HTTP_X_NONCE='c2'))
        self.assertEqual(409, conflict.status_code)
        self.assertEqual('IDEMPOTENCY_CONFLICT', conflict.json()['error'])

    def test_missing_idempotency_key(self):
        response = self.client.post(
            COUNT, data='{}', content_type='application/json',
            **self._headers())
        self.assertEqual(400, response.status_code)
        self.assertEqual('MISSING_IDEMPOTENCY_KEY', response.json()['error'])

    def test_request_logged(self):
        self.client.get(PING, **self._headers())
        self.assertGreaterEqual(
            ApiRequestLog.objects.filter(path=PING).count(), 1)
        log = ApiRequestLog.objects.filter(path=PING).first()
        log.status = 500
        with self.assertRaises(ValueError):
            log.save()
        with self.assertRaises(ValueError):
            log.delete()
