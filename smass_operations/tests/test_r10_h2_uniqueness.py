"""H2：MySQL 数据库级唯一性约束（生成列 + 唯一索引）。

验证的不是"服务层认为唯一"，而是**数据库真的拒绝重复**：
- 重复 active 角色 -> `IntegrityError`（1062 Duplicate entry）
- 撤销后可以新建 active
- 历史撤销行保留
- 并发授予时只有一个成功

用 `TransactionTestCase` 以便多线程共享真实数据库连接。
"""
import threading

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from r21_account import services as core_services
from r21_account.models import Account, AccountRole, RoleCode
from smass_workflow import services as workflow_services
from smass_workflow.models import (
    ApprovalTask,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNode,
    WorkflowVersion,
)

PASSWORD = 'H2Pass#2024'


def make_account(login):
    account = Account.objects.create_user(
        login, PASSWORD, display_name=login, person_type='admin')
    account.must_change_password = False
    account.save(update_fields=['must_change_password'])
    return Account.objects.get(pk=account.pk)


class SchemaLevelAssertions(TransactionTestCase):
    """先证明索引真的存在，再证明它真的起作用。"""

    def test_generated_columns_and_unique_indexes_exist(self):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'r21_account_accountrole'
                  AND INDEX_NAME = 'uq_r21_active_role'
                  AND NON_UNIQUE = 0
            """)
            self.assertGreater(
                cur.fetchone()[0], 0, 'uq_r21_active_role 唯一索引不存在')

            cur.execute("""
                SELECT COUNT(*) FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'smass_workflow_approvaltask'
                  AND INDEX_NAME = 'uq_r6_open_task'
                  AND NON_UNIQUE = 0
            """)
            self.assertGreater(
                cur.fetchone()[0], 0, 'uq_r6_open_task 唯一索引不存在')

    def test_generated_columns_are_virtual(self):
        with connection.cursor() as cur:
            cur.execute("""
                SELECT COLUMN_NAME, EXTRA FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME IN ('r21_account_accountrole',
                                     'smass_workflow_approvaltask')
                  AND GENERATION_EXPRESSION <> ''
            """)
            rows = dict(cur.fetchall())

        self.assertIn('active_account_id', rows)
        self.assertIn('open_instance_id', rows)
        self.assertIn('open_node_id', rows)
        for name, extra in rows.items():
            self.assertIn('VIRTUAL GENERATED', extra, name)


class ActiveRoleUniquenessTests(TransactionTestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.account = make_account('H2ROLE')

    def tearDown(self):
        AccountRole.objects.filter(account=self.account).delete()

    def test_duplicate_active_rejected_by_database(self):
        AccountRole.objects.create(
            account=self.account, role=RoleCode.TEACHER, granted_by='h2')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccountRole.objects.create(
                    account=self.account, role=RoleCode.TEACHER, granted_by='dup')

        self.assertEqual(
            AccountRole.objects.filter(
                account=self.account, role=RoleCode.TEACHER,
                revoked_at__isnull=True).count(),
            1)

    def test_revoke_then_regrant_allowed(self):
        first = AccountRole.objects.create(
            account=self.account, role=RoleCode.TEACHER, granted_by='h2')

        first.revoked_at = timezone.now()
        first.save(update_fields=['revoked_at'])

        second = AccountRole.objects.create(
            account=self.account, role=RoleCode.TEACHER, granted_by='again')

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(
            AccountRole.objects.filter(
                account=self.account, role=RoleCode.TEACHER,
                revoked_at__isnull=True).count(),
            1)

    def test_history_rows_preserved(self):
        for _ in range(3):
            record = AccountRole.objects.create(
                account=self.account, role=RoleCode.TEACHER, granted_by='cycle')
            record.revoked_at = timezone.now()
            record.save(update_fields=['revoked_at'])

        self.assertEqual(AccountRole.objects.filter(account=self.account).count(), 3)
        self.assertEqual(
            AccountRole.objects.filter(
                account=self.account, revoked_at__isnull=True).count(), 0)

    def test_different_roles_do_not_conflict(self):
        AccountRole.objects.create(
            account=self.account, role=RoleCode.TEACHER, granted_by='h2')
        AccountRole.objects.create(
            account=self.account, role=RoleCode.STUDENT, granted_by='h2')

        self.assertEqual(
            AccountRole.objects.filter(
                account=self.account, revoked_at__isnull=True).count(), 2)

    def test_concurrent_grants_produce_exactly_one_active(self):
        """4 个线程同时授予同一角色：只能有一个成功。"""
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(4)

        def worker(index):
            barrier.wait()
            try:
                AccountRole.objects.create(
                    account=self.account,
                    role=RoleCode.TEACHER,
                    granted_by='race{}'.format(index),
                )
                outcome = 'ok'
            except IntegrityError:
                outcome = 'duplicate'
            except Exception as exc:  # noqa: BLE001
                outcome = 'error:{}'.format(type(exc).__name__)
            finally:
                connection.close()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(len(results), 4, '有线程未完成: {}'.format(results))

        active = AccountRole.objects.filter(
            account=self.account, role=RoleCode.TEACHER,
            revoked_at__isnull=True).count()
        self.assertEqual(
            active, 1,
            '并发授予产生了 {} 个 active 记录（结果: {}）'.format(active, results))
        self.assertEqual(results.count('ok'), 1, '成功次数应为 1: {}'.format(results))


class OpenTaskUniquenessTests(TransactionTestCase):
    def setUp(self):
        core_services.ensure_role_groups()
        self.definition = workflow_services.create_definition('H2-FLOW', 'H2流程')
        version = workflow_services.create_draft_version(self.definition)
        workflow_services.add_node(version, 'start', '发起', 'start')
        workflow_services.add_node(version, 'approve', '审批', 'approval')
        workflow_services.add_node(version, 'end', '完成', 'end')
        workflow_services.add_transition(version, 'start', 'approve', 'submit')
        workflow_services.add_transition(version, 'approve', 'end', 'approve')
        workflow_services.publish_version(version)
        self.version = version

        self.instance = workflow_services.start_instance(
            version, subject_type='h2', subject_id='H2-1', created_by='h2')
        workflow_services.transition(self.instance, 'submit')

    def tearDown(self):
        ApprovalTask.objects.filter(instance=self.instance).delete()

    def test_duplicate_open_task_rejected_by_database(self):
        node = self.instance.current_node
        self.assertEqual(
            ApprovalTask.objects.filter(
                instance=self.instance, node=node, status='open').count(), 1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ApprovalTask.objects.create(
                    instance=self.instance, node=node, status='open')

    def test_closed_task_allows_new_open(self):
        task = ApprovalTask.objects.get(
            instance=self.instance, status='open')
        task.status = 'done'
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_at'])

        # 同一 node 再开一个任务应被允许（前一个已非 open）
        again = ApprovalTask.objects.create(
            instance=self.instance, node=task.node, status='open')
        self.assertIsNotNone(again.pk)

        self.assertEqual(
            ApprovalTask.objects.filter(
                instance=self.instance, node=task.node, status='open').count(), 1)

    def test_cancelled_tasks_do_not_conflict(self):
        task = ApprovalTask.objects.get(instance=self.instance, status='open')
        task.status = 'cancelled'
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_at'])

        for _ in range(3):
            record = ApprovalTask.objects.create(
                instance=self.instance, node=task.node, status='cancelled')
            self.assertIsNotNone(record.pk)
