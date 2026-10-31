#!/usr/bin/env python
"""文档覆盖率检查：模型、路由、角色、模块、流程是否都有对应条目（只读）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'docs/SMASS_System_Function_Audit'
INV = AUDIT / 'inventory'

REQUIRED_FILES = [
    '00_System_Overview.md', '01_Account_Types_and_Workspaces.md',
    '02_Role_Permission_Matrix.md', '03_Module_Function_Catalog.md',
    '03_Module_Catalog_Part1.md', '03_Module_Catalog_Part2.md',
    '03_Module_Catalog_Part3.md', '04_Data_Model_Dictionary.md',
    '05_Page_and_Route_Catalog.md', '06_Cross_Module_Workflows.md',
    '07_UI_Usability_Audit.md', '08_Gaps_and_Technical_Debt.md',
    '09_Test_and_Evidence_Index.md', '10_Executive_Summary.md',
]


def read(name):
    path = AUDIT / name
    return path.read_text(encoding='utf-8') if path.exists() else ''


def main():
    models = json.loads((INV / 'models.json').read_text(encoding='utf-8'))
    urls = json.loads((INV / 'urls.json').read_text(encoding='utf-8'))

    project_labels = {
        'app01', 'r21_account', 'r22_account', 'smass_organization',
        'smass_academic', 'smass_scheduling', 'smass_enrollment',
        'smass_attendance', 'smass_activities', 'smass_clubs',
        'smass_facilities', 'smass_forum', 'smass_finance', 'smass_party',
        'smass_portal', 'smass_workflow', 'smass_analytics',
        'smass_operations', 'smass_api',
    }
    effective = [item for item in models if not item['auto_created']]
    project_models = [item for item in effective
                      if item['app_label'] in project_labels]

    dict_text = read('04_Data_Model_Dictionary.md')
    missing_models = [item['model'] for item in project_models
                      if '`{}`'.format(item['model']) not in dict_text]

    route_text = read('05_Page_and_Route_Catalog.md')
    missing_routes = [item['path'] for item in urls
                      if '`{}`'.format(item['path']) not in route_text]

    modules = []
    for part in ('03_Module_Catalog_Part1.md', '03_Module_Catalog_Part2.md',
                 '03_Module_Catalog_Part3.md'):
        modules += re.findall(r'^## 模块 (\d+)：', read(part), re.M)
    expected_modules = {str(index) for index in range(1, 24)}
    missing_modules = sorted(expected_modules - set(modules), key=int)

    account_text = read('01_Account_Types_and_Workspaces.md')
    roles = ['system_admin', 'college_admin', 'teacher', 'student']
    identity_terms = ['辅导员', '班委', '团学干部', '社团负责人', '活动负责人',
                      '财务经办', '场地管理员', 'API 客户端', '无角色']
    missing_identity = [term for term in roles + identity_terms
                        if term not in account_text]

    matrix_text = read('02_Role_Permission_Matrix.md')
    matrix_terms = ['菜单可见性矩阵', '页面访问矩阵', '数据访问范围矩阵',
                    '字段级权限', '审批、发布、导入导出权限',
                    '超级管理员特权', '多角色组合与权限冲突',
                    '安全机制接入状态']
    missing_matrix = [term for term in matrix_terms if term not in matrix_text]

    workflow_text = read('06_Cross_Module_Workflows.md')
    workflows = re.findall(r'^## 流程 (\d+)：', workflow_text, re.M)
    missing_workflows = sorted({str(index) for index in range(1, 13)} - set(workflows),
                               key=int)

    files = [name for name in REQUIRED_FILES
             if not (AUDIT / name).exists()]

    checks = {
        'files': {'required': len(REQUIRED_FILES), 'missing': files},
        'models': {'expected': len(project_models),
                   'missing': missing_models[:20],
                   'missing_count': len(missing_models)},
        'routes': {'expected': len(urls), 'missing_count': len(missing_routes),
                   'missing': missing_routes[:20]},
        'modules': {'expected': 23, 'found': len(modules),
                    'missing': missing_modules},
        'identity': {'missing': missing_identity},
        'matrix': {'missing': missing_matrix},
        'workflows': {'expected': 12, 'found': len(workflows),
                      'missing': missing_workflows},
    }
    ok = (not files and not missing_models and not missing_routes
          and not missing_modules and not missing_identity
          and not missing_matrix and not missing_workflows)
    checks['ok'] = ok
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print('RESULT: {}'.format('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
