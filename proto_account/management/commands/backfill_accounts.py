"""把旧三张账号表回填为统一 ``Account``（仅用于 R2.0 隔离原型库）。

设计约束（对应计划 §6.3 P2 / P4）：
1. **密码哈希原样迁移**：直接把旧表的 ``password`` 字段值赋给 ``Account.password``，
   绝不调用 make_password / set_password，避免"二次加密"（R1 曾踩过的坑）。
2. **幂等**：以 ``(legacy_source, legacy_pk)`` 为唯一键，重复执行只会计入 skipped。
3. **断点续跑**：``--since`` 跳过低主键，配合 ``--batch-size`` 分批提交。
4. **冲突可见**：``login_name`` 唯一。跨类型撞号时记录到 conflicts 并跳过，
   不覆盖已有账号——这为 ADR 提供真实的"命名空间冲突"证据。
5. **可回滚**：``--rollback`` 删除所有由回填产生的行（``legacy_source`` 非空）。

用法：
    python manage.py backfill_accounts --dry-run --settings=smass.settings_proto
    python manage.py backfill_accounts --settings=smass.settings_proto
    python manage.py backfill_accounts --rollback --settings=smass.settings_proto
"""
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app01 import models as legacy
from proto_account import models as proto


@dataclass
class Stats:
    processed: int = 0
    created: int = 0
    skipped: int = 0
    conflicts: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def report(self, label):
        print('[{}] processed={} created={} skipped={} conflicts={} errors={}'.format(
            label, self.processed, self.created, self.skipped,
            len(self.conflicts), len(self.errors),
        ))
        for item in self.conflicts[:20]:
            print('  CONFLICT {}'.format(item))
        for item in self.errors[:20]:
            print('  ERROR {}'.format(item))


#: (旧模型, 人员类型, 角色, 是否需要 Profile)
SOURCES = (
    (legacy.Admin, proto.PersonType.ADMIN, proto.Role.ADMIN, False),
    (legacy.Teacher, proto.PersonType.TEACHER, proto.Role.TEACHER, True),
    (legacy.Student, proto.PersonType.STUDENT, proto.Role.STUDENT, True),
)


class Command(BaseCommand):
    help = '把 Admin/Student/Teacher 回填为统一 Account（原型库专用）'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='只统计不写库')
        parser.add_argument('--batch-size', type=int, default=200, help='每批事务条数')
        parser.add_argument('--since', type=int, default=0, help='断点：跳过前 N 条')
        parser.add_argument('--rollback', action='store_true', help='删除所有回填产生的行')

    def handle(self, *args, **options):
        db_name = self._connection_name()
        if not db_name.startswith('smass_proto_'):
            raise CommandError(
                '拒绝执行：回填只允许在原型库（smass_proto_*）上进行，当前为 {!r}'.format(db_name)
            )

        self.stdout.write('target database : {}'.format(db_name))

        if options['rollback']:
            return self._rollback(options['dry_run'])

        return self._backfill(options)

    # ------------------------------------------------------------------
    @staticmethod
    def _connection_name():
        from django.db import connection

        return connection.settings_dict['NAME']

    def _rollback(self, dry_run):
        qs = proto.Account.objects.exclude(legacy_source='')
        count = qs.count()
        self.stdout.write('rollback candidates: {}'.format(count))

        if dry_run:
            self.stdout.write(self.style.WARNING('dry-run：未删除'))
            return

        with transaction.atomic():
            deleted, detail = qs.delete()

        self.stdout.write(self.style.SUCCESS(
            'rollback done: deleted={} detail={}'.format(deleted, detail)
        ))

    def _backfill(self, options):
        dry_run = options['dry_run']
        batch_size = max(1, options['batch_size'])
        since = max(0, options['since'])
        stats = Stats()

        for model, person_type, role, needs_profile in SOURCES:
            rows = list(model.objects.order_by('pk'))
            self.stdout.write(
                'source {:<8} rows={}'.format(model.__name__, len(rows))
            )

            for index, row in enumerate(rows):
                stats.processed += 1
                if index < since:
                    continue

                pk_text = str(row.pk)

                if proto.Account.objects.filter(
                    legacy_source=model.__name__, legacy_pk=pk_text
                ).exists():
                    stats.skipped += 1
                    continue

                # 命名空间冲突：同一 login_name 已被其他来源占用
                if proto.Account.objects.filter(login_name=pk_text).exists():
                    stats.conflicts.append(
                        '{} pk={} 与已有 account.login_name 冲突'.format(model.__name__, pk_text)
                    )
                    stats.skipped += 1
                    continue

                if dry_run:
                    stats.created += 1
                    continue

                try:
                    with transaction.atomic():
                        account = proto.Account.objects.create(
                            login_name=pk_text,
                            password=row.password,  # 原样迁移，绝不重新加密
                            display_name=getattr(row, 'name', '') or '',
                            person_type=person_type,
                            is_active=True,
                            must_change_password=True,
                            legacy_source=model.__name__,
                            legacy_pk=pk_text,
                        )
                        proto.AccountRole.objects.create(account=account, role=role)

                        if needs_profile and person_type == proto.PersonType.STUDENT:
                            proto.StudentProfile.objects.create(
                                account=account,
                                student_no=pk_text,
                                name=getattr(row, 'name', '') or '',
                                pinyin=getattr(row, 'pinyin', None),
                                sex=getattr(row, 'sex', None),
                                nation=getattr(row, 'nation', None),
                                card_id=getattr(row, 'cardID', '') or '',
                                phone=getattr(row, 'phone', None),
                                qq=getattr(row, 'qq', None),
                                address=getattr(row, 'address', None),
                                classes_name=str(getattr(row, 'classes', '') or ''),
                                political=getattr(row, 'political', 0) or 0,
                            )
                        elif needs_profile and person_type == proto.PersonType.TEACHER:
                            proto.TeacherProfile.objects.create(
                                account=account,
                                teacher_no=pk_text,
                                name=getattr(row, 'name', '') or '',
                                pinyin=getattr(row, 'pinyin', None),
                                sex=getattr(row, 'sex', None),
                                nation=getattr(row, 'nation', None),
                                card_id=getattr(row, 'cardID', '') or '',
                                phone=getattr(row, 'phone', '') or '',
                                qq=getattr(row, 'qq', '') or '',
                                address=getattr(row, 'address', '') or '',
                                entry_time=getattr(row, 'entry_time', None),
                                college_name=str(getattr(row, 'college', '') or ''),
                                political=getattr(row, 'political', 0) or 0,
                            )
                    stats.created += 1
                except Exception as exc:  # noqa: BLE001 - 单行失败不阻断整批
                    stats.errors.append(
                        '{} pk={} 失败: {}'.format(model.__name__, pk_text, exc)
                    )

        stats.report('BACKFILL{}'.format(' (dry-run)' if dry_run else ''))
        self.stdout.write('accounts total  : {}'.format(proto.Account.objects.count()))
        self.stdout.write('account_roles   : {}'.format(proto.AccountRole.objects.count()))
        self.stdout.write('student_profile : {}'.format(proto.StudentProfile.objects.count()))
        self.stdout.write('teacher_profile : {}'.format(proto.TeacherProfile.objects.count()))
