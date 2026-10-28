"""G2 回填：把旧三表回填为统一 Account（仅隔离库）。

安全约束（计划 §3 / G2）：
1. **只在** ``smass_r21_*`` 库执行；连接库名不匹配直接 CommandError；
2. 密码哈希**原样搬迁**（直接赋值），绝不调用 ``set_password``；
3. 幂等：以 ``LegacyAccountLink(source_table, source_pk)`` 判重；
4. 支持 ``--dry-run`` / ``--since``（断点）/ ``--rollback``；
5. 撞号（``login_name`` 已被其他来源占用）→ 记录冲突、跳过、**不覆盖**；
6. 逐批事务，单行失败不污染整批（记 error 并继续），最终输出计数报告。

用法：
    python manage.py backfill_accounts_r21 --dry-run --settings=smass.settings_r21
    python manage.py backfill_accounts_r21            --settings=smass.settings_r21
    python manage.py backfill_accounts_r21 --rollback  --settings=smass.settings_r21
"""
from dataclasses import dataclass, field

from django.db import connection, transaction
from django.core.management.base import BaseCommand, CommandError

from app01 import models as legacy
from r21_account import services
from r21_account.models import (
    Account,
    AccountRole,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
    TeacherProfile,
)

#: 旧模型 → (人员类型, 默认角色, 是否需要 Profile)
SOURCES = (
    (legacy.Admin, PersonType.ADMIN, RoleCode.SYSTEM_ADMIN, None),
    (legacy.Teacher, PersonType.TEACHER, RoleCode.TEACHER, 'teacher'),
    (legacy.Student, PersonType.STUDENT, RoleCode.STUDENT, 'student'),
)


@dataclass
class Stats:
    processed: int = 0
    created: int = 0
    skipped: int = 0
    conflicts: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def report(self, label, stream=None):
        def out(text):
            if stream is None:
                print(text)
            else:
                stream(text + '\n')

        out('[{}] processed={} created={} skipped={} conflicts={} errors={}'.format(
            label, self.processed, self.created, self.skipped,
            len(self.conflicts), len(self.errors),
        ))
        for item in self.conflicts[:20]:
            out('  CONFLICT {}'.format(item))
        for item in self.errors[:20]:
            out('  ERROR {}'.format(item))


class Command(BaseCommand):
    help = 'R2.1 回填：旧三表 -> 统一 Account（仅隔离库 smass_r21_*）'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--since', type=int, default=0)
        parser.add_argument('--rollback', action='store_true')

    def handle(self, *args, **options):
        db_name = connection.settings_dict['NAME'] or ''
        # additive：R2.2 G5 加入隔离演练库前缀与 Django 测试库前缀；
        # 仍然严格排除 smass 与既有原型库。
        safe_prefixes = ('smass_r21_', 'smass_r22_g5_', 'smass_r22_g8_', 'test_smass_')
        if not any(db_name.startswith(prefix) for prefix in safe_prefixes):
            raise CommandError(
                '拒绝：回填只允许在 {} 前缀的原型/演练库执行，当前 {!r}'.format(
                    safe_prefixes, db_name
                )
            )

        self.stdout.write('target database : {}'.format(db_name))

        services.ensure_role_groups()

        if options['rollback']:
            return self._rollback(options['dry_run'])

        return self._backfill(options)

    # ------------------------------------------------------------------
    def _rollback(self, dry_run):
        links = LegacyAccountLink.objects.all()
        count = links.count()
        self.stdout.write('rollback candidates: {}'.format(count))

        if dry_run:
            self.stdout.write(self.style.WARNING('dry-run：未删除'))
            return

        with transaction.atomic():
            # 先删映射，再删账号（Account 级联删 Profile/Role）
            account_ids = list(links.values_list('account_id', flat=True))
            links.delete()
            deleted_accounts = Account.objects.filter(pk__in=account_ids).delete()

        self.stdout.write(self.style.SUCCESS(
            'rollback done: links={} accounts={}'.format(count, deleted_accounts)
        ))

    def _backfill(self, options):
        dry_run = options['dry_run']
        since = max(0, options['since'])
        stats = Stats()

        for model, person_type, role, profile_kind in SOURCES:
            rows = list(model.objects.order_by('pk'))
            self.stdout.write('source {:<8} rows={}'.format(model.__name__, len(rows)))

            for index, row in enumerate(rows):
                stats.processed += 1
                if index < since:
                    continue

                pk_text = str(row.pk)
                source_table = model._meta.db_table

                if LegacyAccountLink.objects.filter(
                    source_table=source_table, source_pk=pk_text
                ).exists():
                    stats.skipped += 1
                    continue

                if Account.objects.filter(login_name=pk_text).exists():
                    stats.conflicts.append(
                        '{} pk={} 与已有 login_name 冲突'.format(model.__name__, pk_text)
                    )
                    stats.skipped += 1
                    continue

                if dry_run:
                    stats.created += 1
                    continue

                try:
                    with transaction.atomic():
                        account = Account(
                            login_name=pk_text,
                            display_name=getattr(row, 'name', '') or '',
                            person_type=person_type,
                            is_active=True,
                            # 旧账号都是"已有密码"，但哈希来自旧系统，强制其首次登录改密更稳
                            must_change_password=True,
                        )
                        # 关键：原样搬迁哈希，绝不 set_password
                        account.password = row.password
                        account.save()

                        services.grant_role(account, role, granted_by='backfill')

                        if profile_kind == 'student':
                            StudentProfile.objects.create(
                                account=account,
                                student_no=pk_text,
                                name=getattr(row, 'name', '') or '',
                                classes_name=str(getattr(row, 'classes', '') or ''),
                                phone=getattr(row, 'phone', '') or '',
                                card_id=getattr(row, 'cardID', '') or '',
                            )
                        elif profile_kind == 'teacher':
                            TeacherProfile.objects.create(
                                account=account,
                                teacher_no=pk_text,
                                name=getattr(row, 'name', '') or '',
                                college_name=str(getattr(row, 'college', '') or ''),
                                phone=getattr(row, 'phone', '') or '',
                            )

                        LegacyAccountLink.objects.create(
                            account=account,
                            source_table=source_table,
                            source_pk=pk_text,
                        )
                        services.audit(
                            'backfill', actor='backfill', target=pk_text,
                            detail='source={}'.format(source_table),
                        )
                    stats.created += 1
                except Exception as exc:  # noqa: BLE001 - 单行失败不阻断整批
                    stats.errors.append(
                        '{} pk={} 失败: {}'.format(model.__name__, pk_text, exc)
                    )

        stats.report('BACKFILL{}'.format(' (dry-run)' if dry_run else ''),
                     stream=self.stdout.write)
        self.stdout.write('accounts        : {}'.format(Account.objects.count()))
        self.stdout.write('roles           : {}'.format(AccountRole.objects.count()))
        self.stdout.write('links           : {}'.format(LegacyAccountLink.objects.count()))
        self.stdout.write('student_profile : {}'.format(StudentProfile.objects.count()))
        self.stdout.write('teacher_profile : {}'.format(TeacherProfile.objects.count()))
