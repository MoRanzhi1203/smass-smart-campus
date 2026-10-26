"""账户、密码与会话相关服务。

设计约束（对应修复计划 R1-A）：

1. **唯一写入路径**：所有密码写入必须经过本模块；模型的 ``save()`` 不再参与哈希。
2. **官方哈希**：使用 Django ``make_password`` / ``check_password``（PBKDF2-SHA256）。
3. **旧数据兼容**：历史 32 位 MD5 仅在**校验**时兼容，命中后立即升级为官方哈希；
   不做批量重写、不导出哈希。
4. **不记录敏感值**：明文密码、哈希、完整身份证号绝不进入日志或 JSON 响应。
5. **登录限速**：基于 Session 的失败计数，超限后短时锁定，避免暴力破解。
"""
import logging
import re
import secrets
import string
import time

from django.conf import settings
from django.contrib.auth.hashers import (
    check_password,
    get_hasher,
    identify_hasher,
    make_password,
)

from app01.utils.encrypt import md5

logger = logging.getLogger('smass.audit')

#: 历史 MD5 实现写死在旧 settings 中的密钥。
#: 该值已随源码/版本历史泄漏，此处仅用于校验历史密码，新密码一律使用官方哈希。
LEGACY_MD5_SECRET_KEY = 'django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE'

# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------
ROLE_ADMIN = 'admin'
ROLE_STUDENT = 'student'
ROLE_TEACHER = 'teacher'
ROLES = (ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER)

ROLE_LABELS = {
    ROLE_ADMIN: '管理员',
    ROLE_STUDENT: '学生',
    ROLE_TEACHER: '教师',
}

ROLE_HOME_URLS = {
    ROLE_ADMIN: '/admin/admin/list/',
    ROLE_STUDENT: '/student/users/profile/',
    ROLE_TEACHER: '/teacher/basic/',
}

ROLE_LOGIN_URLS = {
    ROLE_ADMIN: '/login/account/admin/',
    ROLE_STUDENT: '/login/account/student/',
    ROLE_TEACHER: '/login/account/teacher/',
}

# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------
_LEGACY_MD5_RE = re.compile(r'^[0-9a-f]{32}$')

_PASSWORD_ALPHABET = string.ascii_letters + string.digits

#: 生成的随机初始密码长度
DEFAULT_PASSWORD_LENGTH = 10

#: 登录失败限速
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 300
_LOGIN_FAIL_KEY = 'login_failures'


class PasswordError(ValueError):
    """密码相关的业务校验失败。"""


def generate_password(length=DEFAULT_PASSWORD_LENGTH):
    """生成随机初始密码（大小写字母 + 数字）。

    不包含易混淆符号，便于管理员口头/一次性转达。仅用于"创建账号/重置密码"，
    调用方负责让用户首次登录后自行修改。
    """
    return ''.join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def legacy_md5(raw_password):
    """用当年泄漏的密钥重算历史 MD5，仅用于兼容校验。"""
    return md5(raw_password, secret_key=LEGACY_MD5_SECRET_KEY)


def is_legacy_hash(encoded):
    """判断数据库里存的是不是旧的 32 位 MD5。"""
    return isinstance(encoded, str) and _LEGACY_MD5_RE.match(encoded) is not None


def is_preferred_hash(encoded):
    """判断编码是否已是当前首选的官方哈希算法（否则应在校验成功后升级）。"""
    if not encoded or is_legacy_hash(encoded):
        return False
    try:
        return identify_hasher(encoded).algorithm == get_hasher('default').algorithm
    except Exception:  # noqa: BLE001 - 无法识别的编码一律视为需要升级
        return False


def set_password(account, raw_password):
    """把 *raw_password* 用官方哈希写入 *account* 并落库（只更新 password 字段）。

    这是本项目中**唯一**允许写密码的入口。``raw_password`` 必须是明文。

    注意：若 *account* 尚未入库（``_state.adding``），必须走完整 ``save()``，
    否则 ``save(update_fields=[...])`` 会因 UPDATE 影响 0 行而抛 ``DatabaseError``。
    """
    if account is None:
        raise PasswordError('账号不存在')
    if not raw_password:
        raise PasswordError('密码不能为空')

    account.password = make_password(raw_password)

    if account._state.adding:
        account.save()
    else:
        account.save(update_fields=['password'])

    logger.info(
        'password_set model=%s object_id=%s',
        type(account).__name__,
        account.pk,
    )
    return account


def verify_password(account, raw_password):
    """校验密码。

    返回 ``True`` 表示通过。若命中历史 MD5（含"双重哈希"的坏数据），
    在通过的同时把该账号升级为官方哈希。
    """
    if account is None or not raw_password:
        return False

    encoded = account.password or ''
    if not encoded:
        return False

    # ---- 历史 MD5 分支（含被 save() 二次哈希的坏数据）----
    if is_legacy_hash(encoded):
        single = legacy_md5(raw_password)
        double = legacy_md5(single)
        if secrets.compare_digest(encoded, single) or secrets.compare_digest(encoded, double):
            _upgrade_to_official_hash(account, raw_password)
            return True
        return False

    # ---- Django 官方哈希分支 ----
    if not check_password(raw_password, encoded):
        return False

    if not is_preferred_hash(encoded):
        _upgrade_to_official_hash(account, raw_password)
    return True


def _upgrade_to_official_hash(account, raw_password):
    """把旧编码就地升级为官方哈希；失败不影响本次登录。"""
    try:
        account.password = make_password(raw_password)
        account.save(update_fields=['password'])
        logger.info(
            'password_hash_upgraded model=%s object_id=%s',
            type(account).__name__,
            account.pk,
        )
    except Exception:  # noqa: BLE001 - 升级失败不阻断登录
        logger.exception(
            'password_hash_upgrade_failed model=%s object_id=%s',
            type(account).__name__,
            getattr(account, 'pk', '-'),
        )


def authenticate(model, account_id, raw_password):
    """按主键校验账号密码，成功返回账号实例，失败返回 ``None``。

    调用方不要区分"账号不存在"与"密码错误"，以避免账号枚举。
    """
    if not account_id or not raw_password:
        return None
    account = model.objects.filter(pk=account_id).first()
    if account is None:
        return None
    if verify_password(account, raw_password):
        return account
    return None


def reset_password(account, new_password=None, request=None):
    """重置密码并返回一次性明文（供调用方展示一次，不落库明文）。

    默认生成随机密码；``new_password`` 仅用于测试或管理员显式指定。
    """
    if account is None:
        raise PasswordError('账号不存在')

    raw = new_password or generate_password()
    set_password(account, raw)
    log_action(request, 'password_reset', account)
    return raw


def create_account(model, raw_password=None, **fields):
    """统一账号创建入口：安全编码密码后落库。

    :return: ``(account, raw_password)`` —— 明文仅用于一次性转达，不得写入日志。
    """
    raw = raw_password or generate_password()
    account = model(**fields)
    account.password = make_password(raw)
    account.save()
    logger.info(
        'account_created model=%s object_id=%s',
        type(account).__name__,
        account.pk,
    )
    return account, raw


def save_account_form(form, model, instance=None, request=None):
    """保存账号类 ModelForm（Admin / Student / Teacher）。

    与直接 ``form.save()`` 的区别：
    - 用户**留空**密码时，编辑流程不会把空字符串写进 ``password``（会锁死账号），
      而是保持原哈希不变；
    - 新建流程留空则生成随机一次性密码，并把明文返回给调用方展示一次；
    - 明文密码始终只经过本模块编码，绝不进入日志。

    :return: ``(account, raw_password, generated)``
    """
    cleaned = dict(form.cleaned_data)
    raw = (cleaned.pop('password', '') or '').strip()
    generated = False

    if instance is None:
        account = model(**cleaned)
        if not raw:
            raw = generate_password()
            generated = True
        account.password = make_password(raw)
        account.save()
        log_action(request, 'create', account)
        return account, raw, generated

    for field_name, value in cleaned.items():
        setattr(instance, field_name, value)
    if raw:
        instance.password = make_password(raw)
    instance.save()
    log_action(request, 'update', instance)
    return instance, raw, False


# ---------------------------------------------------------------------------
# 登录限速（基于 Session，单机足够；分布式场景需换 Redis，见 R2 文档）
# ---------------------------------------------------------------------------
def login_lock_remaining(request):
    """返回剩余锁定秒数；``0`` 表示当前可尝试登录。"""
    data = request.session.get(_LOGIN_FAIL_KEY) or {}
    try:
        locked_until = float(data.get('locked_until', 0) or 0)
    except (TypeError, ValueError):
        return 0
    remaining = locked_until - time.time()
    return int(remaining) if remaining > 0 else 0


def register_login_failure(request):
    """记录一次登录失败，达到阈值后锁定。"""
    data = dict(request.session.get(_LOGIN_FAIL_KEY) or {})
    count = int(data.get('count', 0)) + 1
    if count >= LOGIN_MAX_FAILURES:
        data = {'count': 0, 'locked_until': time.time() + LOGIN_LOCK_SECONDS}
        logger.warning(
            'login_locked ip=%s attempts=%s',
            request.META.get('REMOTE_ADDR', '-'),
            LOGIN_MAX_FAILURES,
        )
    else:
        data['count'] = count
    request.session[_LOGIN_FAIL_KEY] = data


def clear_login_failures(request):
    """登录成功后清除失败计数。"""
    request.session.pop(_LOGIN_FAIL_KEY, None)


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
def establish_session(request, account, role):
    """建立登录会话。

    先 ``cycle_key()`` 轮换 Session ID，降低会话固定（Session Fixation）风险，
    再写入服务端权威角色标识；客户端无法通过参数指定角色。
    """
    if role not in ROLES:
        raise ValueError('未知角色: {}'.format(role))

    request.session.cycle_key()
    request.session['info'] = {
        'id': account.pk,
        'name': getattr(account, 'name', ''),
        'type': role,
    }
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    clear_login_failures(request)
    logger.info(
        'login_success role=%s object_id=%s ip=%s',
        role,
        account.pk,
        request.META.get('REMOTE_ADDR', '-'),
    )


def destroy_session(request):
    """登出：``flush()`` 丢弃整个会话数据与 Session ID，旧会话立即失效。"""
    info = request.session.get('info') or {}
    logger.info(
        'logout role=%s object_id=%s ip=%s',
        info.get('type', '-'),
        info.get('id', '-'),
        request.META.get('REMOTE_ADDR', '-'),
    )
    request.session.flush()


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
def log_action(request, action, obj=None, detail=None):
    """记录业务操作审计。

    只记录操作者标识、事件、对象类型与主键、来源 IP、以及**非敏感**补充说明。
    严禁传入密码、哈希、完整身份证号或手机号。
    """
    info = {}
    if request is not None:
        info = request.session.get('info') or {}

    logger.info(
        'action=%s actor=%s role=%s target=%s target_id=%s ip=%s detail=%s',
        action,
        info.get('id', '-'),
        info.get('type', '-'),
        type(obj).__name__ if obj is not None else '-',
        getattr(obj, 'pk', '-') if obj is not None else '-',
        request.META.get('REMOTE_ADDR', '-') if request is not None else '-',
        detail or '-',
    )
