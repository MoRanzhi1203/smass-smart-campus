from django.core.exceptions import ValidationError
from django.db import models

# 注意：密码编码统一由 app01.services.accounts 负责（Django 官方哈希）。
# 本模块历史上曾在 save() 中无条件 md5，导致编辑/重置后密码被二次哈希而失效，
# 该逻辑已移除；此处不得再引入任何密码哈希。


class Nation(models.Model):
    """ 民族表 """

    nationality = models.CharField(verbose_name='民族', max_length=10)

    def __str__(self):
        return self.nationality


"""
# 迁入民族数据
from your_app.models import Nation

nationalities = [
    '汉族', '蒙古族', '回族', '藏族', '维吾尔族', '苗族', '彝族', '壮族', '布依族', '朝鲜族',
    '满族', '侗族', '瑶族', '白族', '土家族', '哈尼族', '哈萨克族', '傣族', '黎族', '傈僳族',
    '佤族', '畲族', '高山族', '拉祜族', '水族', '东乡族', '纳西族', '景颇族', '柯尔克孜族',
    '土族', '达斡尔族', '仫佬族', '羌族', '布朗族', '撒拉族', '毛难族', '仡佬族', '锡伯族',
    '阿昌族', '普米族', '塔吉克族', '怒族', '乌孜别克族', '俄罗斯族', '鄂温克族', '德昂族', '保安族',
    '裕固族', '京族', '塔塔尔族', '独龙族', '鄂伦春族', '赫哲族', '门巴族', '珞巴族', '基诺族',
]

for nationality in nationalities:
    Nation.objects.create(nationality=nationality)
"""


class Grade(models.Model):
    """ 年级表 """

    name = models.CharField(verbose_name='年级', max_length=100)

    def __str__(self):
        return self.name


class College(models.Model):
    """ 学院表 """

    name = models.CharField(verbose_name='学院', max_length=10)

    def __str__(self):
        return self.name


class Major(models.Model):
    """ 专业表 """

    college = models.ForeignKey(verbose_name='学院', to='College', on_delete=models.SET_NULL, null=True)
    name = models.CharField(verbose_name='专业', max_length=100)

    def __str__(self):
        return self.name


class Classes(models.Model):
    """ 班级表 """

    name = models.CharField(verbose_name='班级', max_length=100)
    grade = models.ForeignKey(verbose_name='年级', to='Grade', on_delete=models.SET_NULL, null=True)
    major = models.ForeignKey(verbose_name='专业', to='Major', on_delete=models.SET_NULL, null=True)
    counsellor = models.ForeignKey(verbose_name='辅导员', to='Teacher', on_delete=models.SET_NULL, null=True)

    # 关联 辅导员与班级
    @classmethod
    def connect_instructors(cls, position_name='辅导员'):
        """把具备指定职务（默认"辅导员"）的教师，依次补位到尚无辅导员的班级。

        ⚠️ 语义说明（如实记录，勿误用）：这不是"按班级分配指定辅导员"，而是
        历史上的一次性补数据逻辑——每个空班主任最多被第一个符合条件的教师填充。
        真正的辅导员分配应走 R2 提出的显式分配接口。

        历史缺陷：
        1. 外键字段实际名为 ``counsellor``，旧代码误写 ``instructor``，直接调用会
           ``AttributeError``；
        2. 旧代码硬编码 ``position_id=1``，一旦职务表主键变化就静默失效，
           改为按职务名称匹配。
        """
        instructor_positions = (
            TeacherPosition.objects
            .filter(position__name=position_name)
            .select_related('teacher')
        )
        for instructor_position in instructor_positions:
            classes = cls.objects.filter(counsellor__isnull=True)
            for cls_obj in classes:
                cls_obj.counsellor = instructor_position.teacher
                cls_obj.save(update_fields=['counsellor'])

    def __str__(self):
        return self.name


class Building(models.Model):
    """ 楼栋表 """

    name = models.CharField(verbose_name='楼栋', max_length=100)

    def __str__(self):
        return self.name


class Dormitory(models.Model):
    """ 寝室表 """

    number = models.CharField(verbose_name='寝室号', max_length=100)

    def __str__(self):
        return self.number


class DormitoryNumber(models.Model):
    """ 寝室楼栋映射表 """

    building = models.ForeignKey(verbose_name='楼栋', to='Building', on_delete=models.CASCADE)
    dormitory = models.ForeignKey(verbose_name='寝室号', to='Dormitory', on_delete=models.CASCADE)

    def __str__(self):
        # 定义为返回str形式
        return str(self.dormitory)


class Position(models.Model):
    """ 教师职务 """
    name = models.CharField(verbose_name='教师职务', max_length=6)

    def __str__(self):
        return self.name


class TeacherPosition(models.Model):
    """ 教师与教师职务映射表 """
    teacher = models.ForeignKey(verbose_name='教师', to='Teacher', on_delete=models.CASCADE)
    position = models.ForeignKey(verbose_name='教师职务', to='Position', on_delete=models.CASCADE)


#############################################


class Admin(models.Model):
    """ 管理员表 """

    # 管理员账号设置为三位整数字符串
    id = models.CharField(verbose_name='账号', max_length=3, primary_key=True)
    name = models.CharField(verbose_name='姓名', max_length=16)
    password = models.CharField(verbose_name='密码', max_length=128)

    def __str__(self):
        return self.name


class Student(models.Model):
    """ 学生表 """

    id = models.CharField(verbose_name='学号', max_length=10, primary_key=True)
    name = models.CharField(verbose_name='姓名', max_length=16)
    password = models.CharField(verbose_name='密码', max_length=128)
    pinyin = models.CharField(verbose_name='拼音', max_length=32, null=True)

    sex_choices = (
        (0, '男'),
        (1, '女'),
    )
    sex = models.SmallIntegerField(verbose_name='性别', choices=sex_choices, null=True)

    # on_delete=models.SET_NULL, null=True 删除关联模型时将外键字段设置为 null
    # nation = models.ForeignKey(verbose_name='民族', to='Nation', on_delete=models.SET_NULL, null=True)
    nation = models.CharField(verbose_name='民族', max_length=10, null=True)

    classes = models.ForeignKey(verbose_name='班级', to='Classes', on_delete=models.SET_NULL, null=True)
    cardID = models.CharField(verbose_name='身份证号', max_length=18)
    phone = models.CharField(verbose_name='手机号', max_length=11, null=True)
    qq = models.CharField(verbose_name='QQ号', max_length=11, null=True)

    # 生成详细地址字段，暂设值的最大长度为 64
    address = models.CharField(verbose_name='详细地址', max_length=64, null=True)

    # building = models.ForeignKey(verbose_name='楼栋', to='Building', on_delete=models.SET_NULL, null=True)
    # dormitory = models.ForeignKey(verbose_name='寝室号', to='DormitoryNumber', on_delete=models.SET_NULL, null=True)

    building = models.CharField(verbose_name='楼栋', max_length=3, null=True)
    dormitory = models.CharField(verbose_name='寝室号', max_length=3, null=True)

    political_choices = (
        (0, '群众'),
        (1, '团员'),
        (2, '党员'),
    )
    political = models.SmallIntegerField(verbose_name='政治面貌', choices=political_choices, default=0)

    def __str__(self):
        return self.id


class Teacher(models.Model):
    """ 教师表 """

    id = models.CharField(verbose_name='教职员工编号', max_length=7, primary_key=True)
    name = models.CharField(verbose_name='姓名', max_length=16)
    password = models.CharField(verbose_name='密码', max_length=128)
    pinyin = models.CharField(verbose_name='拼音', max_length=32, null=True)

    sex_choices = (
        (0, '男'),
        (1, '女'),
    )
    sex = models.SmallIntegerField(verbose_name='性别', choices=sex_choices)

    nation = models.CharField(verbose_name='民族', max_length=10, null=True)

    cardID = models.CharField(verbose_name='身份证号', max_length=18)
    phone = models.CharField(verbose_name='手机号', max_length=11)
    qq = models.CharField(verbose_name='QQ号', max_length=11)

    # 生成详细地址字段，暂设值的最大长度为64
    address = models.CharField(verbose_name='详细地址', max_length=64)

    entry_time = models.DateField(verbose_name='入职时间', null=True)

    # title_choices = (
    #     (0, '助教'),
    #     (1, '讲师'),
    #     (2, '副教授'),
    #     (3, '教授'),
    # )
    # title = models.SmallIntegerField(verbose_name='教师职称', choices=title_choices)

    # position = models.ForeignKey(verbose_name='教师职务', to='Position', on_delete=models.SET_NULL, null=True)
    # 生成 TeacherPosition表
    position = models.ManyToManyField(
        verbose_name='教师职务', to='Position', through='TeacherPosition', related_name='Position'
    )

    college = models.ForeignKey(verbose_name='院系', to='College', on_delete=models.SET_NULL, null=True)

    political_choices = (
        (0, '群众'),
        (1, '团员'),
        (2, '党员'),
    )
    political = models.SmallIntegerField(verbose_name='政治面貌', choices=political_choices)

    def __str__(self):
        return self.id


########################################

class Department(models.Model):
    """ 团学部门表 """

    department = models.CharField(verbose_name='部门', max_length=10)

    faction_choices = (
        # (0, '主席团'),
        (1, '团总支'),
        (2, '学生会'),
    )
    faction = models.SmallIntegerField(verbose_name='团总支/学生会', choices=faction_choices)

    college = models.ForeignKey(verbose_name='学院', to='College', on_delete=models.CASCADE, null=True, blank=True)

    level_choices = (
        (0, '院级'),
        (1, '校级'),
    )
    level = models.SmallIntegerField(verbose_name='院/校级', choices=level_choices)

    def clean(self):
        if self.level == 0 and not self.college:
            raise ValidationError({'college': '当 level 为院级时，学院不能为空。'})
        elif self.level == 1 and self.college:
            raise ValidationError({'college': '当 level 为校级时，学院必须为空。'})

    def __str__(self):
        return self.department


class LeagueCadres(models.Model):
    """ 团学总支任职表 """

    id = models.OneToOneField(
        verbose_name='学号',
        to='Student',
        on_delete=models.CASCADE,
        primary_key=True,
    )

    department = models.ForeignKey(verbose_name='部门', to='Department', on_delete=models.CASCADE)

    duties_choices = (
        (0, '主要负责人'),
        (1, '负责人'),
        (2, '委员'),
    )
    duties = models.SmallIntegerField(verbose_name='职务', choices=duties_choices)

    def __str__(self):
        # 返回字符串类型
        return str(self.duties)


class ClassCommittee(models.Model):
    """ 班委任职表 """

    id = models.OneToOneField(
        verbose_name='学号',
        to='Student',
        on_delete=models.CASCADE,
        primary_key=True,
    )

    classes = models.ForeignKey(verbose_name='班级', to='Classes', on_delete=models.CASCADE)

    committee_choices = (
        (0, '班长'),
        (1, '副班长'),
        (2, '团支书'),
        (3, '学习委员'),
        (4, '纪律委员'),
        (5, '宣传委员'),
        (6, '组织委员'),
        (7, '生活委员'),
    )
    committee = models.SmallIntegerField(verbose_name='职务', choices=committee_choices)

    def __str__(self):
        # 返回字符串类型
        return str(self.committee)


class AccountSecurityState(models.Model):
    """账号安全状态（S02 密码生命周期）。

    设计约束：
    - **独立表**，不修改 ``Admin`` / ``Student`` / ``Teacher`` 既有表结构，
      避免对正式库做破坏性 ALTER；
    - 账号用 ``(account_type, account_id)`` 复合定位，与三张既有账号表解耦；
    - 所有策略默认关闭；本表只承载"状态"，策略本身来自可配置的 settings；
    - 表不存在时服务层降级（见 ``services/password_lifecycle.py``），
      保证"未迁移正式库"不会导致 500。
    """

    ACCOUNT_ADMIN = 'admin'
    ACCOUNT_STUDENT = 'student'
    ACCOUNT_TEACHER = 'teacher'
    ACCOUNT_TYPE_CHOICES = (
        (ACCOUNT_ADMIN, '管理员'),
        (ACCOUNT_STUDENT, '学生'),
        (ACCOUNT_TEACHER, '教师'),
    )

    account_type = models.CharField(
        verbose_name='账号类型', max_length=16, choices=ACCOUNT_TYPE_CHOICES)
    account_id = models.CharField(verbose_name='账号标识', max_length=32)

    must_change_password = models.BooleanField(verbose_name='需强制改密', default=False)
    is_active = models.BooleanField(verbose_name='启用', default=True)
    legacy_hash_pending = models.BooleanField(verbose_name='仍持有历史MD5', default=False)

    password_changed_at = models.DateTimeField(
        verbose_name='最近改密时间', null=True, blank=True)
    temp_password_expires_at = models.DateTimeField(
        verbose_name='临时口令到期', null=True, blank=True)

    #: 会话世代：改密/重置/停用时 +1，旧会话因世代不匹配而失效
    session_epoch = models.PositiveIntegerField(verbose_name='会话世代', default=0)

    last_reset_by = models.CharField(
        verbose_name='最近重置操作者', max_length=32, blank=True, default='')

    created_at = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)

    class Meta:
        db_table = 'app01_account_security_state'
        verbose_name = '账号安全状态'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['account_type', 'account_id'],
                name='uniq_app01_account_security_state',
            ),
        ]
        indexes = [
            models.Index(fields=['must_change_password'], name='idx_ass_must_change'),
            models.Index(fields=['legacy_hash_pending'], name='idx_ass_legacy_pending'),
            models.Index(fields=['is_active'], name='idx_ass_is_active'),
        ]

    def __str__(self):
        return '{}:{}'.format(self.account_type, self.account_id)


class LoginDevice(models.Model):
    """登录设备（S17）：用于并发会话列表与远程踢出。

    不直接外键到具体账号模型：生产保持 ``auth.User``，而 R22 使用
    ``r21_account.Account``，这里用字符串 ID 兼容两种身份来源。
    """

    device_id = models.CharField('设备标识', max_length=64, unique=True)
    user_id = models.CharField('用户标识', max_length=32, db_index=True)
    role = models.CharField('登录角色', max_length=16, blank=True, default='')
    session_key = models.CharField(
        '会话键', max_length=64, blank=True, default='', db_index=True)
    ip = models.CharField('来源 IP', max_length=64, blank=True, default='')
    user_agent = models.CharField(
        '客户端', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    last_seen = models.DateTimeField('最近活动', auto_now=True)
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)

    class Meta:
        db_table = 'app01_login_device'
        verbose_name = '登录设备'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['user_id', 'revoked_at'], name='idx_login_dev_user'),
        ]

    def __str__(self):
        return '{}@{}'.format(self.user_id, self.device_id[:8])
