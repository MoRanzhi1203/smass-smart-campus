"""H2：为 ApprovalTask 建立 MySQL 真正生效的"单 open 任务"唯一约束。

背景
----
``ApprovalTask`` 原本声明了
``UniqueConstraint(fields=['instance','node'], condition=Q(status='open'))``，
但 MySQL 不支持条件索引（``models.W036``），该约束**从未在数据库创建**。

方案
----
与 ``r21_account.0002`` 同理，用两个 VIRTUAL 生成列把"open"编码进列值：

- ``status = 'open'`` → ``open_instance_id = instance_id``，``open_node_id = node_id``
- 其他状态 → 两列均为 ``NULL``

唯一索引 ``(open_instance_id, open_node_id)``：
- 同一实例同一节点只能有一个 open 任务
- 已完成/已取消的任务（NULL）永不冲突，历史可累积

回滚
----
``reverse_sql`` 删除索引与两列。
"""

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE `smass_workflow_approvaltask`
  ADD COLUMN `open_instance_id` BIGINT
    GENERATED ALWAYS AS (IF(`status` = 'open', `instance_id`, NULL)) VIRTUAL,
  ADD COLUMN `open_node_id` BIGINT
    GENERATED ALWAYS AS (IF(`status` = 'open', `node_id`, NULL)) VIRTUAL,
  ADD UNIQUE KEY `uq_r6_open_task` (`open_instance_id`, `open_node_id`);
"""

REVERSE_SQL = """
ALTER TABLE `smass_workflow_approvaltask`
  DROP INDEX `uq_r6_open_task`,
  DROP COLUMN `open_node_id`,
  DROP COLUMN `open_instance_id`;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('smass_workflow', '0002_remove_notification_r6_uniq_notification_event_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='approvaltask',
                    name='r6_uniq_open_task',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=FORWARD_SQL,
                    reverse_sql=REVERSE_SQL,
                ),
            ],
        ),
    ]
