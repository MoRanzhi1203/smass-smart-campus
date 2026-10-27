"""后台 ModelForm 集合。

关键设计（对应 R1-A）：

1. 密码字段是一个**非模型字段**（故意不写进 ``Meta.fields``）。
   原因：ModelForm 的 ``_post_clean()`` 会用 ``construct_instance`` 把
   ``Meta.fields`` 里的每个字段写回 ``self.instance``。若把 ``password`` 放进
   ``Meta.fields``，用户"留空不改密码"时就会把空字符串写进 ``instance.password``，
   保存后账号即失效——这正是历史缺陷的同类再犯。
2. 密码统一为可选：``required=False`` + ``render_value=False``。
   - 新建留空 → 视图生成随机一次性密码；
   - 编辑留空 → 完全不触碰原密码哈希。
3. 账号类表单补齐主键字段（``id``）。历史实现用 ``fields='__all__'`` 或只列
   ``name/password``，导致"新建"根本没有主键可填，新增功能实际不可用。
4. 编辑时主键置 ``disabled``，杜绝通过表单改写主键（改写会变成 INSERT 新行）。
5. ``Teacher.position`` 是带 ``through`` 的 M2M，**不能**交给 ModelForm 保存
   （``save_m2m()`` 会抛"中间模型不能直接 set"），故显式排除。
6. 数据库允许为空（``null=True``）的字段在表单层一并放开，避免"新增时被迫填写
   拼音/楼栋/寝室号"这类体验缺陷。
"""
from django import forms

from app01 import models
from app01.services import accounts
from app01.utils.bootstrap import BootStrapModelForm


class BaseAccountModelForm(BootStrapModelForm):
    """账号类表单基类（Admin / Student / Teacher）。"""

    #: 非模型字段：不放进 Meta.fields，避免被 construct_instance 写回模型
    password = forms.CharField(
        label='密码',
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='留空表示不修改密码；新建账号留空将随机生成一次性密码。',
    )

    #: 数据库层 null=True 的字段，表单层允许留空
    optional_model_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name in self.optional_model_fields:
            if name in self.fields:
                self.fields[name].required = False

        # 编辑既有记录时，主键不可修改
        if 'id' in self.fields and self.instance is not None and self.instance.pk:
            self.fields['id'].disabled = True

    @property
    def password_provided(self):
        """用户是否真的填写了密码（用于区分"留空不改"与"填了但要改"）。"""
        return bool((self.data.get(self.add_prefix('password')) or '').strip())

    def clean_password(self):
        """接入 Django 官方强度校验（R1.5-D.4）。

        只校验用户**自填**的密码；留空表示不修改，直接放行。
        随机生成的初始口令不走这里（强度由生成规则保证）。
        """
        raw = (self.cleaned_data.get('password') or '').strip()
        if not raw:
            return ''

        messages = accounts.password_errors(raw)
        if messages:
            raise forms.ValidationError(messages)
        return raw


class AdminModelForm(BaseAccountModelForm):
    """ 管理员表 """

    class Meta:
        model = models.Admin
        # password 是非模型字段，绝不能放进这里
        fields = ['id', 'name']


class StudentModelForm(BaseAccountModelForm):
    """ 学生表 """

    optional_model_fields = (
        'pinyin', 'nation', 'phone', 'qq', 'address', 'building', 'dormitory', 'sex',
    )

    class Meta:
        model = models.Student
        fields = [
            'id', 'name', 'pinyin', 'sex', 'nation', 'classes',
            'cardID', 'phone', 'qq', 'address', 'building', 'dormitory', 'political',
        ]


class TeacherModelForm(BaseAccountModelForm):
    """ 教师表 """

    optional_model_fields = ('pinyin', 'nation', 'entry_time')

    class Meta:
        model = models.Teacher
        # position 走 TeacherPosition 中间表维护，不能用 ModelForm 直接保存
        fields = [
            'id', 'name', 'pinyin', 'sex', 'nation', 'cardID',
            'phone', 'qq', 'address', 'entry_time', 'college', 'political',
        ]


class ClassesModelForm(BootStrapModelForm):
    """ 班级表 """

    class Meta:
        model = models.Classes
        fields = ['name', 'grade', 'major', 'counsellor']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 辅导员允许后分配
        if 'counsellor' in self.fields:
            self.fields['counsellor'].required = False


class CollegeModelForm(BootStrapModelForm):
    """ 学院表 """

    class Meta:
        model = models.College
        fields = ['name']


class MajorModelForm(BootStrapModelForm):
    """ 专业表 """

    class Meta:
        model = models.Major
        fields = ['college', 'name']


class DepartmentModelForm(BootStrapModelForm):
    """ 部门表 """

    class Meta:
        model = models.Department
        fields = ['department', 'faction', 'college', 'level']


class LeagueCadresModelForm(BootStrapModelForm):
    """ 团学干部表 """

    class Meta:
        model = models.LeagueCadres
        fields = ['id', 'department', 'duties']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'id' in self.fields and self.instance is not None and self.instance.pk:
            self.fields['id'].disabled = True


class ClassCommitteeModelForm(BootStrapModelForm):
    """ 班委表 """

    class Meta:
        model = models.ClassCommittee
        fields = ['id', 'classes', 'committee']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'id' in self.fields and self.instance is not None and self.instance.pk:
            self.fields['id'].disabled = True


class StuChangePassModelForm(BootStrapModelForm):
    """ 学生修改本人密码（仅校验字段，与 Student 模型无字段映射）"""

    past_password = forms.CharField(label='原密码', widget=forms.PasswordInput(render_value=False))
    new_password = forms.CharField(label='新密码', widget=forms.PasswordInput(render_value=False))
    confirm_password = forms.CharField(label='确认密码', widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = models.Student
        fields = []
