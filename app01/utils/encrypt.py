"""历史遗留 MD5 辅助函数。

⚠️ 重要：本模块**只用于校验历史数据**（legacy），不得用于写入新密码。

历史成因：早期 ``Admin`` / ``Student`` / ``Teacher`` 的 ``save()`` 无条件调用
``md5(SECRET_KEY + raw)``，导致同一明文在不同路径下被哈希 0~2 次。
新密码统一走 ``app01.services.accounts.set_password``（Django 官方哈希）。

``secret_key`` 参数用于校验当年写死在 ``settings.SECRET_KEY`` 中、现已泄漏的旧密钥
生成的哈希，因此必须可显式传入，而不能依赖当前 ``settings.SECRET_KEY``。
"""
import hashlib

from django.conf import settings


def md5(data_string, secret_key=None):
    """计算 ``md5(secret_key + data_string)``。

    :param data_string: 待哈希的明文字符串
    :param secret_key: 历史密钥；为 ``None`` 时取当前 ``settings.SECRET_KEY``
    """
    key = secret_key if secret_key is not None else settings.SECRET_KEY
    obj = hashlib.md5(key.encode('utf-8'))
    obj.update(data_string.encode('utf-8'))
    return obj.hexdigest()
