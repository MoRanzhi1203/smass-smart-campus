"""验证码生成测试（Pillow 用法的最小回归保护）。

``app01/utils/code.py`` 是全项目唯一直接使用 Pillow 的模块。
2026-10-27 因 pip-audit 报告 62 个 CVE 而把 Pillow 从 12.2.0 升到 13.0.0，
本测试用于固化"升级后仍能正常绘图"这一事实。
"""
from app01.utils.code import check_code

import unittest

from django.test import TestCase


class CaptchaGeneratorTests(TestCase):
    def test_default_size_and_code_length(self):
        image, code = check_code()

        self.assertEqual(image.size, (120, 30))
        self.assertEqual(image.mode, 'RGB')
        self.assertEqual(len(code), 5)
        self.assertTrue(code.isalpha())

    def test_custom_size_and_length(self):
        image, code = check_code(width=160, height=40, char_length=4)

        self.assertEqual(image.size, (160, 40))
        self.assertEqual(len(code), 4)
