from django import forms

from app01.utils.bootstrap import BootStrapForm
from app01.utils.encrypt import md5


class AdminLoginForm(BootStrapForm):
    id = forms.CharField(label='管理员', widget=forms.TextInput)
    password = forms.CharField(label='密码', widget=forms.PasswordInput(render_value=True))

    def clean_password(self):
        password = self.cleaned_data.get('password')
        return md5(password)


class StudentLoginForm(BootStrapForm):
    id = forms.CharField(label='学生', widget=forms.TextInput)
    password = forms.CharField(label='密码', widget=forms.PasswordInput(render_value=True))

    def clean_password(self):
        password = self.cleaned_data.get('password')
        return md5(password)