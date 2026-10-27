"""R2.1 权限矩阵（最小可行）。

约定：
- 权限以 Django ``Permission`` 表达，``content_type`` 绑定到 ``r21_account.Account``，
  因此检查形式为 ``request.user.has_perm('r21_account.<codename>')``；
- 角色通过 Django ``Group`` 承载权限（``AccountRole`` → ``Group`` 同步），
  从而复用 ``ModelBackend`` 的判定逻辑，不另造一套；
- ``dangerous_bulk_delete`` **默认不授予任何角色**（计划 G3 要求）。
"""

#: 动作 codename（与 Permission.codename 一致）
ACTION_CODENAMES = (
    'view_data',
    'add_data',
    'change_data',
    'delete_data',
    'reset_password',
    'import_data',
    'manage_roles',
    'dangerous_bulk_delete',
)

#: 角色 → 权限集合
ROLE_PERMISSIONS = {
    'system_admin': {
        'view_data', 'add_data', 'change_data', 'delete_data',
        'reset_password', 'import_data', 'manage_roles',
        # 注意：dangerous_bulk_delete 不授予
    },
    'college_admin': {
        'view_data', 'add_data', 'change_data', 'import_data',
    },
    'teacher': {
        'view_data',
    },
    'student': set(),
}

#: 人类可读标签（用于创建 Permission.name）
CODENAME_LABELS = {
    'view_data': '查看数据',
    'add_data': '新增数据',
    'change_data': '修改数据',
    'delete_data': '删除数据',
    'reset_password': '重置密码',
    'import_data': '批量导入',
    'manage_roles': '管理角色',
    'dangerous_bulk_delete': '危险批量删除',
}

#: 对象级范围说明（供 README/报告引用）
SCOPE_RULES = {
    'system_admin': '全局',
    'college_admin': '仅 scope_college 匹配的学院',
    'teacher': '仅 scope_college（作为辅导员）对应学院/班级',
    'student': '仅本人',
}
