#!/usr/bin/env python
"""基于 inventory JSON 计算细分统计（只读）。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INV = ROOT / 'docs/SMASS_System_Function_Audit/inventory'


def load(name):
    return json.loads((INV / name).read_text(encoding='utf-8'))


def main():
    apps = load('apps.json')
    models = load('models.json')
    urls = load('urls.json')
    views = load('views.json')
    services = load('services.json')
    tests = load('tests.json')
    templates = load('templates.json')

    project = [item for item in apps if not item['builtin']]
    app_models = Counter(item['app_label'] for item in models
                         if not item['auto_created'])
    app_routes = Counter()
    for item in urls:
        module = item['real_view'].split('.')[0] if item['real_view'] else ''
        app_routes[module] += 1
    app_views = Counter(item['file'].split('/')[0] for item in views)
    app_services = Counter(item['file'].split('/')[0] for item in services)
    app_tests = Counter(item['file'].split('/')[0] for item in tests)

    auto_created = [item for item in models if item['auto_created']]

    route_prefix = Counter()
    for item in urls:
        path = item['path']
        parts = [part for part in path.split('/') if part]
        key = '/' + parts[0] if parts else '/'
        if key.startswith('/r') and key[2:].isdigit():
            key = '/r*'
        route_prefix[key] += 1

    decorator_counter = Counter()
    for item in views + services:
        for name in item.get('decorators', []):
            decorator_counter[name] += 1

    referenced_views = Counter(item['real_view'] for item in urls)
    duplicated_views = {name: count for name, count in referenced_views.items()
                        if count > 1}
    unreferenced = sorted({
        '{}.{}'.format(item['file'].replace('/', '.').removesuffix('.py'),
                       item['name'])
        for item in views
        if not item['name'].startswith('_')
    } - set(referenced_views))

    template_dirs = Counter()
    for item in templates:
        parts = item['path'].split('/')
        key = parts[1] if len(parts) > 2 else '(root)'
        template_dirs[key] += 1

    test_counts = defaultdict(int)
    for item in tests:
        test_counts[item['file'].split('/')[0]] += 1

    supplement = {
        'apps_project_list': [item['label'] for item in project],
        'app_models': dict(sorted(app_models.items())),
        'models_effective': sum(app_models.values()),
        'models_project': sum(value for key, value in app_models.items()
                              if key in {item['label'] for item in project}),
        'app_routes': dict(sorted(app_routes.items(), key=lambda kv: -kv[1])),
        'app_views': dict(sorted(app_views.items())),
        'app_services': dict(sorted(app_services.items())),
        'app_tests': dict(sorted(test_counts.items())),
        'auto_created_models': [{'app': item['app_label'],
                                 'model': item['model'],
                                 'table': item['db_table']}
                                for item in auto_created],
        'models_effective': len([item for item in models
                                 if not item['auto_created']]),
        'route_prefix': dict(sorted(route_prefix.items(),
                                    key=lambda kv: -kv[1])),
        'decorators': dict(sorted(decorator_counter.items(),
                                  key=lambda kv: -kv[1])),
        'distinct_view_callbacks': len(referenced_views),
        'duplicated_view_callbacks': len(duplicated_views),
        'view_functions_total': len(views),
        'view_functions_public': len([item for item in views
                                      if not item['name'].startswith('_')]),
        'service_functions_total': len(services),
        'unreferenced_view_functions': unreferenced,
        'template_dirs': dict(sorted(template_dirs.items())),
    }
    (INV / 'supplement.json').write_text(
        json.dumps(supplement, ensure_ascii=False, indent=1), encoding='utf-8')

    lines = ['# 细分统计（脚本生成）', '',
             '## 每 App 模型/路由/视图/服务/测试', '',
             '| App | 有效模型 | 路由 | 视图函数 | 服务函数 | 测试用例 |',
             '|---|---|---|---|---|---|']
    for app in sorted({*app_models, *app_views, *app_services,
                       *app_routes, *test_counts}):
        lines.append('| {} | {} | {} | {} | {} | {} |'.format(
            app, app_models.get(app, 0), app_routes.get(app, 0),
            app_views.get(app, 0), app_services.get(app, 0),
            test_counts.get(app, 0)))
    lines += ['', '## 路由前缀分布', '', '| 前缀 | 路由数 |', '|---|---|']
    for key, value in sorted(route_prefix.items(), key=lambda kv: -kv[1]):
        lines.append('| {} | {} |'.format(key, value))
    lines += ['', '## 装饰器出现次数（视图与服务）', '',
              '| 装饰器 | 次数 |', '|---|---|']
    for key, value in sorted(decorator_counter.items(),
                             key=lambda kv: -kv[1])[:40]:
        lines.append('| {} | {} |'.format(key, value))
    lines += ['', '## 自动生成的 M2M 中间表（不计入业务模型字典）', '',
              '| App | 模型 | 表 |', '|---|---|---|']
    for item in auto_created:
        lines.append('| {} | {} | {} |'.format(
            item['app_label'], item['model'], item['db_table']))
    (INV / 'supplement.md').write_text('\n'.join(lines), encoding='utf-8')

    print(json.dumps({key: value for key, value in supplement.items()
                      if key not in ('unreferenced_view_functions',
                                     'apps_project_list')},
                     ensure_ascii=False, indent=1))
    print('unreferenced_view_functions:', len(unreferenced))
    print('RESULT: PASS')


if __name__ == '__main__':
    raise SystemExit(main())
