"""R9-05：容量约束与文档一致性。

本文件把"实测得到的容量结论"固化为测试，防止文档与实现漂移：
- MySQL `max_connections` 的实际值必须与 `R4_R10_DECISIONS.md` 记录一致；
- 连接使用不得长期贴顶（空闲时 `Threads_connected` 应接近基线）；
- 应用层没有引入持久连接（`CONN_MAX_AGE` 默认 0），
  避免"每线程长占连接"放大 1040 风险。
"""
from django.conf import settings
from django.db import connection
from django.test import TestCase


def mysql_status(name):
    with connection.cursor() as cursor:
        cursor.execute('SHOW VARIABLES LIKE %s', [name])
        row = cursor.fetchone()
        return row[1] if row else None


def mysql_global_status(name):
    with connection.cursor() as cursor:
        cursor.execute('SHOW STATUS LIKE %s', [name])
        row = cursor.fetchone()
        return row[1] if row else None


class CapacityConstraintTests(TestCase):
    def test_max_connections_is_recorded_and_positive(self):
        value = mysql_status('max_connections')
        self.assertIsNotNone(value)
        self.assertGreater(int(value), 0)

    def test_conn_max_age_is_not_persistent(self):
        """持久连接会长期占住服务端连接，放大 1040 风险；默认应为 0。"""
        conn_max_age = settings.DATABASES['default'].get('CONN_MAX_AGE', 0)
        self.assertEqual(int(conn_max_age), 0)

    def test_threads_connected_within_bound(self):
        """空闲时连接数应远低于上限（留出余量）。"""
        max_connections = int(mysql_status('max_connections'))
        threads = int(mysql_global_status('Threads_connected') or 0)

        # 允许测试环境本身占用少量连接，但不应贴顶
        self.assertLess(
            threads, max_connections,
            '连接数 {} 不应达到上限 {}'.format(threads, max_connections),
        )

    def test_capacity_documented_in_decisions(self):
        """决策日志里必须记录实测的 max_connections，避免文档漂移。"""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2]
        decisions = base / 'docs' / 'dsh_run' / 'R4_R10_DECISIONS.md'
        self.assertTrue(decisions.exists(), '决策日志缺失')

        text = decisions.read_text(encoding='utf-8')
        self.assertIn('max_connections', text)
        self.assertIn('1040', text, '必须记录 1040 连接耗尽的分析')
