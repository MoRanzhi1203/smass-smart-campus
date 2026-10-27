"""路径 B 可行性实验（隔离库 smass_proto_user_model）。

验证清单（对应计划 §6.3 P0 "比较 A/B，验证 Django 管理后台与权限行为"）：

1. 从零迁移是否成功（``AUTH_USER_MODEL`` 在全新库上生效）；
2. ``create_user`` / ``create_superuser`` 是否正常；
3. ``PermissionsMixin`` 提供的 ``has_perm`` 是否可用（授权前 False / 授权后 True）；
4. Django admin 站点是否可登录（``request.user`` 是否为自定义用户）。

**边界**：本实验刻意不装 ``app01``，属于"全新项目"场景；
它证明"B 技术可行"，但**不能**证明"在已有 4 个 app01 迁移的在用库上中途切换是安全的"。

用法：
    conda run -n smass python scripts/proto_user_model_experiment.py
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smass.settings_proto_user')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import authenticate  # noqa: E402
from django.contrib.auth.models import Permission  # noqa: E402
from django.db import connection  # noqa: E402

from proto_user_model.models import ProtoUser  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print('{} {} {}'.format('PASS' if ok else 'FAIL', name, detail))


def guard():
    db = connection.settings_dict['NAME']
    if db != 'smass_proto_user_model':
        raise SystemExit('拒绝：只在路径 B 实验库执行，当前 {!r}'.format(db))
    print('target database : {}'.format(db))
    print('AUTH_USER_MODEL: {}'.format(settings.AUTH_USER_MODEL))


def main():
    guard()

    # ---- 2. 创建用户 / 超级用户 ----
    ProtoUser.objects.all().delete()

    user = ProtoUser.objects.create_user(
        'T100001', 'Probe#2024', display_name='实验教师', person_type='teacher'
    )
    check('create_user', user.pk is not None and user.check_password('Probe#2024'))
    check('normal user is not staff', user.is_staff is False)

    superuser = ProtoUser.objects.create_superuser(
        '900', 'Root#2024', display_name='实验超管', person_type='admin'
    )
    check('create_superuser', superuser.is_superuser and superuser.is_staff)

    # ---- 3. 认证 ----
    authed = authenticate(username='T100001', password='Probe#2024')
    check('authenticate via default backend', authed is not None and authed.pk == user.pk)

    bad = authenticate(username='T100001', password='wrong')
    check('wrong password rejected', bad is None)

    # ---- 4. 权限行为（PermissionsMixin）----
    # 注意 1：Django 语义下 superuser 的 has_perm 恒为 True，
    #         因此必须用**普通用户**来验证"授权前 False / 授权后 True"。
    # 注意 2：Permission 必须绑定到正确的 ContentType，否则 has_perm('app_label.codename')
    #         查不到——全新库里没有 app01 的 ContentType，这里用本模型的。
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(ProtoUser)
    perm_code = '{}.reset_password'.format(content_type.app_label)

    check('has_perm before grant is False', user.has_perm(perm_code) is False)

    perm, _ = Permission.objects.get_or_create(
        codename='reset_password',
        content_type=content_type,
        defaults={'name': 'Can reset password'},
    )
    user.user_permissions.add(perm)
    user = ProtoUser.objects.get(pk=user.pk)

    check(
        'has_perm after grant is True',
        user.has_perm(perm_code) is True,
        '({})'.format(perm_code),
    )

    check(
        'superuser has_perm always True',
        superuser.has_perm('proto_user_model.never_granted') is True,
    )

    # ---- 5. admin 站点可登录 ----
    from django.contrib import admin
    from django.test import Client

    check('admin site loaded', admin.site is not None)

    client = Client()
    logged_in = client.login(username='900', password='Root#2024')
    check('django admin login works', logged_in is True)

    if logged_in:
        # Django 测试 Client 默认 Host 是 testserver，需显式给一个在 ALLOWED_HOSTS 内的 host
        resp = client.get('/admin/', HTTP_HOST='localhost')
        check(
            'admin index reachable',
            resp.status_code == 200,
            'status={}'.format(resp.status_code),
        )

    print('')
    print('users in experiment db: {}'.format(ProtoUser.objects.count()))
    failed = [item for item in results if not item[1]]
    print('summary: {} checks, {} failed'.format(len(results), len(failed)))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
