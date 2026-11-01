"""P3 岗位反推：由学生/班级规模与教学工作量计算教师、辅导员、班主任、学院管理人员。

口径（可在命令里覆盖）：
- 每班每学期 8 门课，每教学班每周 3 学时；
- 教师最大周授课 12 学时 → 教师数 = ceil(总周学时 / 12) = 班数 × 2；
- 每辅导员最多负责 8 个班；
- 每班 1 名班主任（从教师池选派，可兼任）；
- 每学院 1 名学院管理员 + 1 名教学经办 + 1 名学生事务经办（统一最小权限：college_admin，不授 system_admin）。
"""
from __future__ import annotations

import math

from django.contrib.auth.hashers import make_password

from r21_account.models import Account, AccountRole, RoleCode, TeacherProfile
from smass_organization.models import OrganizationMembership, OrganizationUnit

from . import names
from .people import password
from .rng import Rng

COURSES_PER_CLASS = 8
WEEKLY_HOURS_PER_SECTION = 3
MAX_TEACHER_WEEKLY = 12
COUNSELOR_CLASS_LIMIT = 8
BATCH_SIZE = 500


def plan(classes):
    sections = classes * COURSES_PER_CLASS
    weekly = sections * WEEKLY_HOURS_PER_SECTION
    teachers = max(1, math.ceil(weekly / MAX_TEACHER_WEEKLY))
    counselors = max(1, math.ceil(classes / COUNSELOR_CLASS_LIMIT))
    return {
        'classes': classes,
        'sections_planned': sections,
        'weekly_hours': weekly,
        'teachers': teachers,
        'counselors': counselors,
        'head_teachers': classes,
        'college_admins': None,  # 由学院数决定
    }


def generate_staff(config, ctx, *, dry_run=False):
    classes = list(OrganizationUnit.objects.filter(
        code__startswith='SIM-CLS-').order_by('code'))
    colleges = list(OrganizationUnit.objects.filter(
        code__startswith='SIM-COL-').order_by('code'))
    if not classes or not colleges:
        raise ValueError('请先生成组织（--stage org）')
    plan_result = plan(len(classes))
    plan_result['college_admins'] = len(colleges) * 3
    if dry_run:
        return dict(plan_result, created=0, dry_run=True)

    rng = Rng(0, 'staff')
    hashed = make_password(password())
    existing_teachers = set(
        Account.objects.filter(login_name__startswith='sim_tea_')
        .values_list('login_name', flat=True))
    existing_admins = set(
        Account.objects.filter(login_name__startswith='sim_adm_')
        .values_list('login_name', flat=True))

    # 学院 -> 班级
    by_college = {college.pk: [] for college in colleges}
    for class_unit in classes:
        major = class_unit.parent
        college = major.parent if major is not None else None
        if college is not None and college.pk in by_college:
            by_college[college.pk].append(class_unit)

    # 1) 教师账号（每学院：班数 × 2）
    accounts = []
    meta = []
    seq = 0
    created_teachers = 0
    for college in colleges:
        need = len(by_college[college.pk]) * 2
        for _ in range(need):
            seq += 1
            teacher_no = 'T{:06d}'.format(seq)
            name = names.compose(rng, seq + 1000)
            login_name = 'sim_tea_{}'.format(teacher_no)
            if login_name in existing_teachers:
                continue
            accounts.append(Account(
                login_name=login_name, display_name=name,
                person_type='teacher', password=hashed, is_active=True,
                must_change_password=False))
            meta.append({'teacher_no': teacher_no, 'name': name,
                         'login_name': login_name, 'college': college})
            if len(accounts) >= BATCH_SIZE:
                created_teachers += _flush_teachers(accounts, meta, ctx)
                accounts, meta = [], []
    if accounts:
        created_teachers += _flush_teachers(accounts, meta, ctx)
    ctx.flush()

    teacher_ids = list(Account.objects.filter(
        login_name__startswith='sim_tea_').values_list('id', flat=True))
    teacher_ids.sort()
    # 幂等：先清掉仿真班级上的辅导员/班主任关系再重建（限定 SIM 班级）
    if teacher_ids:
        OrganizationMembership.objects.filter(
            unit__code__startswith='SIM-CLS-',
            role__in=['counselor', 'head_teacher']).delete()
    seen = set()

    # 2) 辅导员：每 8 个班 1 名（从教师池选，兼课）
    counselor_ids = rng.sample(teacher_ids, plan_result['counselors'])
    memberships = []
    for index, class_unit in enumerate(classes):
        account_id = counselor_ids[index % len(counselor_ids)]
        key = (account_id, class_unit.pk)
        if key in seen:
            continue
        seen.add(key)
        memberships.append(OrganizationMembership(
            account_id=account_id, unit=class_unit, role='counselor'))

    # 3) 班主任：每班一名（尽量不与辅导员同一人；冲突时换人）
    for class_unit in classes:
        for candidate in rng.shuffle(teacher_ids):
            key = (candidate, class_unit.pk)
            if key in seen:
                continue
            seen.add(key)
            memberships.append(OrganizationMembership(
                account_id=candidate, unit=class_unit, role='head_teacher'))
            break

    OrganizationMembership.objects.bulk_create(
        memberships, ignore_conflicts=True, batch_size=BATCH_SIZE)

    # 4) 学院管理人员（最小权限：college_admin，不授 system_admin）
    admin_accounts = []
    admin_meta = []
    for college_index, college in enumerate(colleges):
        for suffix, role in (('admin', 'college_admin'),
                             ('academic_staff', 'academic_staff'),
                             ('student_affairs', 'student_affairs')):
            login_name = 'sim_adm_{:02d}_{}'.format(college_index + 1, suffix)
            if login_name in existing_admins:
                continue
            name = '{}管理{}'.format(
                college.name[:2], {'admin': '员', 'academic_staff': '教务',
                                   'student_affairs': '学工'}[suffix])
            admin_accounts.append(Account(
                login_name=login_name, display_name=name[:16],
                person_type='admin', password=hashed, is_active=True,
                must_change_password=False))
            admin_meta.append({'login_name': login_name, 'college': college,
                               'role': role})
    Account.objects.bulk_create(admin_accounts, batch_size=BATCH_SIZE)
    login_names = [item['login_name'] for item in admin_meta]
    id_map = dict(Account.objects.filter(
        login_name__in=login_names).values_list('login_name', 'pk'))
    created_admins = sum(1 for item in admin_meta
                         if item['login_name'] not in existing_admins)
    admin_roles = []
    admin_memberships = []
    for item in admin_meta:
        account_id = id_map.get(item['login_name'])
        if not account_id:
            continue
        admin_roles.append(AccountRole(account_id=account_id,
                                       role=RoleCode.COLLEGE_ADMIN))
        admin_memberships.append(OrganizationMembership(
            account_id=account_id, unit=item['college'], role=item['role']))
        ctx.remember('r21_account.Account', account_id)
    AccountRole.objects.bulk_create(admin_roles, ignore_conflicts=True,
                                    batch_size=BATCH_SIZE)
    OrganizationMembership.objects.bulk_create(
        admin_memberships, ignore_conflicts=True, batch_size=BATCH_SIZE)

    result = dict(plan_result, created=created_teachers,
                  admins=created_admins,
                  counselor_links=len(counselor_ids),
                  teacher_memberships=len(memberships))
    ctx.stage_done('staff', {
        'teachers': len(teacher_ids), 'counselors': len(counselor_ids),
        'admins': len(id_map),
    })
    return result


def _flush_teachers(accounts, meta, ctx):
    Account.objects.bulk_create(accounts, batch_size=BATCH_SIZE)
    logins = [item['login_name'] for item in meta]
    id_map = dict(Account.objects.filter(
        login_name__in=logins).values_list('login_name', 'pk'))
    profiles = []
    roles = []
    memberships = []
    for item in meta:
        account_id = id_map.get(item['login_name'])
        if not account_id:
            continue
        profiles.append(TeacherProfile(
            account_id=account_id, teacher_no=item['teacher_no'],
            name=item['name'], college_name=item['college'].name))
        roles.append(AccountRole(account_id=account_id,
                                 role=RoleCode.TEACHER))
        memberships.append(OrganizationMembership(
            account_id=account_id, unit=item['college'], role='teacher'))
        ctx.remember('r21_account.Account', account_id)
    TeacherProfile.objects.bulk_create(profiles, batch_size=BATCH_SIZE)
    AccountRole.objects.bulk_create(roles, ignore_conflicts=True,
                                    batch_size=BATCH_SIZE)
    OrganizationMembership.objects.bulk_create(
        memberships, ignore_conflicts=True, batch_size=BATCH_SIZE)
    return len(profiles)
