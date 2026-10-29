"""U0：路由与页面盘点（自动枚举，不靠推断）。

输出 JSON：每个 URL 的 path / name / view / 是否有模板 / 是否 API。

用法：
    conda run -n smass python scripts/r10_ui_inventory.py
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_r10')

import django  # noqa: E402

django.setup()

from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402


def walk(patterns, prefix=''):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from walk(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield {
                'path': '/' + (prefix + str(entry.pattern)).lstrip('/'),
                'name': entry.name or '',
                'view': getattr(entry.callback, '__name__', str(entry.callback)),
                'module': getattr(entry.callback, '__module__', ''),
            }


def main():
    resolver = get_resolver()
    rows = list(walk(resolver.url_patterns))

    # 去重（多个模块重复挂载同一 login 路由）
    seen = set()
    unique = []
    for row in rows:
        key = (row['path'], row['name'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    for row in unique:
        row['is_api'] = row['path'].startswith('/api/')
        row['is_page'] = not row['is_api'] and not row['path'].endswith('.json')

    pages = [r for r in unique if r['is_page']]
    apis = [r for r in unique if r['is_api']]

    print(json.dumps({
        'total': len(unique),
        'pages': len(pages),
        'apis': len(apis),
        'routes': unique,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
