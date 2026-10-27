"""模板过滤器：脱敏与打码。

安全原则（对应 R1.5-B.5）：对学生侧展示的手机号等个人联系信息，默认做最小披露，
而不是依赖"业务上应该不会外泄"。确需完整值时，应由具备权限的管理端查看。
"""
from django import template

register = template.Library()


@register.filter
def encrypt_range(value, range_str):
    """按索引区间把字符替换成 ``*``。

    :param value: 待处理字符串（``None`` / 空值原样返回空字符串，避免模板报错）
    :param range_str: ``'x:y'`` 形式的闭区间
    """
    if value is None or value == '':
        return ''

    text = str(value)
    if not text:
        return ''

    try:
        start, end = map(int, range_str.split(':'))
    except (ValueError, AttributeError):
        return text

    chars = list(text)
    last = len(chars) - 1
    end = min(end, last)

    for i in range(max(start, 0), end + 1):
        chars[i] = '*'

    return ''.join(chars)


@register.filter
def mask_phone(value):
    """手机号默认脱敏：保留前 3 位与后 4 位。

    13800001234 -> 138****1234
    """
    if value is None or value == '':
        return ''

    text = str(value).strip()
    if len(text) <= 7:
        return '*' * len(text)

    return '{}{}{}'.format(text[:3], '*' * (len(text) - 7), text[-4:])


@register.filter
def mask_id_card(value):
    """身份证号默认脱敏：保留前 6 位与后 4 位。"""
    if value is None or value == '':
        return ''

    text = str(value).strip()
    if len(text) <= 10:
        return '*' * len(text)

    return '{}{}{}'.format(text[:6], '*' * (len(text) - 10), text[-4:])
