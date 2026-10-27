"""受控清表维护命令。

设计动机（R1.5-B.2）：
原来三个后台模块提供 HTTP 清表入口 ``/admin/<module>/list/all_delete/``，
仅靠 POST + ``confirm=YES`` 把关。这在浏览器侧属于"高危批量销毁"，
仅凭一个表单字段不足以构成充分授权。

现在的策略：
- HTTP 入口**保留但默认拒绝**（返回 403 并记审计），不再执行任何删除；
- 真正清表只允许通过本命令行完成，且必须同时满足：
  1. ``--model`` 在白名单内（**不含 Admin**，避免把系统锁死）；
  2. 显式 ``--confirm``；
  3. 处于 ``DEBUG`` 环境，或额外给出 ``--allow-non-debug``。

用法：
    python manage.py purge_table --model Student --confirm
    python manage.py purge_table --model Student --confirm --dry-run
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app01 import models
from app01.services.accounts import log_action

#: 允许清空的模型白名单（刻意不包含 Admin / auth 相关表）
ALLOWED_MODELS = {
    'Student': models.Student,
    'Teacher': models.Teacher,
    'Classes': models.Classes,
    'Major': models.Major,
    'College': models.College,
    'Grade': models.Grade,
    'Department': models.Department,
    'LeagueCadres': models.LeagueCadres,
    'ClassCommittee': models.ClassCommittee,
}


class Command(BaseCommand):
    help = '受控清空业务表（高危维护命令，HTTP 入口已停用）'

    def add_arguments(self, parser):
        parser.add_argument('--model', required=True, help='模型名，例如 Student')
        parser.add_argument('--confirm', action='store_true', help='确认执行删除')
        parser.add_argument('--dry-run', action='store_true', help='只统计不删除')
        parser.add_argument(
            '--allow-non-debug',
            action='store_true',
            help='在 DEBUG=False 环境下也允许执行（默认拒绝）',
        )

    def handle(self, *args, **options):
        model_name = options['model']
        if model_name not in ALLOWED_MODELS:
            raise CommandError(
                '模型 "{}" 不在白名单内。允许值：{}'.format(
                    model_name, ', '.join(sorted(ALLOWED_MODELS))
                )
            )

        if not options['confirm']:
            raise CommandError('高危操作：必须显式给出 --confirm')

        if not settings.DEBUG and not options['allow_non_debug']:
            raise CommandError(
                '拒绝：当前 DJANGO_DEBUG=False。若确需执行，请显式加 --allow-non-debug。'
            )

        model = ALLOWED_MODELS[model_name]
        total = model.objects.count()

        self.stdout.write('target model : {}'.format(model_name))
        self.stdout.write('rows         : {}'.format(total))

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('dry-run：未执行任何删除'))
            return

        with transaction.atomic():
            deleted, detail = model.objects.all().delete()

        log_action(
            None,
            'dangerous_purge',
            None,
            detail='model={} rows={} detail={}'.format(model_name, deleted, detail),
        )

        self.stdout.write(
            self.style.SUCCESS('purged {} rows (deleted={})'.format(model_name, deleted))
        )
