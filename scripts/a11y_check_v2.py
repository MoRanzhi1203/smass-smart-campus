#!/usr/bin/env python
"""F06 无障碍检查：可访问名称、表单标签、标题层级、键盘焦点、对比度。

    python scripts/a11y_check_v2.py --base http://127.0.0.1:8050

不依赖外部 axe CDN；检查项与 WCAG 2.1 A/AA 的关键可自动化部分对应。
输出：.local/evidence/v2/a11y/a11y_check_v2.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.local/evidence/v2/a11y'

PAGES = {
    'student': ['/student/', '/student/attendance/', '/student/courses/'],
    'teacher': ['/teacher/', '/teacher/approvals/', '/teacher/attendance/'],
    'admin': ['/admin/', '/admin/users/', '/admin/organizations/',
              '/admin/finance/', '/admin/data-exchange/'],
}
ACCOUNTS = {'student': 'dev_student', 'teacher': 'dev_teacher',
            'admin': 'dev_admin'}

A11Y_JS = r"""
() => {
  const text = (el) => (el.innerText || el.textContent || '').trim();
  const hasName = (el) => Boolean(
      (el.getAttribute('aria-label') || '').trim()
      || (el.getAttribute('title') || '').trim()
      || text(el)
      || (el.getAttribute('value') || '').trim());
  const buttons = Array.from(document.querySelectorAll('button, .ws-btn'))
      .filter((el) => el.offsetParent !== null);
  const inputs = Array.from(document.querySelectorAll('input, select, textarea'))
      .filter((el) => el.offsetParent !== null)
      .filter((el) => !['hidden', 'submit', 'button', 'checkbox'].includes(el.type));
  const labelled = (el) => {
    if ((el.getAttribute('aria-label') || '').trim()) return true;
    if (el.getAttribute('aria-labelledby')) return true;
    const id = el.getAttribute('id');
    if (id && document.querySelector('label[for="' + id + '"]')) return true;
    return Boolean(el.closest('label'));
  };
  const luminance = (rgb) => {
    const parts = rgb.match(/\d+/g) || [0, 0, 0];
    const [r, g, b] = parts.slice(0, 3).map((value) => {
      const c = Number(value) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (fg, bg) => {
    const a = luminance(fg), b = luminance(bg);
    const [light, dark] = a > b ? [a, b] : [b, a];
    return (light + 0.05) / (dark + 0.05);
  };
  const primary = document.querySelector('.ws-btn.is-primary');
  let primaryContrast = null;
  if (primary) {
    const style = getComputedStyle(primary);
    primaryContrast = Number(contrast(style.color, style.backgroundColor).toFixed(2));
  }
  return {
    title: document.title,
    h1: document.querySelectorAll('h1').length,
    skipLink: Boolean(document.querySelector('.ws-skip')),
    lang: document.documentElement.lang,
    buttons: buttons.length,
    buttonsWithoutName: buttons.filter((el) => !hasName(el)).map(
        (el) => el.className || el.tagName),
    inputs: inputs.length,
    inputsWithoutLabel: inputs.filter((el) => !labelled(el)).map(
        (el) => (el.getAttribute('name') || el.getAttribute('id') || el.tagName)),
    imagesWithoutAlt: Array.from(document.images)
        .filter((img) => !img.hasAttribute('alt')).length,
    linksWithoutText: Array.from(document.querySelectorAll('a'))
        .filter((a) => a.offsetParent !== null && !text(a)
                       && !(a.getAttribute('aria-label') || '').trim()).length,
    primaryContrast,
    summary: document.querySelectorAll('summary').length,
    tables: document.querySelectorAll('table').length,
  };
}
"""


def password():
    from smass.env_loader import load_env

    load_env(ROOT / '.env')
    return (os.environ.get('PRODUCT_DEV_PASSWORD')
            or os.environ.get('INTEGRATED_DEV_PASSWORD')
            or 'Smass#2026')


def focus_walk(page, steps=25):
    focuses = []
    for _ in range(steps):
        page.keyboard.press('Tab')
        info = page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const style = getComputedStyle(el);
                return {
                    tag: el.tagName,
                    name: (el.getAttribute('aria-label') || el.innerText
                           || el.getAttribute('name') || '').trim().slice(0, 40),
                    outline: style.outlineStyle + ' ' + style.outlineWidth,
                };
            }""")
        if info:
            focuses.append(info)
    return focuses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8050')
    parser.add_argument('--json', dest='json_path',
                        default=str(OUT / 'a11y_check_v2.json'))
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    secret = password()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role, urls in PAGES.items():
            context = browser.new_context(viewport={'width': 1366, 'height': 768})
            page = context.new_page()
            try:
                page.goto(args.base + '/login/', wait_until='domcontentloaded')
                page.fill('input[name="login_name"]', ACCOUNTS[role])
                page.fill('input[name="password"]', secret)
                page.click('button[type="submit"]')
                page.wait_for_load_state('networkidle')
                for url in urls:
                    page.goto(args.base + url, wait_until='networkidle')
                    data = page.evaluate(A11Y_JS)
                    data.update({'role': role, 'url': url})
                    if url in ('/student/', '/admin/users/'):
                        data['focus'] = focus_walk(page)
                    results.append(data)
            finally:
                context.close()
        browser.close()

    issues = []
    for item in results:
        if item['buttonsWithoutName']:
            issues.append({'page': item['url'], 'kind': 'button_name',
                           'detail': item['buttonsWithoutName'][:5]})
        if item['inputsWithoutLabel']:
            issues.append({'page': item['url'], 'kind': 'input_label',
                           'detail': item['inputsWithoutLabel'][:5]})
        if item['imagesWithoutAlt']:
            issues.append({'page': item['url'], 'kind': 'image_alt',
                           'detail': item['imagesWithoutAlt']})
        if item['linksWithoutText']:
            issues.append({'page': item['url'], 'kind': 'link_text',
                           'detail': item['linksWithoutText']})
        if item['h1'] != 1:
            issues.append({'page': item['url'], 'kind': 'h1_count',
                           'detail': item['h1']})
        if not item['skipLink']:
            issues.append({'page': item['url'], 'kind': 'skip_link',
                           'detail': None})
        if item['lang'] != 'zh-CN':
            issues.append({'page': item['url'], 'kind': 'lang',
                           'detail': item['lang']})
        if item['primaryContrast'] is not None and item['primaryContrast'] < 4.5:
            issues.append({'page': item['url'], 'kind': 'contrast',
                           'detail': item['primaryContrast']})
        for focus in item.get('focus', []):
            if focus['outline'].startswith('none'):
                issues.append({'page': item['url'], 'kind': 'focus_outline',
                               'detail': focus['name']})
                break

    report = {'pages': len(results), 'issues': issues,
              'issue_count': len(issues), 'results': results,
              'ok': not issues}
    path = Path(args.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    print(json.dumps({'pages': len(results), 'issues': len(issues),
                      'by_kind': sorted({item['kind'] for item in issues}),
                      'ok': report['ok']}, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
