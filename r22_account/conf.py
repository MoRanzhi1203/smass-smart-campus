"""R2.2 特性开关（只在 ``smass.settings_r22`` 下有效）。

正式 ``smass.settings`` 不加载本 app，因此这些开关**默认等于关闭**，
不会影响现有系统行为。
"""
from django.conf import settings

#: 身份模式：off（不解析，全匿名） / account（只认 Account） / dual（双读+冲突拒绝）
IDENTITY_MODE_OFF = 'off'
IDENTITY_MODE_ACCOUNT = 'account'
IDENTITY_MODE_DUAL = 'dual'

VALID_MODES = (IDENTITY_MODE_OFF, IDENTITY_MODE_ACCOUNT, IDENTITY_MODE_DUAL)


def flags():
    raw = getattr(settings, 'R22_FLAGS', {}) or {}
    return {
        'identity_mode': raw.get('identity_mode', IDENTITY_MODE_DUAL),
        'route_policy_enabled': bool(raw.get('route_policy_enabled', True)),
        'audit_enabled': bool(raw.get('audit_enabled', True)),
        'dry_run': bool(raw.get('dry_run', False)),
    }


def identity_mode():
    mode = flags()['identity_mode']
    return mode if mode in VALID_MODES else IDENTITY_MODE_OFF


def enabled():
    return identity_mode() != IDENTITY_MODE_OFF
