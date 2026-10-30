"""S19 服务层：对比度计算与模板可访问性静态审计。

规则（error 级，会阻断新模板）：
- ``<html>`` 缺少 ``lang``；
- ``<img>`` 缺少 ``alt``；
- ``<input>/<select>/<textarea>`` 缺少可关联的 ``label``（``for``/包裹）或 ``aria-label``；
- ``<a>`` 无可见文本且无 ``aria-label``；
- ``tabindex`` 为正数（打乱自然 Tab 顺序）。

warning 级：
- 表单按钮无 ``type``；
- 表格缺少 ``<th>``；
- 使用 ``outline: none`` 且无替代焦点样式。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

#: 新模板目录（必须零 error）
NEW_TEMPLATE_DIRS = (
    'account', 'r12', 'r13', 'r14', 'r15', 'r16', 'r17', 'r18', 'r19', 'r20',
    's09', 's10', 's11', 's13', 's14', 's15', 's16',
)

#: 输入类控件（需要可访问名称）
INPUT_TYPES_NEEDING_LABEL = {
    'text', 'password', 'email', 'number', 'tel', 'url', 'search', 'date',
    'datetime-local', 'month', 'week', 'time', 'checkbox', 'radio', 'file',
}


class Node:
    def __init__(self, tag, attrs, text=''):
        self.tag = tag
        self.attrs = dict(attrs)
        self.text = text


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_lang = None
        self.nodes = []
        self.label_fors = set()
        self._open = []
        self.has_th = False
        self.has_table = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.html_lang = attrs.get('lang')
        if tag == 'label' and attrs.get('for'):
            self.label_fors.add(attrs['for'])
        if tag == 'th':
            self.has_th = True
        if tag == 'table':
            self.has_table = True
        self.nodes.append(Node(tag, attrs))
        self._open.append({'tag': tag, 'index': len(self.nodes) - 1, 'text': []})

    def handle_endtag(self, tag):
        if not self._open or self._open[-1]['tag'] != tag:
            return
        entry = self._open.pop()
        node = self.nodes[entry['index']]
        node.text = ''.join(entry['text'])
        if self._open:
            # 子节点文本向父节点冒泡，保证 <a><span>x</span></a> 也有名称
            self._open[-1]['text'].append(node.text)

    def handle_data(self, data):
        if self._open:
            self._open[-1]['text'].append(data)


def _iter_visible_text(html):
    text = re.sub(r'<script.*?</script>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<style.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def audit_html(html, name='<inline>', new_template=True):
    """返回问题列表：[{level, rule, detail}]。"""
    issues = []
    collector = _Collector()
    try:
        collector.feed(html)
    except Exception:  # noqa: BLE001 - 解析失败不阻断，记为 warning
        issues.append({'level': 'warning', 'rule': 'parse-error',
                       'detail': 'HTML 解析失败'})
        return issues

    if '<html' in html.lower() and not collector.html_lang:
        issues.append({'level': 'error', 'rule': 'html-lang',
                       'detail': '<html> 缺少 lang 属性'})

    labelled_ids = collector.label_fors
    aria_labelled = False
    for node in collector.nodes:
        if node.attrs.get('aria-label') or node.attrs.get('aria-labelledby'):
            aria_labelled = True
        if node.tag == 'img' and 'alt' not in node.attrs:
            issues.append({'level': 'error', 'rule': 'img-alt',
                           'detail': '<img> 缺少 alt'})
        if node.tag in ('input', 'select', 'textarea'):
            input_type = (node.attrs.get('type') or 'text').lower()
            node_id = node.attrs.get('id', '')
            has_label = bool(
                (node_id and node_id in labelled_ids)
                or node.attrs.get('aria-label')
                or node.attrs.get('aria-labelledby'))
            if node.tag == 'input' and input_type in ('hidden', 'submit', 'button', 'reset'):
                has_label = True
            elif node.tag == 'input' and input_type not in INPUT_TYPES_NEEDING_LABEL:
                has_label = True
            if not has_label:
                issues.append({'level': 'error', 'rule': 'control-label',
                               'detail': '{} 缺少 label/aria-label'.format(node.tag)})
        if node.tag == 'a':
            text = (node.text or '').strip()
            if not text and not node.attrs.get('aria-label'):
                issues.append({'level': 'error', 'rule': 'link-name',
                               'detail': '<a> 无可见文本且无 aria-label'})
        tabindex = node.attrs.get('tabindex')
        if tabindex is not None:
            try:
                if int(tabindex) > 0:
                    issues.append({'level': 'warning', 'rule': 'tabindex-positive',
                                   'detail': 'tabindex={} 打乱 Tab 顺序'.format(tabindex)})
            except ValueError:
                pass

    if collector.has_table and not collector.has_th:
        issues.append({'level': 'warning', 'rule': 'table-header',
                       'detail': '<table> 缺少 <th>'})
    if re.search(r'outline\s*:\s*none', html, re.I) and not re.search(
            r'focus-visible|:focus', html, re.I):
        issues.append({'level': 'warning', 'rule': 'focus-outline',
                       'detail': '清除了 outline 且未提供替代焦点样式'})
    if re.search(r'<button(?![^>]*type=)', html, re.I):
        issues.append({'level': 'warning', 'rule': 'button-type',
                       'detail': '<button> 未声明 type'})
    return issues


# ---------------------------------------------------------------------------
# 对比度（WCAG 2.1）
# ---------------------------------------------------------------------------
def _hex_to_rgb(value):
    text = str(value).strip().lstrip('#')
    if len(text) == 3:
        text = ''.join(ch * 2 for ch in text)
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))


def relative_luminance(rgb):
    def channel(value):
        ratio = value / 255.0
        return ratio / 12.92 if ratio <= 0.03928 else ((ratio + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(item) for item in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(fg, bg):
    """返回对比度（1.0 ~ 21.0）。"""
    light = relative_luminance(_hex_to_rgb(fg))
    dark = relative_luminance(_hex_to_rgb(bg))
    if light < dark:
        light, dark = dark, light
    return round((light + 0.05) / (dark + 0.05), 2)


def wcag_level(ratio, large_text=False):
    """返回 'AAA' / 'AA' / 'FAIL'。"""
    if large_text:
        if ratio >= 4.5:
            return 'AAA'
        if ratio >= 3.0:
            return 'AA'
        return 'FAIL'
    if ratio >= 7.0:
        return 'AAA'
    if ratio >= 4.5:
        return 'AA'
    return 'FAIL'


# ---------------------------------------------------------------------------
# 模板扫描
# ---------------------------------------------------------------------------
def is_new_template(relative_path):
    parts = Path(relative_path).parts
    return bool(parts) and parts[0] in NEW_TEMPLATE_DIRS


def audit_dir(root):
    root = Path(root)
    results = []
    for path in sorted(root.rglob('*.html')):
        relative = path.relative_to(root).as_posix()
        try:
            html = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        results.append({
            'path': relative,
            'new_template': is_new_template(relative),
            'issues': audit_html(html, relative),
            'text_length': len(_iter_visible_text(html)),
        })
    return results


def summarize(results):
    new_errors = sum(1 for item in results if item['new_template']
                     for issue in item['issues'] if issue['level'] == 'error')
    new_warnings = sum(1 for item in results if item['new_template']
                       for issue in item['issues'] if issue['level'] == 'warning')
    legacy_errors = sum(1 for item in results if not item['new_template']
                        for issue in item['issues'] if issue['level'] == 'error')
    return {
        'templates': len(results),
        'new_templates': sum(1 for item in results if item['new_template']),
        'new_errors': new_errors,
        'new_warnings': new_warnings,
        'legacy_errors': legacy_errors,
    }


#: 设计系统关键配色的对比度基线（用于回归）
COLOR_PAIRS = (
    ('#1f2430', '#f5f7fb', False),
    ('#667085', '#ffffff', False),
    ('#2456a6', '#ffffff', False),
    ('#0f7b4f', '#e7f6ef', False),
    ('#b42318', '#fdecea', False),
    ('#8a5a00', '#fff4d6', False),
)
