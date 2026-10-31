"""就绪探针：数据库、迁移、缓存与文件目录检查，结果写入 ReadinessProbe。

    python manage.py smass_probe
"""
from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '运行就绪探针并写入 ReadinessProbe'

    def handle(self, *args, **options):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        from smass_operations.models import ReadinessProbe

        checks = []

        def run(name, func):
            started = time.perf_counter()
            try:
                ok, detail = func()
            except Exception as exc:  # noqa: BLE001 - 探针失败记录为不通过
                ok, detail = False, str(exc)[:200]
            duration = int((time.perf_counter() - started) * 1000)
            checks.append({'name': name, 'ok': ok, 'detail': detail,
                           'duration_ms': duration})

        def check_db():
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            return True, 'database ok'

        def check_migrations():
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            return not plan, '{} pending'.format(len(plan))

        def check_cache():
            from django.core.cache import cache

            cache.set('smass_probe', '1', 5)
            return cache.get('smass_probe') == '1', 'cache ok'

        def check_storage():
            root = Path(settings.BASE_DIR)
            writable = root.exists() and root.is_dir()
            return writable, str(root)

        run('database', check_db)
        run('migrations', check_migrations)
        run('cache', check_cache)
        run('storage', check_storage)

        for item in checks:
            ReadinessProbe.objects.create(
                name=item['name'], ok=item['ok'], detail=item['detail'],
                duration_ms=item['duration_ms'])
            self.stdout.write('{:<12} {} {} ({} ms)'.format(
                item['name'], 'OK' if item['ok'] else 'FAIL',
                item['detail'], item['duration_ms']))

        failed = [item for item in checks if not item['ok']]
        if failed:
            self.stderr.write('探针失败：{}'.format(
                ', '.join(item['name'] for item in failed)))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('探针全部通过'))
