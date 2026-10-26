from django import template

register = template.Library()


@register.filter
def encrypt_range(value, range_str):
    """
    手机|身份证加密
    :param value: 输入待加密字符串
    :param range_str: 输入字符串'x:y', 作为加密的索引范围
    :return:
    """
    start, end = map(int, range_str.split(':'))
    encrypted = list(value)
    for i in range(start, end + 1):
        encrypted[i] = '*'
    return ''.join(encrypted)

