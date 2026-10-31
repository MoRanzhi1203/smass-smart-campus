"""受控清理任务：过期导入临时文件、旧通知、旧登录尝试、旧探针。

    python manage.py smass_housekeeping --dry-run
    python manage.py smass_housekeeping --keep-days 90

只清理明确可再生的临时/历史数据；默认 dry-run 之外需要显式 --apply。
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = '清理临时导入文件与过期运维数据（默认 dry-run）'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='实际执行删除；默认只统计')
        parser.add_argument('--keep-days', type=int, default=90,
                            help='保留天数（默认 90）')
        parser.add_argument('--tmp-hours', type=int, default=24,
                            help='导入临时文件保留小时数（默认 24）')

    def handle(self, *args, **options):
        from r21_account.models import LoginAttempt
        from smass_operations.models import ReadinessProbe
        from smass_workflow.models import Notification

        apply = options['apply']
        cutoff = timezone.now() - timedelta(days=options['keep_days'])
        tmp_cutoff = timezone.now() - timedelta(hours=options['tmp_hours'])

        tmp_dir = Path(settings.BASE_DIR) / 'private_uploads' / 'import_tmp'
        stale_files = []
        if tmp_dir.exists():
            for path in tmp_dir.glob('*.csv'):
                mtime = timezone.datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.get_current_timezone())
                if mtime < tmp_cutoff:
                    stale_files.append(path)

        notifications = Notification.objects.filter(created_at__lt=cutoff)
        attempts = LoginAttempt.objects.filter(created_at__lt=cutoff)
        probes = ReadinessProbe.objects.filter(checked_at__lt=cutoff)

        summary = {
            'tmp_files': len(stale_files),
            'notifications': notifications.count(),
            'login_attempts': attempts.count(),
            'probes': probes.count(),
            'apply': apply,
        }
        self.stdout.write('清理计划：{}'.format(summary))

        if not apply:
            self.stdout.write('dry-run：未删除任何数据（加 --apply 执行）')
            return

        for path in stale_files:
            path.unlink(missing_ok=True)
        deleted = {
            'notifications': notifications.delete()[0],
            'login_attempts': attempts.delete()[0],
            'probes': probes.delete()[0],
            'tmp_files': len(stale_files),
        }
        self.stdout.write(self.style.SUCCESS('已清理：{}'.format(deleted)))
