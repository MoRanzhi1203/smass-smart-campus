from django import forms

from app01 import models
from app01.utils.bootstrap import BootStrapModelForm
from app01.utils.encrypt import md5


class AdminModelForm(BootStrapModelForm):
    """ 管理员表 """

    class Meta:
        model = models.Admin
        fields = ['name', 'password']

        widgets = {
            # 隐藏密码输入值
            'password': forms.PasswordInput(render_value=True),
        }


class StudentModelForm(BootStrapModelForm):
    """ 学生表 """

    class Meta:
        model = models.Student
        fields = '__all__'

        widgets = {
            # 隐藏密码输入值
            'password': forms.PasswordInput(render_value=True),
        }


class TeacherModelForm(BootStrapModelForm):
    """ 教师表 """

    class Meta:
        model = models.Teacher
        fields = '__all__'

        widgets = {
            # 隐藏密码输入值
            'password': forms.PasswordInput(render_value=True),
        }


class ClassesModelForm(BootStrapModelForm):
    """ 班级表 """

    class Meta:
        model = models.Classes
        fields = '__all__'


class CollegeModelForm(BootStrapModelForm):
    """ 学院表 """

    class Meta:
        model = models.College
        fields = '__all__'


class MajorModelForm(BootStrapModelForm):
    """ 专业表 """

    class Meta:
        model = models.Major
        fields = '__all__'


class DepartmentModelForm(BootStrapModelForm):
    """ 部门表 """

    class Meta:
        model = models.Department
        fields = '__all__'


class LeagueCadresModelForm(BootStrapModelForm):
    """ 团学干部表 """

    class Meta:
        model = models.LeagueCadres
        fields = '__all__'

class ClassCommitteeModelForm(BootStrapModelForm):
    """ 班委表 """

    class Meta:
        model = models.ClassCommittee
        fields = '__all__'


class StuChangePassModelForm(BootStrapModelForm):
    """ 重置密码 """

    past_password = forms.CharField(label='原密码', widget=forms.PasswordInput(render_value=True))
    new_password = forms.CharField(label='新密码', widget=forms.PasswordInput(render_value=True))
    confirm_password = forms.CharField(label='确认密码', widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = models.Student
        fields = []

        widgets = {
            'past_password': forms.PasswordInput(render_value=True),
            'new_password': forms.PasswordInput(render_value=True),
            'confirm_password': forms.PasswordInput(render_value=True),
        }
