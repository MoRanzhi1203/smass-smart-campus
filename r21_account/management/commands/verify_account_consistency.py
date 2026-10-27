"""G2 一致性校验：对比旧表与统一账号（只读）。

检查项：
1. 映射覆盖：每个 ``LegacyAccountLink`` 都能在旧表找到对应行；
2. 哈希一致：``Account.password`` 与旧表 ``password`` 完全相同（证明无双写/回填二次加密）；
3. 启用状态：``Account.is_active`` 与"旧表是否被视为停用"一致（旧表无停用字段，故只校验新表侧
   的 ``deactivated_at`` 与 ``is_active`` 自洽）；
4. 角色：每个 Account 至少一个活跃角色，且与 person_type 匹配；
5. 数量：Account 数 == 旧表三表之和（在纯回填场景下成立；双写新增也满足）。

用法：
    python manage.py verify_account_consistency --settings=smass.settings_r21
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from app01 import models as legacy
from r21_account.models import (
    Account,
    LegacyAccountLink,
    PersonType,
    RoleCode,
)

EXPECTED_ROLE = {
    PersonType.ADMIN: RoleCode.SYSTEM_ADMIN,
    PersonType.TEACHER: RoleCode.TEACHER,
    PersonType.STUDENT: RoleCode.STUDENT,
}

SOURCE_MODELS = {
    legacy.Admin._meta.db_table: legacy.Admin,
    legacy.Teacher._meta.db_table: legacy.Teacher,
    legacy.Student._meta.db_table: legacy.Student,
}


class Command(BaseCommand):
    help = 'R2.1 一致性校验：旧表 vs 统一 Account（只读）'

    def add_arguments(self, parser):
        parser.add_argument('--strict-count', action='store_true',
                            help='要求 Account 数严格等于旧表三表之和')

    def handle(self, *args, **options):
        db_name = connection.settings_dict['NAME'] or ''
        if not db_name.startswith('smass_r21_'):
            raise CommandError(
                '拒绝：一致性校验只允许在 smass_r21_* 原型库执行，当前 {!r}'.format(db_name)
            )

        problems = []
        self.stdout.write('target database : {}'.format(db_name))

        legacy_total = (
            legacy.Admin.objects.count()
            + legacy.Teacher.objects.count()
            + legacy.Student.objects.count()
        )
        account_total = Account.objects.count()
        link_total = LegacyAccountLink.objects.count()

        self.stdout.write('legacy rows     : {}'.format(legacy_total))
        self.stdout.write('accounts        : {}'.format(account_total))
        self.stdout.write('legacy links    : {}'.format(link_total))

        if link_total != account_total:
            problems.append(
                '映射数({}) != 账号数({})'.format(link_total, account_total)
            )

        if options['strict_count'] and account_total != legacy_total:
            problems.append(
                '账号数({}) != 旧表行数({})'.format(account_total, legacy_total)
            )

        hash_mismatch = []
        role_mismatch = []
        inactive_inconsistent = []
        missing_source = []

        for link in LegacyAccountLink.objects.select_related('account').all():
            model = SOURCE_MODELS.get(link.source_table)
            if model is None:
                problems.append('未知来源表: {}'.format(link.source_table))
                continue

            source_row = model.objects.filter(pk=link.source_pk).values(
                'password'
            ).first()
            if source_row is None:
                missing_source.append('{}:{}'.format(link.source_table, link.source_pk))
                continue

            if source_row['password'] != link.account.password:
                hash_mismatch.append('{}:{}'.format(link.source_table, link.source_pk))

            expected_role = EXPECTED_ROLE.get(link.account.person_type)
            active = link.account.active_roles()
            if expected_role not in active:
                role_mismatch.append(
                    '{} (person_type={}, roles={})'.format(
                        link.account.login_name, link.account.person_type, active
                    )
                )

            if link.account.is_active and link.account.deactivated_at is not None:
                inactive_inconsistent.append(link.account.login_name)

        if missing_source:
            problems.append('映射指向的旧表行不存在: {}'.format(missing_source[:10]))
        if hash_mismatch:
            problems.append(
                '密码哈希不一致（疑似二次加密）: {} 行, 例: {}'.format(
                    len(hash_mismatch), hash_mismatch[:5]
                )
            )
        if role_mismatch:
            problems.append(
                '角色与 person_type 不匹配: {} 行, 例: {}'.format(
                    len(role_mismatch), role_mismatch[:5]
                )
            )
        if inactive_inconsistent:
            problems.append(
                '启用状态自相矛盾（is_active=True 但有 deactivated_at）: {}'.format(
                    inactive_inconsistent[:5]
                )
            )

        self.stdout.write('')
        if problems:
            self.stdout.write(self.style.ERROR('[FAIL] 发现 {} 处问题：'.format(len(problems))))
            for item in problems:
                self.stdout.write('  - {}'.format(item))
            return

        self.stdout.write(self.style.SUCCESS(
            '[PASS] 映射覆盖 / 密码哈希一致 / 角色匹配 / 启用状态自洽 全部通过'
        ))
