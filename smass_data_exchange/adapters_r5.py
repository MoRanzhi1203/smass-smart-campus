"""S25-R5 适配器：学年 / 学期 / 课程 / 教学班 / 选课 五类导入。

复用 R4 适配器的模式与引擎能力；本文件**独立于** ``adapters.py``，
由该模块在末尾显式导入以完成注册（避免循环依赖）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from smass_data_exchange.adapters import (
    BaseAdapter,
    _actor_id,
    _check_import_permission,
    register_adapter,
)
from smass_data_exchange.schema import DatasetSchema, FieldSpec


def _err(row, column, code, message):
    return {'row': row, 'column': column, 'code': code, 'message': message}


def _permission_error(exc):
    return [_err(0, '', 'PERMISSION_DENIED',
                 '当前账号没有导入权限（{}）'.format(exc))]


def _create_job(dataset, total, actor):
    """创建导入作业记录（可选）。

    R5 环境（``settings_r5``）只安装 ``smass_academic``，没有
    ``smass_organization`` 的 ``DataImportJob``。此时导入本身仍应可用，
    只是没有持久化的作业历史——这是环境能力差异，不是失败。
    """
    try:
        from smass_organization.models import DataImportJob
    except Exception:  # noqa: BLE001 - 未安装 smass_organization
        return None
    return DataImportJob.objects.create(
        kind=dataset[:32], total_rows=total, created_by=actor)


def _finish_job(job, stats, created=0, updated=0):
    if job is None:
        return None
    from django.utils import timezone

    from smass_organization.models import IMPORT_COMMITTED

    job.success_rows = created + updated + stats.get('skipped', 0)
    job.error_rows = stats.get('conflict', 0)
    job.status = IMPORT_COMMITTED
    job.committed_at = timezone.now()
    job.save(update_fields=['status', 'success_rows', 'error_rows', 'committed_at'])
    return job


def _parse_date(value):
    """把已规范化的 YYYY-MM-DD 转回 date；空返回 None。"""
    if not value:
        return None
    from datetime import datetime

    return datetime.strptime(value, '%Y-%m-%d').date()


# ---------------------------------------------------------------------------
# 学年
# ---------------------------------------------------------------------------
class R5AcademicYearAdapter(BaseAdapter):
    dataset = 'r5_academic_years'

    def __init__(self):
        self.schema = DatasetSchema(
            code=self.dataset, version='1', title='学年导入（R5）',
            fields=(
                FieldSpec('code', '学年编码', required=True, max_length=16,
                          help='唯一，如 2024-2025', example='2024-2025'),
                FieldSpec('start_date', '开始日期', required=True, dtype='date',
                          example='2024-09-01'),
                FieldSpec('end_date', '结束日期', required=True, dtype='date',
                          example='2025-08-31'),
            ),
            instructions=('学年编码唯一；日期格式 YYYY-MM-DD',
                          '结束日期必须晚于开始日期'),
            notes=('不会自动把任何学年设为"当前学年"，需在页面上单独操作',),
        )

    def validate(self, rows, account, *, request=None):
        from smass_academic.models import AcademicYear

        try:
            _check_import_permission(account)
        except Exception as exc:  # noqa: BLE001
            return [], _permission_error(exc)

        codes = {str(r.get('code') or '').strip() for r in rows}
        codes.discard('')
        existing = {y.code: y for y in AcademicYear.objects.filter(code__in=codes)}

        seen, validated, errors = set(), [], []
        for row in rows:
            line = row.get('__row__', 0)
            code = str(row.get('code') or '').strip()
            start = row.get('start_date')
            end = row.get('end_date')

            row_errors = []
            if not code:
                row_errors.append(('code', 'EMPTY_CODE', '学年编码不能为空'))
            elif code in seen:
                row_errors.append(('code', 'DUPLICATE_IN_FILE', '文件内编码重复'))
            else:
                seen.add(code)

            if start and end and end <= start:
                row_errors.append(('end_date', 'BAD_RANGE', '结束日期必须晚于开始日期'))

            if row_errors:
                for column, ec, message in row_errors:
                    errors.append(_err(line, column, ec, message))
                continue

            record = existing.get(code)
            if record is None:
                plan = 'create'
            elif (record.start_date.isoformat() == start
                  and record.end_date.isoformat() == end):
                plan = 'skip'
            else:
                plan = 'update'

            item = dict(row)
            item.update({'__plan__': plan, '__code__': code,
                         '__existing_pk__': record.pk if record else None})
            validated.append(item)
        return validated, errors

    def commit(self, validated, account, *, request=None):
        from django.db import transaction

        from smass_academic.models import AcademicYear

        actor = _actor_id(account)
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}
        with transaction.atomic():
            job = _create_job(self.dataset, len(validated), actor)
            for item in validated:
                plan = item['__plan__']
                if plan == 'skip':
                    stats['skipped'] += 1
                    continue
                payload = {
                    'start_date': _parse_date(item.get('start_date')),
                    'end_date': _parse_date(item.get('end_date')),
                }
                if plan == 'create':
                    AcademicYear.objects.create(code=item['__code__'], **payload)
                    stats['created'] += 1
                else:
                    updated = AcademicYear.objects.filter(
                        pk=item['__existing_pk__']).update(**payload)
                    if updated:
                        stats['updated'] += 1
                    else:
                        stats['conflict'] += 1
            _finish_job(job, stats, stats['created'], stats['updated'])
        return job, stats

    def describe_row(self, row, account):
        return {'row': row.get('__row__', 0), 'code': row.get('__code__', ''),
                'start_date': row.get('start_date', ''),
                'end_date': row.get('end_date', ''),
                'plan': row.get('__plan__', '')}


# ---------------------------------------------------------------------------
# 学期
# ---------------------------------------------------------------------------
class R5TermAdapter(BaseAdapter):
    dataset = 'r5_academic_terms'

    def __init__(self):
        from smass_academic.models import AcademicTerm

        semesters = tuple(choice[0] for choice in AcademicTerm.SEMESTER_CHOICES)
        self.schema = DatasetSchema(
            code=self.dataset, version='1', title='学期导入（R5）',
            fields=(
                FieldSpec('year_code', '学年编码', required=True, max_length=16,
                          help='必须已存在的学年', example='2024-2025'),
                FieldSpec('semester', '学期', required=True, dtype='enum',
                          choices=semesters, example=semesters[0]),
                FieldSpec('start_date', '开始日期', required=True, dtype='date',
                          example='2024-09-01'),
                FieldSpec('end_date', '结束日期', required=True, dtype='date',
                          example='2025-01-15'),
                FieldSpec('name', '显示名', max_length=32, example='2024 秋'),
            ),
            instructions=('学年编码 + 学期唯一确定一个学期',
                          '结束日期必须晚于开始日期'),
        )

    def validate(self, rows, account, *, request=None):
        from smass_academic.models import AcademicTerm, AcademicYear

        try:
            _check_import_permission(account)
        except Exception as exc:  # noqa: BLE001
            return [], _permission_error(exc)

        year_codes = {str(r.get('year_code') or '').strip() for r in rows}
        year_codes.discard('')
        years = {y.code: y for y in AcademicYear.objects.filter(code__in=year_codes)}

        seen, validated, errors = set(), [], []
        for row in rows:
            line = row.get('__row__', 0)
            year_code = str(row.get('year_code') or '').strip()
            semester = str(row.get('semester') or '').strip()
            start, end = row.get('start_date'), row.get('end_date')

            row_errors = []
            year = years.get(year_code)
            if not year_code:
                row_errors.append(('year_code', 'EMPTY_YEAR', '学年编码不能为空'))
            elif year is None:
                row_errors.append(('year_code', 'UNKNOWN_YEAR', '学年不存在'))
            if not semester:
                row_errors.append(('semester', 'EMPTY_SEMESTER', '学期不能为空'))
            if start and end and end <= start:
                row_errors.append(('end_date', 'BAD_RANGE', '结束日期必须晚于开始日期'))

            key = (year_code, semester)
            if key in seen:
                row_errors.append(('semester', 'DUPLICATE_IN_FILE', '文件内重复的学年+学期'))
            else:
                seen.add(key)

            if row_errors:
                for column, ec, message in row_errors:
                    errors.append(_err(line, column, ec, message))
                continue

            existing = AcademicTerm.objects.filter(year=year, semester=semester).first()
            if existing is None:
                plan = 'create'
            elif (existing.start_date.isoformat() == start
                  and existing.end_date.isoformat() == end):
                plan = 'skip'
            else:
                plan = 'update'

            item = dict(row)
            item.update({'__plan__': plan, '__year_pk__': year.pk,
                         '__semester__': semester,
                         '__existing_pk__': existing.pk if existing else None})
            validated.append(item)
        return validated, errors

    def commit(self, validated, account, *, request=None):
        from django.db import transaction

        from smass_academic.models import AcademicTerm

        actor = _actor_id(account)
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}
        with transaction.atomic():
            job = _create_job(self.dataset, len(validated), actor)
            for item in validated:
                plan = item['__plan__']
                if plan == 'skip':
                    stats['skipped'] += 1
                    continue
                payload = {
                    'start_date': _parse_date(item.get('start_date')),
                    'end_date': _parse_date(item.get('end_date')),
                    'name': str(item.get('name') or '')[:32],
                }
                if plan == 'create':
                    AcademicTerm.objects.create(
                        year_id=item['__year_pk__'],
                        semester=item['__semester__'], **payload)
                    stats['created'] += 1
                else:
                    updated = AcademicTerm.objects.filter(
                        pk=item['__existing_pk__']).update(**payload)
                    if updated:
                        stats['updated'] += 1
                    else:
                        stats['conflict'] += 1
            _finish_job(job, stats, stats['created'], stats['updated'])
        return job, stats

    def describe_row(self, row, account):
        return {'row': row.get('__row__', 0), 'year': row.get('year_code', ''),
                'semester': row.get('semester', ''), 'plan': row.get('__plan__', '')}


# ---------------------------------------------------------------------------
# 课程
# ---------------------------------------------------------------------------
class R5CourseAdapter(BaseAdapter):
    dataset = 'r5_courses'

    def __init__(self):
        self.schema = DatasetSchema(
            code=self.dataset, version='1', title='课程导入（R5）',
            fields=(
                FieldSpec('code', '课程编码', required=True, max_length=32,
                          example='CS101'),
                FieldSpec('title', '课程名称', required=True, max_length=128,
                          example='程序设计基础'),
                FieldSpec('credit', '学分', dtype='str', max_length=8,
                          help='0.5 ~ 99.9', example='3.0'),
                FieldSpec('course_type', '课程类型', max_length=32, example='必修'),
            ),
            instructions=('课程编码唯一', '学分可留空；填了必须是数字且 0 < credit <= 99.9'),
        )

    def validate(self, rows, account, *, request=None):
        from smass_academic.models import Course

        try:
            _check_import_permission(account)
        except Exception as exc:  # noqa: BLE001
            return [], _permission_error(exc)

        codes = {str(r.get('code') or '').strip() for r in rows}
        codes.discard('')
        existing = {c.code: c for c in Course.objects.filter(code__in=codes)}

        seen, validated, errors = set(), [], []
        for row in rows:
            line = row.get('__row__', 0)
            code = str(row.get('code') or '').strip()
            title = str(row.get('title') or '').strip()
            raw_credit = str(row.get('credit') or '').strip()

            row_errors = []
            if not code:
                row_errors.append(('code', 'EMPTY_CODE', '课程编码不能为空'))
            elif code in seen:
                row_errors.append(('code', 'DUPLICATE_IN_FILE', '文件内课程编码重复'))
            else:
                seen.add(code)
            if not title:
                row_errors.append(('title', 'EMPTY_TITLE', '课程名称不能为空'))

            credit = None
            if raw_credit:
                try:
                    credit = Decimal(raw_credit)
                    if credit <= 0 or credit > Decimal('99.9'):
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    row_errors.append(('credit', 'BAD_CREDIT', '学分必须是 0~99.9 之间的数字'))

            if row_errors:
                for column, ec, message in row_errors:
                    errors.append(_err(line, column, ec, message))
                continue

            record = existing.get(code)
            if record is None:
                plan = 'create'
            elif (record.title == title
                  and str(record.credit) == str(credit if credit is not None else record.credit)
                  and record.course_type == str(row.get('course_type') or '')[:32]):
                plan = 'skip'
            else:
                plan = 'update'

            item = dict(row)
            item.update({'__plan__': plan, '__code__': code, '__title__': title,
                         '__credit__': credit,
                         '__existing_pk__': record.pk if record else None})
            validated.append(item)
        return validated, errors

    def commit(self, validated, account, *, request=None):
        from django.db import transaction

        from smass_academic.models import Course

        actor = _actor_id(account)
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}
        with transaction.atomic():
            job = _create_job(self.dataset, len(validated), actor)
            for item in validated:
                plan = item['__plan__']
                if plan == 'skip':
                    stats['skipped'] += 1
                    continue
                payload = {
                    'title': item['__title__'],
                    'course_type': str(item.get('course_type') or '')[:32],
                }
                if item['__credit__'] is not None:
                    payload['credit'] = item['__credit__']
                if plan == 'create':
                    Course.objects.create(code=item['__code__'], **payload)
                    stats['created'] += 1
                else:
                    updated = Course.objects.filter(
                        pk=item['__existing_pk__']).update(**payload)
                    if updated:
                        stats['updated'] += 1
                    else:
                        stats['conflict'] += 1
            _finish_job(job, stats, stats['created'], stats['updated'])
        return job, stats

    def describe_row(self, row, account):
        return {'row': row.get('__row__', 0), 'code': row.get('__code__', ''),
                'title': row.get('__title__', ''), 'plan': row.get('__plan__', '')}


# ---------------------------------------------------------------------------
# 教学班
# ---------------------------------------------------------------------------
class R5SectionAdapter(BaseAdapter):
    dataset = 'r5_sections'

    def __init__(self):
        from smass_academic.models import AcademicTerm, TeachingSection

        semesters = tuple(choice[0] for choice in AcademicTerm.SEMESTER_CHOICES)
        statuses = tuple(choice[0] for choice in TeachingSection.STATUS_CHOICES)
        self.schema = DatasetSchema(
            code=self.dataset, version='1', title='教学班导入（R5）',
            fields=(
                FieldSpec('year_code', '学年编码', required=True, max_length=16,
                          example='2024-2025'),
                FieldSpec('semester', '学期', required=True, dtype='enum',
                          choices=semesters, example=semesters[0],
                          help='取值与学期表一致'),
                FieldSpec('course_code', '课程编码', required=True, max_length=32,
                          example='CS101'),
                FieldSpec('code', '教学班号', required=True, max_length=32,
                          example='CS101-01'),
                FieldSpec('capacity', '容量', dtype='int', example='40',
                          help='0 表示不限制'),
                FieldSpec('status', '状态', dtype='enum', choices=statuses,
                          example=statuses[0]),
            ),
            instructions=('学年+学期+课程必须都存在',
                          '教学班号在同一学期内唯一', '容量 0 表示不限制'),
        )

    def validate(self, rows, account, *, request=None):
        from smass_academic.models import AcademicTerm, AcademicYear, Course, TeachingSection

        try:
            _check_import_permission(account)
        except Exception as exc:  # noqa: BLE001
            return [], _permission_error(exc)

        year_codes = {str(r.get('year_code') or '').strip() for r in rows}
        years = {y.code: y for y in AcademicYear.objects.filter(code__in=year_codes)}
        course_codes = {str(r.get('course_code') or '').strip() for r in rows}
        courses = {c.code: c for c in Course.objects.filter(code__in=course_codes)}

        terms = {}
        for year_code, year in years.items():
            for term in AcademicTerm.objects.filter(year=year):
                terms[(year_code, term.semester)] = term

        seen, validated, errors = set(), [], []
        for row in rows:
            line = row.get('__row__', 0)
            year_code = str(row.get('year_code') or '').strip()
            semester = str(row.get('semester') or '').strip()
            course_code = str(row.get('course_code') or '').strip()
            code = str(row.get('code') or '').strip()
            status = str(row.get('status') or '').strip() or 'open'

            row_errors = []
            term = terms.get((year_code, semester))
            if term is None:
                row_errors.append(('semester', 'UNKNOWN_TERM', '学年+学期不存在'))
            course = courses.get(course_code)
            if course is None:
                row_errors.append(('course_code', 'UNKNOWN_COURSE', '课程不存在'))
            if not code:
                row_errors.append(('code', 'EMPTY_CODE', '教学班号不能为空'))

            key = (year_code, semester, code)
            if key in seen:
                row_errors.append(('code', 'DUPLICATE_IN_FILE', '文件内重复的教学班'))
            else:
                seen.add(key)

            capacity = row.get('capacity')
            if capacity in (None, ''):
                capacity = 0
            try:
                capacity = int(capacity)
                if capacity < 0:
                    raise ValueError
            except (TypeError, ValueError):
                row_errors.append(('capacity', 'BAD_CAPACITY', '容量必须是非负整数'))

            if row_errors:
                for column, ec, message in row_errors:
                    errors.append(_err(line, column, ec, message))
                continue

            existing = TeachingSection.objects.filter(
                term=term, code=code).first() if term else None
            if existing is None:
                plan = 'create'
            elif (existing.course_id == course.pk
                  and existing.capacity == capacity
                  and existing.status == status):
                plan = 'skip'
            else:
                plan = 'update'

            item = dict(row)
            item.update({'__plan__': plan, '__term_pk__': term.pk,
                         '__course_pk__': course.pk, '__code__': code,
                         '__capacity__': capacity, '__status__': status,
                         '__existing_pk__': existing.pk if existing else None})
            validated.append(item)
        return validated, errors

    def commit(self, validated, account, *, request=None):
        from django.db import transaction

        from smass_academic.models import TeachingSection

        actor = _actor_id(account)
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}
        with transaction.atomic():
            job = _create_job(self.dataset, len(validated), actor)
            for item in validated:
                plan = item['__plan__']
                if plan == 'skip':
                    stats['skipped'] += 1
                    continue
                payload = {'course_id': item['__course_pk__'],
                           'capacity': item['__capacity__'],
                           'status': item['__status__']}
                if plan == 'create':
                    TeachingSection.objects.create(
                        term_id=item['__term_pk__'], code=item['__code__'], **payload)
                    stats['created'] += 1
                else:
                    updated = TeachingSection.objects.filter(
                        pk=item['__existing_pk__']).update(**payload)
                    if updated:
                        stats['updated'] += 1
                    else:
                        stats['conflict'] += 1
            _finish_job(job, stats, stats['created'], stats['updated'])
        return job, stats

    def describe_row(self, row, account):
        return {'row': row.get('__row__', 0), 'code': row.get('__code__', ''),
                'capacity': row.get('__capacity__', 0),
                'plan': row.get('__plan__', '')}


# ---------------------------------------------------------------------------
# 选课（含容量校验）
# ---------------------------------------------------------------------------
class R5EnrollmentAdapter(BaseAdapter):
    dataset = 'r5_enrollments'

    def __init__(self):
        from smass_academic.models import AcademicTerm

        semesters = tuple(choice[0] for choice in AcademicTerm.SEMESTER_CHOICES)
        self.schema = DatasetSchema(
            code=self.dataset, version='1', title='选课导入（R5）',
            fields=(
                FieldSpec('year_code', '学年编码', required=True, max_length=16,
                          example='2024-2025'),
                FieldSpec('semester', '学期', required=True, dtype='enum',
                          choices=semesters, example=semesters[0]),
                FieldSpec('section_code', '教学班号', required=True, max_length=32,
                          example='CS101-01'),
                FieldSpec('login_name', '学生登录名', required=True, max_length=64,
                          example='DEMO-S0001',
                          help='必须已存在的学生账号登录名'),
            ),
            instructions=('教学班必须存在且状态为可选',
                          '容量已满时该行报 SECTION_FULL',
                          '同一学生对同一教学班重复选课将被跳过'),
            notes=('本导入只创建/恢复选课记录，不会替学生退课',),
        )

    def validate(self, rows, account, *, request=None):
        from smass_academic.models import AcademicTerm, AcademicYear, Enrollment, TeachingSection
        from r21_account.models import Account

        try:
            _check_import_permission(account)
        except Exception as exc:  # noqa: BLE001
            return [], _permission_error(exc)

        year_codes = {str(r.get('year_code') or '').strip() for r in rows}
        years = {y.code: y for y in AcademicYear.objects.filter(code__in=year_codes)}

        terms = {}
        for year_code, year in years.items():
            for term in AcademicTerm.objects.filter(year=year):
                terms[(year_code, term.semester)] = term

        section_codes = {str(r.get('section_code') or '').strip() for r in rows}
        sections = {}
        for term in terms.values():
            for sec in TeachingSection.objects.filter(term=term, code__in=section_codes):
                sections[(term.pk, sec.code)] = sec

        login_names = {str(r.get('login_name') or '').strip() for r in rows}
        login_names.discard('')
        accounts = {a.login_name: a for a in Account.objects.filter(login_name__in=login_names)}

        # 每个教学班当前已选人数（不含已退出）
        current_counts = {
            sec.pk: Enrollment.objects.filter(
                section=sec).exclude(status='dropped').count()
            for sec in sections.values()
        }
        reserved: dict[int, int] = {}

        validated, errors = [], []
        for row in rows:
            line = row.get('__row__', 0)
            year_code = str(row.get('year_code') or '').strip()
            semester = str(row.get('semester') or '').strip()
            section_code = str(row.get('section_code') or '').strip()
            login_name = str(row.get('login_name') or '').strip()

            row_errors = []
            term = terms.get((year_code, semester))
            if term is None:
                row_errors.append(('semester', 'UNKNOWN_TERM', '学年+学期不存在'))
                section = None
            else:
                section = sections.get((term.pk, section_code))
                if section is None:
                    row_errors.append(('section_code', 'UNKNOWN_SECTION', '教学班不存在'))

            account_obj = accounts.get(login_name)
            if not login_name:
                row_errors.append(('login_name', 'EMPTY_LOGIN', '登录名不能为空'))
            elif account_obj is None:
                row_errors.append(('login_name', 'UNKNOWN_ACCOUNT', '学生账号不存在'))

            if section is not None:
                from smass_academic.models import TeachingSection as _TS

                if section.status != _TS.STATUS_OPEN:
                    row_errors.append(('section_code', 'SECTION_CLOSED',
                                       '教学班当前不可选（状态非 open）'))

            # 容量校验（含文件内已占用名额）
            if section is not None and section.capacity:
                used = current_counts.get(section.pk, 0) + reserved.get(section.pk, 0)
                if used >= section.capacity:
                    row_errors.append(('section_code', 'SECTION_FULL', '教学班容量已满'))

            if row_errors:
                for column, ec, message in row_errors:
                    errors.append(_err(line, column, ec, message))
                continue

            existing = Enrollment.objects.filter(
                section=section, account=account_obj).first()
            if existing is not None and existing.status != 'dropped':
                plan = 'skip'
            elif existing is not None:
                plan = 'update'          # 曾退课，恢复
            else:
                plan = 'create'
                reserved[section.pk] = reserved.get(section.pk, 0) + 1

            item = dict(row)
            item.update({'__plan__': plan, '__section_pk__': section.pk,
                         '__account_pk__': account_obj.pk,
                         '__existing_pk__': existing.pk if existing else None})
            validated.append(item)
        return validated, errors

    def commit(self, validated, account, *, request=None):
        from django.db import transaction

        from smass_academic.models import Enrollment, EnrollmentHistory

        actor = _actor_id(account)
        stats = {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}
        with transaction.atomic():
            job = _create_job(self.dataset, len(validated), actor)
            for item in validated:
                plan = item['__plan__']
                if plan == 'skip':
                    stats['skipped'] += 1
                    continue
                if plan == 'create':
                    enrollment = Enrollment.objects.create(
                        section_id=item['__section_pk__'],
                        account_id=item['__account_pk__'],
                        status='enrolled',
                    )
                    EnrollmentHistory.objects.create(
                        enrollment=enrollment, old_status='', new_status='enrolled',
                        changed_by=actor)
                    stats['created'] += 1
                else:
                    enrollment = Enrollment.objects.filter(
                        pk=item['__existing_pk__']).first()
                    if enrollment is None:
                        stats['conflict'] += 1
                        continue
                    old_status = enrollment.status
                    enrollment.status = 'enrolled'
                    enrollment.save(update_fields=['status', 'changed_at'])
                    EnrollmentHistory.objects.create(
                        enrollment=enrollment, old_status=old_status,
                        new_status='enrolled', changed_by=actor)
                    stats['updated'] += 1
            _finish_job(job, stats, stats['created'], stats['updated'])
        return job, stats

    def describe_row(self, row, account):
        return {'row': row.get('__row__', 0),
                'section': row.get('section_code', ''),
                'login_name': row.get('login_name', ''),
                'plan': row.get('__plan__', '')}


BUILTIN_R5_ADAPTERS = (
    R5AcademicYearAdapter, R5TermAdapter, R5CourseAdapter,
    R5SectionAdapter, R5EnrollmentAdapter,
)


def register_all():
    """注册全部 R5 适配器（幂等）。"""
    for cls in BUILTIN_R5_ADAPTERS:
        register_adapter(cls())
    return len(BUILTIN_R5_ADAPTERS)
