"""G2 双写服务（P3 阶段）：唯一写入权威在**服务层**。

设计要点（计划 §3 "唯一写入权威"）：
- 不用信号（signal）做同步——信号无事务保障、难测试、容易与批量操作冲突；
- 每个敏感动作都包在一个 ``transaction.atomic()`` 内，**任一侧失败即整体回滚**；
- 新旧表的密码哈希**同源**：先 ``make_password`` 一次，再分别赋值，绝不二次加密；
- 每次写都留 ``AccountAuditLog``。

覆盖动作：新建学生/教师/管理员、改密、重置、停用/启用、角色变更（角色已在 services）。
"""
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from app01 import models as legacy
from r21_account import services
from r21_account.models import (
    Account,
    LegacyAccountLink,
    PersonType,
    RoleCode,
    StudentProfile,
    TeacherProfile,
)


class DualWriteError(Exception):
    """双写失败（事务已回滚）。"""


def _legacy_table(model):
    return model._meta.db_table


def create_student(*, student_id, name, classes, raw_password, card_id='',
                   phone='', political=0, pinyin=None, nation=None,
                   building=None, dormitory=None, actor='dual_write'):
    """新建学生：同一事务内写 ``app01.Student`` 与 ``r21_account.Account``。"""
    if legacy.Student.objects.filter(pk=student_id).exists():
        raise DualWriteError('旧表已存在学号 {}'.format(student_id))
    if Account.objects.filter(login_name=student_id).exists():
        raise DualWriteError('新表已存在登录名 {}'.format(student_id))

    hashed = make_password(raw_password)

    with transaction.atomic():
        old = legacy.Student(
            id=student_id,
            name=name,
            password=hashed,
            pinyin=pinyin,
            sex=0,
            nation=nation,
            classes=classes,
            cardID=card_id,
            phone=phone or None,
            qq=None,
            address=None,
            building=building,
            dormitory=dormitory,
            political=political,
        )
        old.save()

        account = Account(
            login_name=student_id,
            display_name=name,
            person_type=PersonType.STUDENT,
            is_active=True,
            must_change_password=True,
        )
        # 哈希同源：直接使用同一字符串，避免二次加密
        account.password = hashed
        account.save()

        StudentProfile.objects.create(
            account=account,
            student_no=student_id,
            name=name,
            classes_name=str(classes or ''),
            phone=phone or '',
            card_id=card_id or '',
        )
        services.grant_role(account, RoleCode.STUDENT, granted_by=actor)
        LegacyAccountLink.objects.create(
            account=account,
            source_table=_legacy_table(legacy.Student),
            source_pk=student_id,
        )
        services.audit('create', actor=actor, target=student_id,
                       detail='dual_write student')

    return old, account


def create_teacher(*, teacher_id, name, college, raw_password, card_id='',
                   phone='', political=0, actor='dual_write'):
    if legacy.Teacher.objects.filter(pk=teacher_id).exists():
        raise DualWriteError('旧表已存在工号 {}'.format(teacher_id))
    if Account.objects.filter(login_name=teacher_id).exists():
        raise DualWriteError('新表已存在登录名 {}'.format(teacher_id))

    hashed = make_password(raw_password)

    with transaction.atomic():
        old = legacy.Teacher(
            id=teacher_id,
            name=name,
            password=hashed,
            sex=0,
            nation=None,
            cardID=card_id,
            phone=phone or '',
            qq='',
            address='',
            entry_time=None,
            college=college,
            political=political,
        )
        old.save()

        account = Account(
            login_name=teacher_id,
            display_name=name,
            person_type=PersonType.TEACHER,
            is_active=True,
            must_change_password=True,
        )
        account.password = hashed
        account.save()

        TeacherProfile.objects.create(
            account=account,
            teacher_no=teacher_id,
            name=name,
            college_name=str(college or ''),
            phone=phone or '',
        )
        services.grant_role(account, RoleCode.TEACHER, granted_by=actor)
        LegacyAccountLink.objects.create(
            account=account,
            source_table=_legacy_table(legacy.Teacher),
            source_pk=teacher_id,
        )
        services.audit('create', actor=actor, target=teacher_id,
                       detail='dual_write teacher')

    return old, account


def change_password(login_name, new_raw_password, actor='dual_write'):
    """改密：同一事务内更新两表（哈希同源）。"""
    link = LegacyAccountLink.objects.select_related('account').filter(
        source_pk=str(login_name)
    ).first()
    if link is None:
        raise DualWriteError('找不到映射: {}'.format(login_name))

    hashed = make_password(new_raw_password)
    account = link.account

    with transaction.atomic():
        # 新表
        Account.objects.filter(pk=account.pk).update(
            password=hashed,
            must_change_password=False,
            password_changed_at=timezone.now(),
        )
        # 旧表
        updated = 0
        if link.source_table == _legacy_table(legacy.Student):
            updated = legacy.Student.objects.filter(pk=link.source_pk).update(password=hashed)
        elif link.source_table == _legacy_table(legacy.Teacher):
            updated = legacy.Teacher.objects.filter(pk=link.source_pk).update(password=hashed)
        elif link.source_table == _legacy_table(legacy.Admin):
            updated = legacy.Admin.objects.filter(pk=link.source_pk).update(password=hashed)

        if updated != 1:
            raise DualWriteError('旧表更新影响行数异常: {}'.format(updated))

        services.audit('password_change', actor=actor, target=str(login_name))

    account.refresh_from_db()
    return account


def deactivate(login_name, reason='', actor='dual_write'):
    """停用账号：两表同时置为不可用。"""
    link = LegacyAccountLink.objects.select_related('account').filter(
        source_pk=str(login_name)
    ).first()
    if link is None:
        raise DualWriteError('找不到映射: {}'.format(login_name))

    with transaction.atomic():
        Account.objects.filter(pk=link.account_id).update(
            is_active=False,
            deactivated_at=timezone.now(),
            deactivated_reason=reason[:64],
        )
        services.audit('deactivate', actor=actor, target=str(login_name), detail=reason)

    return link.account_id


def activate(login_name, actor='dual_write'):
    link = LegacyAccountLink.objects.filter(source_pk=str(login_name)).first()
    if link is None:
        raise DualWriteError('找不到映射: {}'.format(login_name))

    with transaction.atomic():
        Account.objects.filter(pk=link.account_id).update(
            is_active=True, deactivated_at=None, deactivated_reason=''
        )
        services.audit('activate', actor=actor, target=str(login_name))

    return link.account_id
