"""组织生成：学院 → 专业 → 年级 → 行政班（稳定编码，可重复执行）。"""
from __future__ import annotations

from smass_organization.models import (
    UNIT_TYPE_CLASS,
    UNIT_TYPE_COLLEGE,
    UNIT_TYPE_GRADE,
    UNIT_TYPE_MAJOR,
    OrganizationUnit,
)

from . import config as sim_config

PREFIX = 'SIM'


def code(*parts):
    return '-'.join([PREFIX] + [str(part) for part in parts])


def ensure_unit(unit_code, name, unit_type, parent=None):
    unit, _created = OrganizationUnit.objects.update_or_create(
        code=unit_code,
        defaults={'name': name, 'unit_type': unit_type, 'parent': parent,
                  'status': 'active'})
    return unit


def generate(config, ctx, *, dry_run=False):
    """返回 {'colleges': [...], 'majors': [...], 'grades': [...], 'classes': [...]}。

    ``dry_run`` 时只按配置计算数量，不写库。
    """
    if dry_run:
        return {'colleges': [], 'majors': [], 'grades': [], 'classes': [],
                'dry_run': True}
    colleges = []
    for index in range(config['colleges']):
        name = sim_config.COLLEGE_NAMES[index % len(sim_config.COLLEGE_NAMES)]
        college = ensure_unit(
            code('COL', '{:02d}'.format(index + 1)),
            name, UNIT_TYPE_COLLEGE)
        colleges.append(college)
        ctx.remember('organization.OrganizationUnit', college.pk)

    major_names = list(sim_config.MAJOR_NAMES)
    majors = []
    major_cursor = 0
    base, extra = divmod(config['majors'], config['colleges'])
    for college_index, college in enumerate(colleges):
        count = base + (1 if college_index < extra else 0)
        for order in range(count):
            major_name = major_names[major_cursor % len(major_names)]
            major_cursor += 1
            major = ensure_unit(
                code('MAJ', '{:02d}'.format(college_index + 1),
                     '{:02d}'.format(order + 1)),
                major_name, UNIT_TYPE_MAJOR, college)
            majors.append(major)
            ctx.remember('organization.OrganizationUnit', major.pk)

    years = sim_config.grade_labels(config)
    grades = []
    for college_index, college in enumerate(colleges):
        for year in years:
            grade = ensure_unit(
                code('GRD', '{:02d}'.format(college_index + 1), year),
                '{}级'.format(year), UNIT_TYPE_GRADE, college)
            grades.append(grade)
            ctx.remember('organization.OrganizationUnit', grade.pk)

    classes = []
    for major in majors:
        for year in years:
            for order in range(config['classes_per_major_grade']):
                class_unit = ensure_unit(
                    code('CLS', major.code.split('-')[-2] + major.code.split('-')[-1],
                         year, '{:02d}'.format(order + 1)),
                    '{}{}级{}班'.format(major.name, year, order + 1),
                    UNIT_TYPE_CLASS, major)
                classes.append(class_unit)
                ctx.remember('organization.OrganizationUnit', class_unit.pk)

    ctx.stage_done('org', {
        'colleges': len(colleges), 'majors': len(majors),
        'grades': len(grades), 'classes': len(classes),
    })
    return {'colleges': colleges, 'majors': majors, 'grades': grades,
            'classes': classes}