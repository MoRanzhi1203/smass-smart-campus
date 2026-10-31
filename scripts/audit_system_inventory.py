#!/usr/bin/env python
"""只读全系统清查：Django App / Model / URL / View / Service / 模板 / 测试 / 角色菜单。

    python scripts/audit_system_inventory.py --out docs/SMASS_System_Function_Audit/inventory

不连接业务数据库、不写入任何业务表；只读取代码与 Django 元数据。
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = 'smass.settings_product'

#: Django/第三方内置 app 与项目业务 app 分开统计
BUILTIN_PREFIXES = ('django.', 'rest_framework', 'corsheaders', 'debug_toolbar')

SKIP_DIRS = {'.git', '.local', 'staticfiles', '__pycache__', 'node_modules',
             'media', 'private_uploads', 'logs'}


def setup():
    os.environ['DJANGO_SETTINGS_MODULE'] = SETTINGS
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()


def field_repr(field):
    from django.db.models import ForeignKey, ManyToManyField, OneToOneField

    item = {
        'name': field.name,
        'type': field.get_internal_type(),
        'verbose_name': str(getattr(field, 'verbose_name', '') or ''),
        'null': bool(getattr(field, 'null', False)),
        'blank': bool(getattr(field, 'blank', False)),
        'unique': bool(getattr(field, 'unique', False)),
        'db_index': bool(getattr(field, 'db_index', False)),
        'primary_key': bool(getattr(field, 'primary_key', False)),
        'max_length': getattr(field, 'max_length', None),
        'default': None if field.has_default() is False else short_repr(
            field.get_default()),
    }
    choices = getattr(field, 'choices', None)
    if choices:
        item['choices'] = [{'value': str(value), 'label': str(label)}
                           for value, label in choices]
    if isinstance(field, (ForeignKey, OneToOneField, ManyToManyField)):
        item['related_model'] = '{}.{}'.format(
            field.related_model._meta.app_label,
            field.related_model._meta.object_name)
        item['related_name'] = getattr(field, 'remote_field', None) and \
            getattr(field.remote_field, 'related_name', None)
        if isinstance(field, (ForeignKey, OneToOneField)):
            item['on_delete'] = getattr(field.remote_field, 'on_delete', None)
            item['on_delete'] = getattr(item['on_delete'], '__name__', str(
                item['on_delete']))
    return item


def short_repr(value):
    text = repr(value)
    if len(text) > 120:
        return text[:117] + '...'
    return text


def collect_apps():
    from django.apps import apps

    items = []
    for config in apps.get_app_configs():
        builtin = config.name.startswith(BUILTIN_PREFIXES)
        try:
            relative = str(Path(config.path).relative_to(ROOT))
        except ValueError:
            relative = str(config.path)
        items.append({
            'label': config.label,
            'name': config.name,
            'verbose_name': str(config.verbose_name),
            'path': relative,
            'builtin': builtin,
        })
    return items


def collect_models():
    from django.apps import apps

    items = []
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        constraints = []
        for constraint in meta.constraints:
            constraints.append({
                'name': constraint.name,
                'type': type(constraint).__name__,
                'fields': list(getattr(constraint, 'fields', []) or []),
                'condition': short_repr(getattr(constraint, 'condition', None)),
            })
        indexes = [{'name': item.name,
                    'fields': list(item.fields or []),
                    'condition': short_repr(getattr(item, 'condition', None))}
                   for item in meta.indexes]
        items.append({
            'app_label': meta.app_label,
            'model': meta.object_name,
            'db_table': meta.db_table,
            'verbose_name': str(meta.verbose_name),
            'verbose_name_plural': str(meta.verbose_name_plural),
            'managed': meta.managed,
            'auto_created': meta.auto_created is not False,
            'proxy': meta.proxy,
            'ordering': list(meta.ordering or []),
            'pk_field': meta.pk.name,
            'fields': [field_repr(field) for field in meta.get_fields()
                       if getattr(field, 'concrete', False)],
            'relations': [field_repr(field) for field in meta.get_fields()
                          if getattr(field, 'is_relation', False)
                          and not getattr(field, 'auto_created', False)],
            'constraints': constraints,
            'indexes': indexes,
            'unique_together': [list(item) for item in (meta.unique_together or [])],
        })
    return items


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------
def collect_urls():
    from django.urls import get_resolver

    resolver = get_resolver()
    rows = []

    def walk(patterns, prefix='', namespace=''):
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            if hasattr(pattern, 'url_patterns'):
                ns = namespace
                if getattr(pattern, 'namespace', None):
                    ns = namespace + pattern.namespace + ':'
                walk(pattern.url_patterns, route, ns)
                continue
            callback = pattern.callback
            module = getattr(callback, '__module__', '')
            qualname = getattr(callback, '__qualname__', repr(callback))
            # 解开 functools.wraps 包装，定位真正的视图函数
            target = callback
            seen = 0
            while hasattr(target, '__wrapped__') and seen < 8:
                target = target.__wrapped__
                seen += 1
            rows.append({
                'path': '/' + route if not route.startswith('/') else route,
                'name': pattern.name or '',
                'namespace': namespace.rstrip(':'),
                'view_module': module,
                'view_qualname': qualname,
                'real_view': '{}.{}'.format(
                    getattr(target, '__module__', module),
                    getattr(target, '__qualname__', qualname)),
                'include': '',
            })

    walk(resolver.url_patterns)
    return rows


# ---------------------------------------------------------------------------
# View / Service 源码扫描
# ---------------------------------------------------------------------------
def iter_py_files():
    for path in ROOT.rglob('*.py'):
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if 'migrations' in relative.parts:
            continue
        yield path


def decorator_names(node):
    names = []
    for decorator in node.decorator_list:
        target = decorator
        if isinstance(target, ast.Call):
            target = target.func
        parts = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        names.append('.'.join(reversed(parts)) if parts else ast.dump(target))
    return names


def scan_defs(path):
    """返回模块中顶层函数与类方法（含装饰器与 docstring 首行）。"""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return []
    results = []

    def visit(node, in_class=''):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ''
            results.append({
                'name': node.name,
                'class': in_class,
                'lineno': node.lineno,
                'decorators': decorator_names(node),
                'args': [arg.arg for arg in node.args.args],
                'doc': doc.splitlines()[0].strip() if doc else '',
            })
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                visit(child, node.name)

    for item in tree.body:
        visit(item)
    return results


def collect_views_and_services():
    views, services, tests = [], [], []
    for path in iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        name = path.name
        is_view = (name in ('views.py', 'ui_views.py')
                   or '/views/' in rel or name.endswith('_views.py'))
        is_service = (name == 'services.py' or '/services/' in rel
                      or name.startswith('services_'))
        is_test = (name.startswith('test_') or name == 'tests.py'
                   or '/tests/' in rel) and '/migrations/' not in rel
        if not (is_view or is_service or is_test):
            continue
        for node in scan_defs(path):
            node['file'] = rel
            if is_test:
                if node['name'].startswith('test_'):
                    tests.append(node)
            elif is_view:
                views.append(node)
            elif is_service and not node['name'].startswith('_'):
                services.append(node)
    return views, services, tests


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------
def template_meta(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    extends = re.search(r'{%\s*extends\s+["\']([^"\']+)["\']', text)
    blocks = re.findall(r'{%\s*block\s+(\w+)', text)
    forms = len(re.findall(r'<form\b', text))
    tables = len(re.findall(r'<table\b', text))
    return {
        'path': path.relative_to(ROOT).as_posix(),
        'size': path.stat().st_size,
        'extends': extends.group(1) if extends else '',
        'blocks': sorted(set(blocks)),
        'forms': forms,
        'tables': tables,
        'lines': text.count('\n') + 1,
    }


def collect_templates():
    items = []
    for base in ('templates', 'smass_workspace/templates'):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob('*.html'):
            relative = path.relative_to(ROOT)
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            items.append(template_meta(path))
    return items


# ---------------------------------------------------------------------------
# 角色、菜单、权限
# ---------------------------------------------------------------------------
def collect_roles():
    from r21_account import authorization as authz
    from r21_account.models import RoleCode, PersonType

    from smass_workspace import navigation

    kinds = []
    for kind in ('student', 'teacher', 'admin'):
        sections = []
        for section in navigation.sections_for(kind):
            sections.append({
                'label': section.label,
                'items': [{'label': item.label, 'url_name': item.url_name,
                           'href': item.href, 'icon': item.icon,
                           'system_admin_only': item.system_admin_only}
                          for item in section.items],
            })
        kinds.append({'kind': kind, 'sections': sections})

    from r21_account.authorization import ACTION_PERMISSIONS, RESOURCES

    resources = []
    for code, spec in RESOURCES.items():
        resources.append({
            'code': code,
            'model': spec.model,
            'scope': getattr(spec, 'scope', ''),
            'fields': sorted(getattr(spec, 'fields', {}) or {}),
        })
    return {
        'person_types': [{'value': value, 'label': str(label)}
                         for value, label in PersonType.choices],
        'role_codes': [{'value': value, 'label': str(label)}
                       for value, label in RoleCode.choices],
        'actions': sorted(ACTION_PERMISSIONS),
        'action_count': len(ACTION_PERMISSIONS),
        'resources': resources,
        'workspaces': kinds,
    }


def count_migrations():
    total = 0
    for app in ('app01', 'r21_account', 'r22_account', 'smass_organization',
                'smass_academic', 'smass_scheduling', 'smass_enrollment',
                'smass_attendance', 'smass_activities', 'smass_clubs',
                'smass_facilities', 'smass_forum', 'smass_finance',
                'smass_party', 'smass_portal', 'smass_workflow',
                'smass_analytics', 'smass_operations', 'smass_api',
                'smass_api_security', 'smass_audit', 'smass_mfa',
                'smass_stepup', 'smass_policy', 'smass_privacy',
                'smass_uploads', 'smass_security_tests', 'smass_a11y',
                'smass_workspace'):
        directory = ROOT / app / 'migrations'
        if directory.exists():
            total += len([item for item in directory.glob('*.py')
                          if item.name != '__init__.py'])
    return total


def main():
    parser = argparse.ArgumentParser(description='SMASS 只读清查')
    parser.add_argument('--out', default='docs/SMASS_System_Function_Audit/inventory')
    args = parser.parse_args()

    setup()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    apps = collect_apps()
    models = collect_models()
    urls = collect_urls()
    views, services, tests = collect_views_and_services()
    templates = collect_templates()
    roles = collect_roles()

    project_apps = [item for item in apps if not item['builtin']]
    builtin_apps = [item for item in apps if item['builtin']]

    def dump(name, data):
        (out / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')

    dump('apps.json', apps)
    dump('models.json', models)
    dump('urls.json', urls)
    dump('views.json', views)
    dump('services.json', services)
    dump('tests.json', tests)
    dump('templates.json', templates)
    dump('roles.json', roles)

    with (out / 'urls.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(urls[0].keys()))
        writer.writeheader()
        writer.writerows(urls)

    with (out / 'models.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['app', 'model', 'db_table', 'field', 'type',
                         'null', 'blank', 'unique', 'choices', 'relation'])
        for model in models:
            for field in model['fields']:
                writer.writerow([
                    model['app_label'], model['model'], model['db_table'],
                    field['name'], field['type'], field['null'],
                    field['blank'], field['unique'],
                    '|'.join('{}={}'.format(item['value'], item['label'])
                             for item in field.get('choices', [])),
                    field.get('related_model', ''),
                ])

    project_labels = {app['label'] for app in project_apps}
    effective = [item for item in models if not item['auto_created']]
    summary = {
        'head': subprocess_head(),
        'settings': SETTINGS,
        'python': sys.version.split()[0],
        'django': __import__('django').get_version(),
        'apps_total': len(apps),
        'apps_project': len(project_apps),
        'apps_builtin': len(builtin_apps),
        'models_total': len(models),
        'models_auto_created': len(models) - len(effective),
        'models_effective': len(effective),
        'models_project': len([item for item in effective
                               if item['app_label'] in project_labels]),
        'models_builtin': len([item for item in effective
                               if item['app_label'] not in project_labels]),
        'tables_unique': len({item['db_table'] for item in models}),
        'urls_total': len(urls),
        'urls_named': len([item for item in urls if item['name']]),
        'views_functions': len(views),
        'services_functions': len(services),
        'templates': len(templates),
        'templates_workspace': len([item for item in templates
                                    if item['path'].startswith(
                                        'smass_workspace/')]),
        'tests': len(tests),
        'role_codes': len(roles['role_codes']),
        'person_types': len(roles['person_types']),
        'authz_actions': roles['action_count'],
        'authz_resources': len(roles['resources']),
        'nav_items': sum(len(section['items'])
                         for kind in roles['workspaces']
                         for section in kind['sections']),
        'migrations': count_migrations(),
        'project_app_labels': [item['label'] for item in project_apps],
    }
    dump('summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('RESULT: PASS')


def subprocess_head():
    import subprocess

    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                          capture_output=True, text=True,
                          encoding='utf-8').stdout.strip()


if __name__ == '__main__':
    raise SystemExit(main())
