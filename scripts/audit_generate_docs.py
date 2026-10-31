#!/usr/bin/env python
"""由 inventory JSON 生成模型字典与路由目录的 Markdown 主体（只读）。"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'docs/SMASS_System_Function_Audit'
INV = AUDIT / 'inventory'

SENSITIVE_HINTS = ('password', 'phone', 'card_id', 'id_card', 'address',
                   'qq', 'email', 'mobile', 'token', 'secret', 'hash')

MODULE_TITLES = {
    'app01': '历史系统表（app01，升级迁移起点）',
    'auth': 'Django 内置认证',
    'contenttypes': 'Django 内容类型',
    'sessions': 'Django 会话',
    'admin': 'Django 管理后台日志',
    'r21_account': '统一账号与角色',
    'r22_account': '双身份桥接（R22）',
    'smass_organization': '组织与学籍',
    'smass_academic': '学年学期、课程与教学班',
    'smass_scheduling': '排课与课表',
    'smass_enrollment': '分班、转专业与学籍异动',
    'smass_attendance': '考勤与请假',
    'smass_activities': '活动、志愿与学分',
    'smass_clubs': '社团与任职',
    'smass_facilities': '场地与预约',
    'smass_forum': '论坛、公告与举报',
    'smass_finance': '账单、缴费与退费',
    'smass_party': '党建与专项组织',
    'smass_portal': '门户配置',
    'smass_workflow': '流程、审批与通知',
    'smass_analytics': '指标与报表',
    'smass_operations': '运维监控与告警',
    'smass_api': '开放 API',
}

GOVERNANCE = {
    'app01': ('历史只读；迁移源', '系统管理员（只读排查）', '不新增；仅迁移脚本读取',
              'AccountSecurityState / LoginDevice', '→ Account / StudentRecord / OrganizationUnit'),
    'r21_account': ('统一身份', '本人；管理员按范围', '系统管理员',
                    'AccountAuditLog / LoginAttempt', '承接 app01 三表账号'),
    'r22_account': ('双身份桥接', '系统管理员', '不写入（仅比对）',
                    '无', 'Legacy 映射校验'),
    'smass_organization': ('组织与学籍', '超管全校；学院管理员本院；教师本人教学班；学生本人',
                           '超管；学院管理员受字段策略限制',
                           'StudentRecordChange', 'College/Major/Classes → OrganizationUnit；Student → StudentRecord'),
    'smass_academic': ('教务', '全员按范围', '超管', 'EnrollmentHistory',
                       '无直接映射（app01 无课程表）'),
    'smass_scheduling': ('排课', '教师/学生/管理员', '超管', 'ScheduleConflict / ScheduleRun.explanation',
                         '无'),
    'smass_enrollment': ('学籍异动', '学院管理员/超管；学生本人',
                         '学生提交；管理员审批', '无独立事件表（状态字段）', '无'),
    'smass_attendance': ('考勤请假', '教师/辅导员/管理员；学生本人', '教师发起；学生提交请假',
                         '课程内建状态与审批字段', '无'),
    'smass_activities': ('活动志愿', '全员', '超管/活动负责人；学生报名',
                         'ActivityCredit 认定字段', '无'),
    'smass_clubs': ('社团', '全员', '社团负责人/超管', 'ClubPost 任职记录', 'Department/LeagueCadres 可对应'),
    'smass_facilities': ('场地', '全员', '超管建档；师生预约；管理员审批',
                         'RoomBooking 状态与审批字段', '无'),
    'smass_forum': ('论坛公告', '全员（按状态）', '超管/版主', 'Report 处置记录', '无'),
    'smass_finance': ('财务', '学生本人；财务/超管', '财务（can_finance）/超管',
                      'LedgerEntry / RefundRequest', '无'),
    'smass_party': ('党建专项', '授权用户（AccessGrant）', '超管/授权管理员',
                    'AccessLog', '无'),
    'smass_portal': ('门户配置', '全员', '超管', '无', '无'),
    'smass_workflow': ('流程审批', '发起人/审批人/超管', '发起人/审批人', 'WorkflowEvent',
                       '无'),
    'smass_analytics': ('指标报表', '按 permission_roles', '超管', 'MetricSnapshot', '无'),
    'smass_operations': ('运维', '超管', '超管', 'AlertEvent / ReadinessProbe', '无'),
    'smass_api': ('开放接口', '持令牌客户端', '超管签发', 'Token / 幂等记录', '无'),
    'smass_workspace': ('产品层（无模型）', '—', '—', '—', '—'),
}

PAGE_CATALOG = {
    'student': [
        ('学习', '学习工作台', '/student/', 'workspace:student_home', 'student.home',
         '学期、今日课表、考勤率、待缴费用、待办、公告', '查看；跳转各子页', '学生本人'),
        ('学习', '我的课表', '/student/timetable/', 'workspace:student_timetable',
         'student.timetable', '按已发布排课运行渲染周课表', '查看', '学生本人'),
        ('学习', '我的课程', '/student/courses/', 'workspace:student_courses',
         'student.courses', '选课、教学班、任课教师、学分', '查看', '学生本人'),
        ('学习', '学籍信息', '/student/record/', 'workspace:student_record',
         'student.record', '学籍、组织链、变更历史、住宿摘要', '查看', '学生本人'),
        ('日常', '考勤与请假', '/student/attendance/', 'workspace:student_attendance',
         'student.attendance', '考勤统计、最近记录、请假申请与撤销', '提交请假、撤销本人待批请假', '学生本人'),
        ('日常', '费用与账单', '/student/fees/', 'workspace:student_fees', 'student.fees',
         '账单、应缴/已缴/待缴、缴费登记', '自助缴费（台账登记）', '学生本人'),
        ('日常', '场地预约', '/student/bookings/', 'workspace:student_bookings',
         'student.bookings', '我的预约、场地列表、预约申请', '申请、取消', '学生本人'),
        ('日常', '我的寝室', '/student/dormitory/', 'workspace:student_dormitory',
         'student.dormitory', '楼栋/寝室/床位/室友', '查看', '学生本人'),
        ('校园', '活动与志愿', '/student/activities/', 'workspace:student_activities',
         'student.activities', '可报名活动、我的报名、志愿摘要', '报名、取消报名', '学生本人'),
        ('校园', '志愿服务', '/student/volunteer/', 'workspace:student_volunteer',
         'student.volunteer', '已认定志愿时长与学分', '查看', '学生本人'),
        ('校园', '社团', '/student/clubs/', 'workspace:student_clubs', 'student.clubs',
         '社团名录、我的社团与任职', '申请加入', '学生本人'),
        ('校园', '学生组织', '/student/organizations/', 'workspace:student_organizations',
         'student.organizations', '组织名录、我的组织归属、班级', '查看', '学生本人'),
        ('消息', '通知公告', '/student/notices/', 'workspace:student_notices',
         'student.notices', '面向学生的已发布公告', '查看', '学生本人'),
        ('消息', '通知中心（共用）', '/notifications/', 'workspace:notifications',
         'common.notifications', '站内通知 + 公告合并，打开即标记已读', '查看', '登录用户'),
        ('账号', '个人中心（共用）', '/profile/', 'workspace:profile', 'common.profile',
         '账号、角色、组织关系、可用工作台', '查看；进入改密', '登录用户'),
    ],
    'teacher': [
        ('教学', '教学工作台', '/teacher/', 'workspace:teacher_home', 'teacher.home',
         '教学班、学生数、今日课程、待批、通知', '查看；快捷入口', '教师'),
        ('教学', '我的课程', '/teacher/courses/', 'workspace:teacher_courses',
         'teacher.courses', '本人教学班与选课人数', '查看', '教师本人'),
        ('教学', '教学班', '/teacher/sections/', 'workspace:teacher_sections',
         'teacher.sections', '教学班与学生名单', '查看', '教师本人教学班'),
        ('教学', '我的课表', '/teacher/timetable/', 'workspace:teacher_timetable',
         'teacher.timetable', '教师视角周课表', '查看', '教师本人'),
        ('学生事务', '考勤管理', '/teacher/attendance/', 'workspace:teacher_attendance',
         'teacher.attendance', '考勤场次列表与发起', '发起考勤', '教师本人教学班班级'),
        ('学生事务', '考勤登记', '/teacher/attendance/<pk>/',
         'workspace:teacher_attendance_detail', 'teacher.attendance_detail',
         '逐人登记出勤/迟到/缺勤/请假、结束场次', '登记、结束', '场次归属校验'),
        ('学生事务', '学生事务', '/teacher/students/', 'workspace:teacher_students',
         'teacher.students', '本人教学班学生', '查看', '教学班范围'),
        ('学生事务', '学生档案', '/teacher/students/<pk>/',
         'workspace:teacher_student_detail', 'teacher.student_detail',
         '学生选课/考勤/请假', '查看', '对象级校验'),
        ('学生事务', '审批中心', '/teacher/approvals/', 'workspace:teacher_approvals',
         'teacher.approvals', '请假、补签、流程待办、场地预约', '批准/驳回/完成', '范围内学生与本人待办'),
        ('辅导员', '负责班级', '/teacher/classes/', 'workspace:teacher_classes',
         'teacher.classes', '负责班级与学生', '查看', '仅辅导员'),
        ('辅导员', '负责学生', '/teacher/counselor/students/',
         'workspace:teacher_counselor_students', 'teacher.counselor_students',
         '负责范围内学生', '查看', '仅辅导员'),
        ('辅导员', '请假审批', '/teacher/counselor/leaves/',
         'workspace:teacher_leave_review', 'teacher.leave_review',
         '负责学生请假审批', '批准/驳回', '仅辅导员'),
        ('消息', '通知与公告', '/teacher/notices/', 'workspace:teacher_notices',
         'teacher.notices', '面向教师的公告', '查看', '教师'),
    ],
    'admin': [
        ('总览', '控制台总览', '/admin/', 'workspace:admin_home', 'admin.home',
         '账号/学籍/教学/排课/活动/费用/监控汇总', '查看；快捷入口', '管理员'),
        ('身份与组织', '用户账号', '/admin/users/', 'workspace:admin_users',
         'admin.users', '账号列表、筛选、角色、启停、重置口令、创建', '创建/授角色/停用/重置', '超管写；学院管理员只读'),
        ('身份与组织', '角色与权限', '/admin/roles/', 'workspace:admin_roles',
         'admin.roles', '四个角色与账号数、能力说明', '查看', '管理员'),
        ('身份与组织', '组织架构', '/admin/organizations/', 'workspace:admin_organizations',
         'admin.organizations', '组织单元树与人员归属', '查看', '管理员（范围）'),
        ('学籍与教学', '学籍管理', '/admin/records/', 'workspace:admin_records',
         'admin.records', '学籍列表与筛选', '查看', '管理员（范围）'),
        ('学籍与教学', '学籍档案', '/admin/records/<no>/', 'workspace:admin_record_detail',
         'admin.record_detail', '学籍详情、选课、编辑表单', '超管编辑姓名/状态/班级', '学院管理员只读'),
        ('学籍与教学', '学籍异动', '/admin/record-changes/', 'workspace:admin_record_changes',
         'admin.record_changes', '转专业与学籍状态变更', '批准/驳回', '范围内学生'),
        ('学籍与教学', '学年学期与课程', '/admin/academics/', 'workspace:admin_academics',
         'admin.academics', '学年/学期/课程列表 + 新建表单', '超管新建', '超管写；学院管理员只读'),
        ('学籍与教学', '教学班与选课', '/admin/sections/', 'workspace:admin_sections',
         'admin.sections', '教学班列表 + 新建', '超管新建教学班', '超管写'),
        ('学籍与教学', '教学班名单', '/admin/sections/<pk>/roster/',
         'workspace:admin_section_roster', 'admin.section_roster',
         '选课名单与任课教师', '查看', '管理员'),
        ('排课与资源', '排课与课表', '/admin/scheduling/', 'workspace:admin_scheduling',
         'admin.scheduling', '排课运行、冲突、发布状态', '查看；进入排课求解（专业工具）', '管理员'),
        ('排课与资源', '教室与场地', '/admin/facilities/', 'workspace:admin_facilities',
         'admin.facilities', '场地台账 + 新增场地', '超管新增场地', '超管写'),
        ('排课与资源', '预约审批', '/admin/booking-approvals/',
         'workspace:admin_booking_approvals', 'admin.booking_approvals',
         '待批场地预约', '批准/驳回', '管理员'),
        ('审批与工作流', '待办与审批', '/admin/approvals/', 'workspace:admin_approvals',
         'admin.approvals', '待批请假/流程/场地 + 请假状态', '批准/驳回/完成', '范围内'),
        ('审批与工作流', '流程定义', '/admin/workflows/', 'workspace:admin_workflows',
         'admin.workflows', '流程定义与实例', '查看；进入流程编辑（专业工具）', '管理员'),
        ('校园业务', '活动管理', '/admin/activities/', 'workspace:admin_activities',
         'admin.activities', '活动列表 + 创建', '超管创建/发布/结束/生成学分', '超管写'),
        ('校园业务', '社团与学生组织', '/admin/clubs/', 'workspace:admin_clubs',
         'admin.clubs', '社团与部门组织', '查看', '管理员'),
        ('校园业务', '通知公告', '/admin/notices/', 'workspace:admin_notices',
         'admin.notices', '公告列表 + 发布', '超管创建/发布', '超管写'),
        ('数据治理', '数据导入导出', '/admin/data-exchange/', 'workspace:admin_data_exchange',
         'admin.data_exchange', '可用数据集清单', '查看；进入导入向导（专业工具）', '管理员'),
        ('运维与安全', '运行监控', '/admin/monitoring/', 'workspace:admin_monitoring',
         'admin.monitoring', '请求指标、慢请求、探针、告警', '查看', '管理员'),
        ('运维与安全', '安全审计', '/admin/audit/', 'workspace:admin_audit',
         'admin.audit', '账号操作日志、登录尝试', '查看', '管理员'),
        ('运维与安全', '系统配置', '/admin/settings/', 'workspace:admin_settings',
         'admin.settings', '动作权限、角色账号数、字段策略、密码策略', '查看', '仅超管'),
    ],
}

MODULE_INTRO = {
    'app01': '原始校园系统的三张账号表（Admin/Student/Teacher）及组织、寝室、职务表。'
             '产品登录已不使用这些表，但历史数据是升级迁移的起点；迁移脚本把其中的'
             '学院/专业/班级/学生/教师/管理员映射到统一模型。',
    'auth': 'Django 默认用户与权限表。产品认证使用 r21_account.Account，'
            '`AUTH_USER_MODEL` 未被改写；auth 表仅被 Django 权限框架引用。',
    'r21_account': '统一身份权威：Account（登录）、AccountRole（角色）、'
                   'StudentProfile/TeacherProfile（业务档案轻量映射）、'
                   'LegacyAccountLink（历史账号锚点）、AccountAuditLog/LoginAttempt（审计）。',
    'r22_account': 'R22 双身份桥接表，用于在正式切换前比对旧 app01 账号与新账号的映射状态；'
                   '产品路径不依赖它做登录，迁移脚本也不写入该表。',
    'smass_organization': '组织树（学院/专业/年级/班级/部门）、学籍档案、'
                          '学籍变更历史、字段策略、导入批次。',
    'smass_academic': '学年、学期、课程、教学班、任课分配、选课与选课历史。',
    'smass_scheduling': '节次、教师档案与约束、群体、排课运行、课时需求、'
                        '课表条目与冲突解释。',
    'smass_enrollment': '自动分班规则/批次/结果、转专业申请、学籍状态变更。',
    'smass_attendance': '考勤场次、逐人考勤、请假、补签。',
    'smass_activities': '活动、报名、第二课堂学分与志愿时长认定。',
    'smass_clubs': '社团、成员关系、社团职务任命。',
    'smass_facilities': '楼宇、房间、设备、资格、可用时段、维护期、预约。',
    'smass_forum': '板块、帖子、评论、举报、公告。',
    'smass_finance': '收费项目、账单、缴费、退费申请、台账。',
    'smass_party': '党建/专项组织、成员、活动、文档、访问授权与访问日志。',
    'smass_portal': '门户分区、链接与门户公告（配置型）。',
    'smass_workflow': '流程定义/版本/节点/流转、实例、事件、待办、通知。',
    'smass_analytics': '指标定义、快照、报表定义/运行、数据质量问题。',
    'smass_operations': '请求指标、告警规则/事件、就绪探针。',
    'smass_api': 'API 客户端、令牌、幂等记录（开放接口）。',
}


def load(name):
    return json.loads((INV / name).read_text(encoding='utf-8'))


def is_sensitive(field):
    name = field['name'].lower()
    return any(hint in name for hint in SENSITIVE_HINTS)


def field_line(field):
    bits = [field['type']]
    if field.get('max_length'):
        bits.append('max={}'.format(field['max_length']))
    if field['null']:
        bits.append('null')
    if field['blank']:
        bits.append('blank')
    if field['unique']:
        bits.append('unique')
    if field.get('choices'):
        bits.append('choices={}'.format('/'.join(
            item['value'] for item in field['choices'][:8])))
    if field.get('related_model'):
        bits.append('→ {}'.format(field['related_model']))
    if field.get('on_delete'):
        bits.append('on_delete={}'.format(field['on_delete']))
    return ' '.join(bits)


def model_dictionary(models, apps):
    app_order = [item['label'] for item in apps if not item['builtin']]
    grouped = defaultdict(list)
    for model in models:
        if model['auto_created']:
            continue
        grouped[model['app_label']].append(model)

    lines = [
        '# 数据模型字典',
        '',
        '> 生成方式：`scripts/audit_system_inventory.py` 读取 Django 模型元数据，'
        '`scripts/audit_generate_docs.py` 渲染为 Markdown。',
        '> 统计口径：有效模型 %d 个（其中项目模型 %d、Django 内置 %d），'
        '自动 M2M 中间表 %d 个单列在文末。' % (
            len([m for m in models if not m['auto_created']]),
            len([m for m in models if not m['auto_created']
                 and m['app_label'] in app_order]),
            len([m for m in models if not m['auto_created']
                 and m['app_label'] not in app_order]),
            len([m for m in models if m['auto_created']])),
        '',
        '## 阅读说明',
        '',
        '- **表**：模型实际对应的数据库表名；',
        '- **字段**：类型、长度、可空、唯一、枚举值与关系目标；',
        '- **敏感**列：字段名命中个人信息/凭据关键字，需按字段策略脱敏；',
        '- **约束/索引**：模型 `Meta.constraints` 与 `Meta.indexes` 的实测值；',
        '- **审计**：该模型是否有历史/审计表（仅在存在对应模型时标记）。',
        '',
        '## 模块治理与数据归属',
        '',
        '> 依据：各模块服务函数的权限判定、视图守卫、`r21_account/authorization.py` '
        '与 `smass_workspace/permissions.py`。',
        '',
        '| App | 定位 | 读取范围 | 写入角色 | 审计/历史 | app01 映射 |',
        '|---|---|---|---|---|---|',
    ]
    for app in app_order:
        if app not in GOVERNANCE:
            continue
        item = GOVERNANCE[app]
        lines.append('| `{}` | {} | {} | {} | {} | {} |'.format(app, *item))
    lines += ['', '## 目录', '',]
    for app in app_order:
        if app not in grouped:
            continue
        lines.append('- [{} · {}](#{})'.format(
            app, MODULE_TITLES.get(app, app), app.replace('_', '-')))

    for app in app_order:
        if app not in grouped:
            continue
        lines += ['', '---', '',
                  '## {}'.format(app), '',
                  '### {}'.format(MODULE_TITLES.get(app, app)), '']
        if app in MODULE_INTRO:
            lines += [MODULE_INTRO[app], '']
        for model in sorted(grouped[app], key=lambda item: item['model']):
            lines += ['#### `{}`（表 `{}`）'.format(
                model['model'], model['db_table']), '',
                '- 业务名称：{}'.format(model['verbose_name']),
                '- 主键：`{}`'.format(model['pk_field']),
                '- 排序：{}'.format(
                    '、'.join(model['ordering']) if model['ordering'] else '未设置'),
                '- 敏感字段：{}'.format(
                    '、'.join('`{}`'.format(f['name']) for f in model['fields']
                             if is_sensitive(f)) or '无'),
                '']
            if model['fields']:
                lines += ['| 字段 | 类型/约束 | 可空 | 唯一 | 说明 |',
                          '|---|---|---|---|---|']
                for field in model['fields']:
                    lines.append('| `{}` | {} | {} | {} | {} |'.format(
                        field['name'], field_line(field),
                        '是' if field['null'] else '否',
                        '是' if field['unique'] else '否',
                        field['verbose_name'] or ''))
                lines.append('')
            if model['relations']:
                lines += ['关系：', '']
                for rela in model['relations']:
                    lines.append('- `{}` → `{}`（related_name=`{}`，on_delete={}）'.format(
                        rela['name'], rela.get('related_model', ''),
                        rela.get('related_name') or '默认',
                        rela.get('on_delete') or '—'))
                lines.append('')
            if model['constraints'] or model['indexes'] or model['unique_together']:
                lines += ['约束与索引：', '']
                for constraint in model['constraints']:
                    lines.append('- 约束 `{}`（{}）：fields={} condition={}'.format(
                        constraint['name'], constraint['type'],
                        constraint['fields'], constraint['condition']))
                for index in model['indexes']:
                    lines.append('- 索引 `{}`：fields={} condition={}'.format(
                        index['name'], index['fields'], index['condition']))
                for unique in model['unique_together']:
                    lines.append('- unique_together：{}'.format(unique))
                lines.append('')

    auto = [m for m in models if m['auto_created']]
    lines += ['---', '', '## 自动生成的 M2M 中间表', '',
              '以下表由 Django 自动创建，不单独出现在业务代码中：', '',
              '| App | 模型 | 表 |', '|---|---|---|']
    for item in auto:
        lines.append('| {} | {} | {} |'.format(
            item['app_label'], item['model'], item['db_table']))
    lines += ['', '## Django 内置模型（6 个有效模型）', '',
              '产品未改写 `AUTH_USER_MODEL`，以下内置表随 Django 迁移创建；'
              '产品路径只间接使用其中部分。', '',
              '| App | 模型 | 表 | 用途 | 产品是否使用 | 敏感 |',
              '|---|---|---|---|---|---|',
              '| `auth` | `User` | `auth_user` | Django 默认用户（产品中为空置） | 否（认证走 `r21_account.Account`） | 密码哈希 |',
              '| `auth` | `Group` | `auth_group` | 角色权限组（`r21_*` 组） | 是（`sync_account_groups`） | 否 |',
              '| `auth` | `Permission` | `auth_permission` | 动作 codename | 是（RBAC 判定） | 否 |',
              '| `contenttypes` | `ContentType` | `django_content_type` | 权限绑定模型 | 是（间接） | 否 |',
              '| `sessions` | `Session` | `django_session` | 登录会话 | 是 | 会话键 |',
              '| `admin` | `LogEntry` | `django_admin_log` | Django 后台操作日志 | 否（未挂载 admin 站点） | 否 |',
              '',
              '> 统计：项目有效模型 114 + 内置 6 = 120；自动 M2M 中间表 6 个（见上节）。',
              '']
    lines += ['', '## 数据关系（文字 ER）', '',
              '- `r21_account.Account` 1:1 `StudentProfile` / `TeacherProfile`；',
              '- `Account` 1:N `StudentRecord`（学籍档案）、`Enrollment`（选课）、'
              '`TeachingAssignment`（任课）、`RoomBooking`（预约）、`Notification`（通知）；',
              '- `OrganizationUnit` 自关联树（学院→专业/年级→班级；部门自嵌套）；',
              '- `StudentRecord` N:1 `OrganizationUnit`；1:N `AttendanceRecord`、'
              '`LeaveRequest`、`ActivityRegistration`、`ActivityCredit`、`ClubMembership`、'
              '`Bill`；',
              '- `AcademicTerm` N:1 `AcademicYear`；`TeachingSection` N:1 `AcademicTerm`+`Course`；'
              '`Enrollment` N:1 `TeachingSection`+`Account`；',
              '- `ScheduleRun` 1:N `LessonRequirement`/`ScheduleEntry`/`ScheduleConflict`；'
              '`ScheduleEntry` N:1 `Room`/`Teacher`/`Cohort`；',
              '- `RoomBooking` N:1 `Room`+`Account`；`Bill` 1:N `BillItem`/`Payment`/`RefundRequest`；',
              '- `WorkflowInstance` 1:N `WorkflowEvent`/`ApprovalTask`；'
              '`Notification` 独立按 `recipient` 字符串关联登录名。',
              '']
    return '\n'.join(lines)


def route_catalog(urls, apps):
    prefix_groups = defaultdict(list)
    for item in urls:
        path = item['path']
        parts = [part for part in path.split('/') if part]
        key = '/' + parts[0] if parts else '/'
        if key.startswith('/r') and key[2:].isdigit():
            key = '/r4–/r20（历史模块）'
        if key.startswith('/s') and key[2:].isdigit():
            key = '/s09–/s19（安全模块）'
        prefix_groups[key].append(item)

    lines = [
        '# 页面与路由目录',
        '',
        '> 路由由 Django URL 解析器实际展开得到（`scripts/audit_system_inventory.py`）。'
        '共 %d 条，全部具名。' % len(urls),
        '',
        '## 分组统计',
        '',
        '| 前缀 | 路由数 | 说明 |',
        '|---|---|---|',
    ]
    for key in sorted(prefix_groups, key=lambda item: -len(prefix_groups[item])):
        lines.append('| `{}` | {} | {} |'.format(
            key, len(prefix_groups[key]),
            '产品三端' if key in ('/student', '/teacher', '/admin') else
            '统一入口与共用页面' if key in ('/', '/login', '/logout', '/profile',
                                            '/notifications', '/no-role') else
            '历史业务模块（保留）' if key.startswith('/r') else
            '安全模块（独立配置）' if key.startswith('/s') else '其它'))

    for key in sorted(prefix_groups):
        lines += ['', '---', '', '## `{}`'.format(key), '',
                  '| 路径 | 名称 | 视图 |', '|---|---|---|']
        for item in sorted(prefix_groups[key], key=lambda x: x['path']):
            lines.append('| `{}` | `{}` | `{}` |'.format(
                item['path'], item['name'], item['real_view']))
    lines += ['', '---', '', '## 产品三端页面说明', '',
              '产品页面共 %d 个（学生 %d / 教师 %d / 管理 %d），'
              '全部由 `templates/workspace/base.html` 与 `static/workspace/app.css` 渲染。' % (
                  sum(len(value) for value in PAGE_CATALOG.values()),
                  len(PAGE_CATALOG['student']), len(PAGE_CATALOG['teacher']),
                  len(PAGE_CATALOG['admin'])), '']
    labels = {'student': '学生工作台', 'teacher': '教师工作台',
              'admin': '管理控制台'}
    for kind in ('student', 'teacher', 'admin'):
        lines += ['### {}（{} 页）'.format(
            labels[kind], len(PAGE_CATALOG[kind])), '',
            '| 一级菜单 | 页面 | URL | 命名路由 | view | 用途 | 主要操作 | 权限 |',
            '|---|---|---|---|---|---|---|---|']
        for row in PAGE_CATALOG[kind]:
            lines.append('| {} | {} | `{}` | `{}` | `{}` | {} | {} | {} |'.format(*row))
        lines.append('')
    return '\n'.join(lines)


def main():
    apps = load('apps.json')
    models = load('models.json')
    urls = load('urls.json')

    (AUDIT / '04_Data_Model_Dictionary.md').write_text(
        model_dictionary(models, apps), encoding='utf-8')
    (AUDIT / '05_Page_and_Route_Catalog.md').write_text(
        route_catalog(urls, apps), encoding='utf-8')
    print('generated 04, 05')


if __name__ == '__main__':
    raise SystemExit(main())
