"""学生生成：Account + StudentProfile + StudentRecord + 角色，批量写入且幂等。

PII 策略：姓名合成；手机号使用 ``100`` 开头的 11 位无效号段；不生成身份证与邮箱。
"""
from __future__ import annotations

import os
import re
from datetime import date

from django.contrib.auth.hashers import make_password

from r21_account.models import Account, AccountRole, RoleCode, StudentProfile
from smass_organization.models import StudentRecord

from . import config as sim_config
from . import names
from .rng import Rng

BATCH_SIZE = 500
PHONE_PREFIX = '100'


def password():
    return os.environ.get('SIMULATION_PASSWORD', 'Sim#2026demo')


def grade_key(years, year):
    """年级映射：最老（最早入学）为 senior，最新为 freshman。"""
    ordered = sorted(years)
    position = ordered.index(year)
    steps = max(1, len(ordered) - 1)
    ratio = position / steps
    if ratio >= 1.0:
        return 'freshman'
    if ratio >= 0.66:
        return 'sophomore'
    if ratio >= 0.33:
        return 'junior'
    return 'senior'


def class_year(class_unit):
    """班级编码形如 ``SIM-CLS-<专业四位>-<年份>-<序号>``，年份在倒数第二段。"""
    parts = class_unit.code.split('-')
    if len(parts) < 5 or not parts[-2].isdigit():
        raise ValueError('班级编码格式不符：{}'.format(class_unit.code))
    return int(parts[-2])


def generate_students(config, ctx, *, limit=None, progress=None,
                      dry_run=False):
    if dry_run:
        target = config['students'] if limit is None else min(
            limit, config['students'])
        return {'created': 0, 'target': target,
                'classes': config['classes'], 'dry_run': True}
    rng = Rng(os.environ.get('SIM_SEED', 0), 'students')
    years = sim_config.grade_labels(config)
    classes = list(
        StudentRecord._meta.apps.get_model('smass_organization',
                                           'OrganizationUnit')
        .objects.filter(code__startswith='SIM-CLS-').order_by('code'))
    hashed = make_password(password())
    existing = set(
        Account.objects.filter(login_name__startswith='sim_stu_')
        .values_list('login_name', flat=True))
    per_class = config['students_per_class']
    total_target = len(classes) * per_class if limit is None else min(
        limit, len(classes) * per_class)

    accounts = []
    pending = []
    seq = 0
    created = 0
    for class_unit in classes:
        year = class_year(class_unit)
        grade_key_value = grade_key(years, year)
        for order in range(per_class):
            seq += 1
            if seq > total_target:
                break
            student_no = 'S{}{:05d}'.format(year, seq)
            login_name = 'sim_stu_{}'.format(student_no)
            if login_name in existing:
                continue
            name = names.compose(rng, seq)
            status = rng.weighted(
                sim_config.STATUS_BY_GRADE[grade_key_value])
            pending.append({
                'seq': seq, 'student_no': student_no, 'login_name': login_name,
                'name': name, 'class_unit': class_unit, 'year': year,
                'status': status,
            })
            accounts.append(Account(
                login_name=login_name, display_name=name,
                person_type='student', password=hashed, is_active=True,
                must_change_password=False))
            if len(accounts) >= BATCH_SIZE:
                created += _flush(accounts, pending, ctx, config)
                accounts, pending = [], []
                if progress:
                    progress(created)
        if seq > total_target:
            break
    if accounts:
        created += _flush(accounts, pending, ctx, config)
    ctx.stage_done('students', {'students': created, 'target': total_target})
    return {'created': created, 'target': total_target, 'classes': len(classes)}


def _flush(accounts, pending, ctx, config):
    Account.objects.bulk_create(accounts, batch_size=BATCH_SIZE)
    logins = [item['login_name'] for item in pending]
    id_map = dict(Account.objects.filter(
        login_name__in=logins).values_list('login_name', 'pk'))
    profiles = []
    records = []
    roles = []
    for item in pending:
        account_id = id_map.get(item['login_name'])
        if not account_id:
            continue
        class_unit = item['class_unit']
        major = class_unit.parent
        college = major.parent if major is not None else None
        profiles.append(StudentProfile(
            account_id=account_id, student_no=item['student_no'],
            name=item['name'],
            college_name=college.name if college else '',
            classes_name=class_unit.name))
        records.append(StudentRecord(
            student_no=item['student_no'], name=item['name'],
            account_id=account_id, unit=class_unit, status=item['status'],
            enrolled_at=date(item['year'], 9, 1),
            extra={'sim_batch': ctx.code,
                   'phone': '{}{:08d}'.format(PHONE_PREFIX, item['seq'])}))
        roles.append(AccountRole(account_id=account_id,
                                 role=RoleCode.STUDENT))
    StudentProfile.objects.bulk_create(profiles, batch_size=BATCH_SIZE)
    StudentRecord.objects.bulk_create(records, batch_size=BATCH_SIZE)
    AccountRole.objects.bulk_create(roles, ignore_conflicts=True,
                                    batch_size=BATCH_SIZE)
    # MySQL 的 bulk_create 不回填主键：按学号回查后再登记对象索引
    record_ids = dict(
        StudentRecord.objects
        .filter(student_no__in=[item['student_no'] for item in pending])
        .values_list('student_no', 'pk'))
    for account_id in id_map.values():
        ctx.remember('r21_account.Account', account_id)
    for pk in record_ids.values():
        ctx.remember('organization.StudentRecord', pk)
    ctx.flush()
    return len(records)
