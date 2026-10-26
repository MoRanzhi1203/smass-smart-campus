"""登录表单。

关键约定：**表单不参与密码哈希**。

历史实现曾在 ``clean_password`` 中先 md5 一次，而模型 ``save()`` 又 md5 一次，
造成"新建可用、编辑后失效"的隐蔽缺陷。现在表单只做格式与前后的基本校验，
明文原样交给 ``app01.services.accounts`` 统一编码与校验。
"""
from django import forms

from app01.utils.bootstrap import BootStrapForm


class BaseLoginForm(BootStrapForm):
    """登录表单基类：账号 + 密码。"""

    id = forms.CharField(label='账号', widget=forms.TextInput)
    password = forms.CharField(label='密码', widget=forms.PasswordInput)

    def clean_id(self):
        account_id = (self.cleaned_data.get('id') or '').strip()
        if not account_id:
            raise forms.ValidationError('请输入账号')
        return account_id


class AdminLoginForm(BaseLoginForm):
    """管理员登录。"""

    id = forms.CharField(label='管理员', widget=forms.TextInput)


class StudentLoginForm(BaseLoginForm):
    """学生登录。"""

    id = forms.CharField(label='学生', widget=forms.TextInput)


class TeacherLoginForm(BaseLoginForm):
    """教师登录。"""

    id = forms.CharField(label='教师', widget=forms.TextInput)
