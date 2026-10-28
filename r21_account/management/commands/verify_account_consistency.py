"""G2/G5 一致性校验：旧表 vs 统一 Account（**只读**，永不自动修复）。

模式：
- 默认：人类可读报告；
- ``--json``：机器可读（差异码 + 计数 + 脱敏样例）；
- ``--plan-only``：只输出修复计划，不执行任何写操作。

安全：
- 库名必须命中 ``smass_r21_`` 或 ``smass_r22_g5_`` 前缀；
- 本命令**没有任何 apply/repair 选项**——修复必须由人工评审后另写脚本。
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from app01 import models as legacy
from r21_account.models import (
    Account,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
    TeacherProfile,
)

SAFE_DB_PREFIXES = ('smass_r21_', 'smass_r22_g5_', 'test_smass_')

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

#: person_type -> 旧表（用于判断"某账号是否本应被回填"）
SOURCE_TABLE_BY_PERSON = {
    PersonType.ADMIN: legacy.Admin._meta.db_table,
    PersonType.TEACHER: legacy.Teacher._meta.db_table,
    PersonType.STUDENT: legacy.Student._meta.db_table,
}

#: 差异码 → 严重级别
SEVERITY = {
    'LINK_ACCOUNT_MISMATCH': 'critical',
    'STRICT_COUNT_MISMATCH': 'critical',
    'MISSING_SOURCE': 'critical',
    'HASH_MISMATCH': 'critical',
    'ROLE_MISMATCH': 'high',
    'STATUS_INCONSISTENT': 'high',
    'ORPHAN_PROFILE': 'medium',
    'DANGLING_LINK': 'critical',
    'UNLINKED_ACCOUNT': 'high',
}

#: 差异码 → 修复计划（只描述，不执行）
PLAN = {
    'LINK_ACCOUNT_MISMATCH': '映射数多于账号数：异常状态，需人工核对映射表',
    'STRICT_COUNT_MISMATCH': '账号总数与旧表行数不一致：确认是否存在非回填来源账号',
    'MISSING_SOURCE': '映射指向的旧表行已不存在：需评审是否保留 Account（禁止自动删除）',
    'HASH_MISMATCH': '密码哈希不一致：确认是否被二次加密，禁止自动重写哈希',
    'ROLE_MISMATCH': '角色与 person_type 不符：人工确认后重新授予角色',
    'STATUS_INCONSISTENT': '启用状态自相矛盾：人工确认 is_active 与 deactivated_at',
    'ORPHAN_PROFILE': '档案无对应映射：确认是否遗留数据，禁止自动删除',
    'DANGLING_LINK': '映射指向不存在的 Account：需人工处理',
    'UNLINKED_ACCOUNT': '账号在旧表中存在但缺少映射：确认是否回填遗漏，禁止自动删除',
}


class Command(BaseCommand):
    help = '一致性校验：旧表 vs 统一 Account（只读，无 repair）'

    def add_arguments(self, parser):
        parser.add_argument('--strict-count', action='store_true')
        parser.add_argument('--json', action='store_true', help='机器可读输出')
        parser.add_argument('--plan-only', action='store_true', help='只输出修复计划')

    def handle(self, *args, **options):
        db_name = connection.settings_dict['NAME'] or ''
        if not any(db_name.startswith(prefix) for prefix in SAFE_DB_PREFIXES):
            raise CommandError(
                '拒绝：一致性校验只允许在 {} 前缀的原型/演练库执行，当前 {!r}'.format(
                    SAFE_DB_PREFIXES, db_name
                )
            )

        issues = []

        def add(code, count, samples=None):
            issues.append({
                'code': code,
                'severity': SEVERITY.get(code, 'medium'),
                'count': count,
                'samples': (samples or [])[:5],
                'plan': PLAN.get(code, '人工评审'),
            })

        legacy_total = (
            legacy.Admin.objects.count()
            + legacy.Teacher.objects.count()
            + legacy.Student.objects.count()
        )
        account_total = Account.objects.count()
        link_total = LegacyAccountLink.objects.count()

        # 映射数**多于**账号数才是异常；账号多于映射是正常现象
        # （例如管理员手工创建、或非回填来源的账号）。
        if link_total > account_total:
            add('LINK_ACCOUNT_MISMATCH', link_total - account_total,
                ['links={} accounts={}'.format(link_total, account_total)])

        if options['strict_count'] and account_total != legacy_total:
            add('STRICT_COUNT_MISMATCH', abs(account_total - legacy_total),
                ['accounts={} legacy_rows={}'.format(account_total, legacy_total)])

        hash_mismatch = []
        role_mismatch = []
        status_inconsistent = []
        missing_source = []

        for link in LegacyAccountLink.objects.select_related('account').all():
            model = SOURCE_MODELS.get(link.source_table)
            if model is None:
                missing_source.append('unknown_table:{}'.format(link.source_table))
                continue

            source_row = model.objects.filter(pk=link.source_pk).values('password').first()
            if source_row is None:
                missing_source.append('{}:{}'.format(link.source_table, link.source_pk))
                continue

            if source_row['password'] != link.account.password:
                hash_mismatch.append('{}:{}'.format(link.source_table, link.source_pk))

            expected_role = EXPECTED_ROLE.get(link.account.person_type)
            if expected_role not in link.account.active_roles():
                role_mismatch.append(link.account.login_name)

            if link.account.is_active and link.account.deactivated_at is not None:
                status_inconsistent.append(link.account.login_name)

        if missing_source:
            add('MISSING_SOURCE', len(missing_source), missing_source)
        if hash_mismatch:
            add('HASH_MISMATCH', len(hash_mismatch), hash_mismatch)
        if role_mismatch:
            add('ROLE_MISMATCH', len(role_mismatch), role_mismatch)
        if status_inconsistent:
            add('STATUS_INCONSISTENT', len(status_inconsistent), status_inconsistent)

        # 孤立档案：profile 的 account 没有映射
        linked_account_ids = set(
            LegacyAccountLink.objects.values_list('account_id', flat=True)
        )
        for model, name in ((StudentProfile, 'student'), (TeacherProfile, 'teacher')):
            orphans = [
                row.account_id
                for row in model.objects.all().only('account_id')
                if row.account_id not in linked_account_ids
            ]
            if orphans:
                add('ORPHAN_PROFILE', len(orphans), ['{}:{}'.format(name, o) for o in orphans])

        # 悬挂映射：link 指向不存在的 Account（正常情况下 FK 会阻止，防御性检查）
        dangling = LegacyAccountLink.objects.filter(account__isnull=True).count()
        if dangling:
            add('DANGLING_LINK', dangling, ['count={}'.format(dangling)])

        # 未链接账号：只有当该 login_name **确实存在于对应旧表**时才算问题
        # （避免把手工创建/非回填来源的账号误报为不一致）
        unlinked = []
        for account in Account.objects.all().only('pk', 'login_name', 'person_type'):
            if account.pk in linked_account_ids:
                continue
            table = SOURCE_TABLE_BY_PERSON.get(account.person_type)
            if table is None:
                continue
            if SOURCE_MODELS[table].objects.filter(pk=account.login_name).exists():
                unlinked.append(account.login_name)
        if unlinked:
            add('UNLINKED_ACCOUNT', len(unlinked), unlinked)

        payload = {
            'ok': not issues,
            'database': db_name,
            'counts': {
                'legacy_rows': legacy_total,
                'accounts': account_total,
                'links': link_total,
                'student_profiles': StudentProfile.objects.count(),
                'teacher_profiles': TeacherProfile.objects.count(),
            },
            'issues': issues,
            'mode': 'plan-only' if options['plan_only'] else 'check-only',
            'repair_executed': False,
        }

        if options['json']:
            self.stdout.write(json.dumps(payload, ensure_ascii=False))
            return

        self.stdout.write('target database : {}'.format(db_name))
        self.stdout.write('legacy rows     : {}'.format(legacy_total))
        self.stdout.write('accounts        : {}'.format(account_total))
        self.stdout.write('legacy links    : {}'.format(link_total))
        self.stdout.write('')

        if not issues:
            self.stdout.write(self.style.SUCCESS(
                '[PASS] 映射覆盖 / 密码哈希一致 / 角色匹配 / 启用状态自洽 / 无孤立档案'
            ))
            return

        self.stdout.write(self.style.ERROR(
            '[FAIL] 发现 {} 类问题'.format(len(issues))
        ))
        for issue in issues:
            self.stdout.write('  - [{}] {} x{} 例: {}'.format(
                issue['severity'], issue['code'], issue['count'], issue['samples']
            ))
            if options['plan_only']:
                self.stdout.write('    计划: {}'.format(issue['plan']))
