# 细分统计（脚本生成）

## 每 App 模型/路由/视图/服务/测试

| App | 有效模型 | 路由 | 视图函数 | 服务函数 | 测试用例 |
|---|---|---|---|---|---|
| admin | 1 | 0 | 0 | 0 | 0 |
| app01 | 18 | 0 | 84 | 59 | 188 |
| auth | 3 | 0 | 0 | 0 | 0 |
| contenttypes | 1 | 0 | 0 | 0 | 0 |
| django | 0 | 7 | 0 | 0 | 0 |
| r21_account | 7 | 10 | 6 | 13 | 110 |
| r22_account | 1 | 0 | 5 | 0 | 117 |
| sessions | 1 | 0 | 0 | 0 | 0 |
| smass_a11y | 0 | 0 | 4 | 11 | 19 |
| smass_academic | 7 | 24 | 29 | 17 | 56 |
| smass_activities | 3 | 11 | 17 | 17 | 28 |
| smass_analytics | 5 | 10 | 11 | 8 | 31 |
| smass_api | 4 | 6 | 10 | 16 | 23 |
| smass_api_security | 0 | 0 | 11 | 15 | 28 |
| smass_attendance | 4 | 13 | 20 | 21 | 41 |
| smass_audit | 0 | 0 | 8 | 8 | 20 |
| smass_clubs | 3 | 8 | 13 | 19 | 28 |
| smass_data_exchange | 0 | 16 | 14 | 0 | 85 |
| smass_enrollment | 5 | 11 | 18 | 23 | 43 |
| smass_facilities | 8 | 11 | 18 | 19 | 59 |
| smass_finance | 6 | 9 | 15 | 13 | 34 |
| smass_forum | 5 | 12 | 16 | 16 | 32 |
| smass_mfa | 0 | 0 | 9 | 17 | 24 |
| smass_operations | 4 | 8 | 9 | 9 | 425 |
| smass_organization | 7 | 16 | 20 | 17 | 72 |
| smass_party | 7 | 12 | 18 | 25 | 35 |
| smass_policy | 0 | 0 | 9 | 12 | 25 |
| smass_portal | 3 | 7 | 11 | 13 | 36 |
| smass_privacy | 0 | 0 | 11 | 15 | 25 |
| smass_scheduling | 9 | 8 | 19 | 0 | 40 |
| smass_security_tests | 0 | 0 | 0 | 0 | 20 |
| smass_stepup | 0 | 0 | 10 | 12 | 26 |
| smass_uploads | 0 | 0 | 8 | 12 | 27 |
| smass_workflow | 8 | 18 | 20 | 14 | 47 |
| smass_workspace | 0 | 88 | 101 | 62 | 40 |
| tests_e2e | 0 | 0 | 0 | 0 | 16 |

## 路由前缀分布

| 前缀 | 路由数 |
|---|---|
| /r* | 194 |
| /admin | 41 |
| /student | 21 |
| /teacher | 20 |
| /exchange | 16 |
| /api | 6 |
| / | 1 |
| /login | 1 |
| /logout | 1 |
| /no-role | 1 |
| /profile | 1 |
| /notifications | 1 |
| /hub | 1 |

## 装饰器出现次数（视图与服务）

| 装饰器 | 次数 |
|---|---|
| require_POST | 180 |
| require_login | 145 |
| require_GET | 111 |
| roles_required | 67 |
| require_http_methods | 65 |
| admin_required | 63 |
| admin_only | 41 |
| student_only | 21 |
| teacher_only | 20 |
| perms.require_system_admin | 15 |
| role_required | 5 |
| csrf_exempt | 3 |
| student_required | 3 |
| api_endpoint | 2 |
| teacher_required | 1 |
| property | 1 |

## 自动生成的 M2M 中间表（不计入业务模型字典）

| App | 模型 | 表 |
|---|---|---|
| auth | Group_permissions | auth_group_permissions |
| auth | User_groups | auth_user_groups |
| auth | User_user_permissions | auth_user_user_permissions |
| r21_account | Account_groups | r21_account_account_groups |
| r21_account | Account_user_permissions | r21_account_account_user_permissions |
| smass_analytics | ReportDefinition_metrics | smass_analytics_reportdefinition_metrics |