"""G2：静态守卫 —— 防止 ``app01`` 重新引入"默认用户模型"依赖（L2）。

清单依据：G0 实测 ``app01`` 内 ``get_user_model()`` / ``AUTH_USER_MODEL`` /
``request.user`` 命中数均为 0，所以守卫可以要求**零违规**（无需白名单）。

守卫检查两类风险：
1. 调用 ``get_user_model()``（会拿到 ``auth.User``，不是 ``Account``）；
2. 直接读 ``settings.AUTH_USER_MODEL`` 并据此取模型。
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

APP_ROOT = Path(__file__).resolve().parents[2]

BANNED_CALL_NAMES = {'get_user_model'}
BANNED_SETTINGS_ATTR = 'AUTH_USER_MODEL'


def iter_python_files(root):
    for path in sorted(root.rglob('*.py')):
        rel = path.relative_to(APP_ROOT).as_posix()
        if '__pycache__' in rel or '/migrations/' in rel:
            continue
        yield path, rel


class StaticGuardTests(SimpleTestCase):
    def test_no_get_user_model_calls_in_app01(self):
        violations = []

        for path, rel in iter_python_files(APP_ROOT / 'app01'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=rel)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in BANNED_CALL_NAMES:
                    violations.append('{}:{} {}'.format(rel, node.lineno, name))

        self.assertEqual(violations, [], 'app01 不应直接调用 get_user_model()')

    def test_no_auth_user_model_reads_in_app01(self):
        violations = []

        for path, rel in iter_python_files(APP_ROOT / 'app01'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == BANNED_SETTINGS_ATTR:
                    violations.append('{}:{}'.format(rel, node.lineno))
                if isinstance(node, ast.Constant) and node.value == BANNED_SETTINGS_ATTR:
                    violations.append('{}:{} literal'.format(rel, node.lineno))

        self.assertEqual(violations, [], 'app01 不应读取 settings.AUTH_USER_MODEL')

    def test_guard_itself_detects_a_violation(self):
        """自检：守卫必须能真的发现问题（避免"空转通过"）。"""
        sample = "from django.contrib.auth import get_user_model\nget_user_model()\n"
        tree = ast.parse(sample)
        found = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in BANNED_CALL_NAMES
        ]
        self.assertEqual(len(found), 1)
