"""R9-01：遥测、健康检查与告警。"""
from django.test import TestCase

from smass_operations import services
from smass_operations.models import (
    AlertEvent,
    AlertRule,
    ReadinessProbe,
    RequestMetric,
)


class FakeRequest:
    def __init__(self, path, method='GET'):
        self.path = path
        self.method = method


class RouteNormalizationTests(TestCase):
    def test_numeric_segments_replaced(self):
        self.assertEqual(
            services.normalize_route('/r4/students/123/'), '/r4/students/{id}/'
        )

    def test_long_tokens_replaced(self):
        route = services.normalize_route('/api/v1/x/abcdef0123456789abcdef/')
        self.assertIn('{token}', route)

    def test_plain_segments_preserved(self):
        self.assertEqual(services.normalize_route('/r5/years/'), '/r5/years/')


class MetricsTests(TestCase):
    def test_record_and_summarize(self):
        for index, duration in enumerate([10, 20, 30, 40, 500]):
            services.record_request(FakeRequest('/r5/years/'), 200, duration)

        stats = services.summary(300)
        self.assertEqual(stats['requests'], 5)
        self.assertGreater(stats['p99_ms'], 0)
        self.assertEqual(stats['error_rate'], 0.0)

    def test_error_rate_counts_5xx(self):
        services.record_request(FakeRequest('/x/'), 200, 10)
        services.record_request(FakeRequest('/x/'), 500, 10)

        stats = services.summary(300)
        self.assertEqual(stats['error_rate'], 0.5)

    def test_empty_window(self):
        stats = services.summary(300)
        self.assertEqual(stats['requests'], 0)
        self.assertEqual(stats['p95_ms'], 0.0)

    def test_no_pii_in_stored_route(self):
        services.record_request(FakeRequest('/r4/students/987654321/'), 200, 5)
        row = RequestMetric.objects.latest('id')
        self.assertNotIn('987654321', row.route)


class HealthTests(TestCase):
    def test_liveness(self):
        resp = self.client.get('/r9/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_readiness_ok_on_test_db(self):
        resp = self.client.get('/r9/ready/')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['ok'])
        names = {check['name'] for check in payload['checks']}
        self.assertEqual(names, {'database', 'migrations'})

    def test_readiness_probes_persisted(self):
        self.client.get('/r9/ready/')
        self.assertTrue(ReadinessProbe.objects.filter(name='database').exists())

    def test_metrics_endpoint(self):
        services.record_request(FakeRequest('/r9/health/'), 200, 3)
        resp = self.client.get('/r9/metrics/?window=300')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['summary']['requests'], 1)


class AlertTests(TestCase):
    def test_create_rule_rejects_unknown_metric(self):
        with self.assertRaises(services.OpsError):
            services.create_rule('r1', '规则', 'nope', 1)

    def test_duplicate_rule_rejected(self):
        services.create_rule('r1', '规则', 'error_rate', 0.1)
        with self.assertRaises(services.OpsError):
            services.create_rule('r1', '重复', 'error_rate', 0.2)

    def test_rule_triggers_when_threshold_exceeded(self):
        services.create_rule('err', '错误率过高', 'error_rate', 0.2, window_seconds=300)
        for _ in range(4):
            services.record_request(FakeRequest('/x/'), 500, 10)

        triggered = services.evaluate_rules()
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0]['rule'], 'err')
        self.assertGreaterEqual(triggered[0]['observed'], 1.0)
        self.assertTrue(AlertEvent.objects.filter(rule__code='err').exists())

    def test_rule_not_triggered_below_threshold(self):
        services.create_rule('err2', '错误率过高', 'error_rate', 0.9, window_seconds=300)
        services.record_request(FakeRequest('/x/'), 500, 10)
        services.record_request(FakeRequest('/x/'), 200, 10)

        self.assertEqual(services.evaluate_rules(), [])

    def test_disabled_rule_ignored(self):
        rule = services.create_rule('off', '停用', 'error_rate', 0.0)
        rule.is_enabled = False
        rule.save(update_fields=['is_enabled'])

        for _ in range(3):
            services.record_request(FakeRequest('/x/'), 500, 10)
        self.assertEqual(services.evaluate_rules(), [])

    def test_alerts_endpoint_does_not_persist(self):
        services.create_rule('err3', '错误', 'error_rate', 0.1)
        for _ in range(3):
            services.record_request(FakeRequest('/x/'), 500, 10)

        before = AlertEvent.objects.count()
        resp = self.client.get('/r9/alerts/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AlertEvent.objects.count(), before)
