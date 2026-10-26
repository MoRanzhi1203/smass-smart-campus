"""登录 / 注销视图。

安全要点（对应 R1-A、R1-B）：
- 密码校验统一委托 ``app01.services.accounts``，视图内不做任何哈希；
- 登录成功前调用 ``session.cycle_key()`` 轮换会话 ID，降低会话固定风险；
- 注销使用 ``session.flush()``，旧 Session ID 立即失效；
- 失败信息统一为"账号或密码错误"，不区分账号是否存在（防枚举）；
- 连续失败达阈值后短时锁定（Session 级限速）；
- 跳转目标经过 ``url_has_allowed_host_and_scheme`` 校验，防开放重定向。
"""
import logging

from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from app01 import models
from app01.form.account import (
    AdminLoginForm,
    StudentLoginForm,
    TeacherLoginForm,
)
from app01.services import accounts

logger = logging.getLogger('smass.audit')

#: 角色 -> (模型, 表单, 中文名, 默认首页)
_LOGIN_CONFIG = {
    accounts.ROLE_ADMIN: (
        models.Admin, AdminLoginForm, '管理员', accounts.ROLE_HOME_URLS[accounts.ROLE_ADMIN],
    ),
    accounts.ROLE_STUDENT: (
        models.Student, StudentLoginForm, '学生', accounts.ROLE_HOME_URLS[accounts.ROLE_STUDENT],
    ),
    accounts.ROLE_TEACHER: (
        models.Teacher, TeacherLoginForm, '教师', accounts.ROLE_HOME_URLS[accounts.ROLE_TEACHER],
    ),
}


def login(request):
    """登录主页面（角色选择入口）。"""
    return render(request, 'login/index.html')


def _safe_next(request, default_url):
    """校验 ``next`` 参数，仅允许站内跳转，避免开放重定向。"""
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return default_url


def _render_login(request, form, name_ch, status=200, lock_message=None):
    """渲染登录页（统一携带 next，保证 POST 后仍能跳回原页面）。"""
    context = {
        'form': form,
        'name_ch': name_ch,
        'next': request.POST.get('next') or request.GET.get('next', ''),
    }
    if lock_message:
        context['lock_message'] = lock_message
    return render(request, 'login/login.html', context, status=status)


def _handle_login(request, role):
    """管理员 / 学生 / 教师 共用的登录流程。"""
    model, form_class, name_ch, default_url = _LOGIN_CONFIG[role]

    if request.method == 'GET':
        return _render_login(request, form_class(), name_ch)

    # ---- 登录限速 ----
    remaining = accounts.login_lock_remaining(request)
    if remaining > 0:
        return _render_login(
            request,
            form_class(),
            name_ch,
            status=429,
            lock_message='登录失败次数过多，请 {} 秒后再试。'.format(remaining),
        )

    form = form_class(data=request.POST)

    if not form.is_valid():
        # 表单本身不合法（未填/格式错）不计入暴力破解计数
        return _render_login(request, form, name_ch)

    account = accounts.authenticate(
        model,
        form.cleaned_data['id'],
        form.cleaned_data['password'],
    )

    if account is None:
        accounts.register_login_failure(request)
        form.add_error('password', '账号或密码错误')
        return _render_login(request, form, name_ch)

    accounts.establish_session(request, account, role)
    return redirect(_safe_next(request, default_url))


def login_admin(request):
    """管理员账号登录界面。"""
    return _handle_login(request, accounts.ROLE_ADMIN)


def login_student(request):
    """学生账号登录界面。"""
    return _handle_login(request, accounts.ROLE_STUDENT)


def login_teacher(request):
    """教师账号登录界面。"""
    return _handle_login(request, accounts.ROLE_TEACHER)


def logout_account(request):
    """注销：丢弃整个会话，旧 Session ID 立即失效。"""
    accounts.destroy_session(request)
    return redirect('/login/')
