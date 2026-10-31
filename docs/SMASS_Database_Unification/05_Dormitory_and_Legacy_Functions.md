# 05 住宿与旧功能覆盖

> 目的：说明住宿数据的迁移方式、旧库回退移除的影响，以及 app01 旧功能在
> 新系统中的覆盖状态。结论以源码与断库测试为依据。

---

## 1. 住宿数据

### 1.1 源数据实测

| 表 | 行数 | 说明 |
|---|---|---|
| `app01_building` | 0 | 空 |
| `app01_dormitory` | 0 | 空 |
| `app01_dormitorynumber` | 0 | 空 |
| `app01_student.building/dormitory` | 全部为空 | 3 名学生无住宿字段值 |

因此本轮迁移的 3 条学籍 **没有住宿数据**；对账结果 `source 0 / target 0`。

### 1.2 目标结构

当前权威源：`StudentRecord.extra.dormitory`：

```json
{
  "building": "紫荆公寓 3 号楼",
  "room": "312",
  "bed": "2 号床",
  "roommates": ["刘洋", "赵敏"]
}
```

- 产品学生端 `/student/dormitory/` 只读该字段；
- 管理端学籍详情只读该字段；
- 迁移脚本把 app01 的 `building/dormitory` 写入该结构（实测为空）。

### 1.3 旧库回退已移除

| 项 | 变更 |
|---|---|
| 位置 | `smass_workspace/services/student.py::dormitory_of` |
| 变更前 | 先读 `extra`，缺失时 `from app01.models import Student` 回退查询 |
| 变更后 | **只读 `extra`**，不再 import 或查询 app01 |
| 影响 | 产品库 app01 表本就为空，页面行为不变；运行时旧库依赖降为 0 |
| 验证 | `db_unify_dependency_scan.py` runtime=0；产品层 40 例 OK；断库测试 13 页全 200 |

### 1.4 住宿管理的缺口

- 没有楼栋/房间/床位台账的写入界面（旧表为空，产品未实现）；
- 没有调宿申请/审批；
- 室友列表依赖 `extra.roommates`，无成员关系校验。

### 1.5 建议的目标设计（本轮不实施）

```
DormitoryBuilding(code, name, campus, address)
DormitoryRoom(building, code, floor, capacity, gender_policy)
BedAssignment(student_record, bed, from_date, to_date, status)
```

- 与 `StudentRecord` 1:N（历史住宿）；
- 迁移时从 `extra.dormitory` 回填；
- 产品页改为查询 `BedAssignment`，extra 保留兼容。

---

## 2. app01 旧功能覆盖矩阵

> 状态取自 `docs/SMASS_System_Function_Audit/03_Module_Catalog_Part3.md`（M23）
> 与本轮依赖扫描。

| 旧功能 | 新系统覆盖 | 说明 |
|---|---|---|
| 管理员账号管理 | 部分 | 产品可创建/授权/停用/重置；旧 CRUD 页未挂载 |
| 学生档案管理 | 部分 | 学籍查看/编辑 + 导入；旧 CRUD 页未挂载 |
| 教师档案管理 | **未覆盖** | 只有 `TeacherProfile` 读取与迁移；无 CRUD |
| 学院/专业/班级 | 部分 | `OrganizationUnit` + R4 专业工具 |
| 年级 | 部分 | 组织单元展示；无独立管理 |
| 部门 | 部分 | 组织单元；无成员管理界面 |
| 班委/团学干部 | **未覆盖** | 迁移为 `Membership.role`；无管理界面与具体职务 |
| 楼栋/寝室台账 | **未覆盖** | 旧表为空；产品只读 `extra` |
| 民族/职务字典 | **未覆盖** | `app01_nation/position` 未迁移 |
| 教师职务关系 | **未解决** | `teacherposition` 语义不明，未迁移 |
| 旧三角色登录页 | 不适用 | 统一 `/login/` |
| 旧后台报表/导出 | 部分 | S25/R7 导出；旧页未挂载 |
| 旧 MD5 密码兼容 | 已处理 | 非 PBKDF2 设不可用+强制改密 |

---

## 3. 旧 URL / 模板 / 登录的处理

| 项 | 现状 |
|---|---|
| `/login/` | 产品统一入口；旧 `/login/account/*` 不在 `urls_product` |
| 旧 `templates/admin|student|teacher` | 未被产品 URL 引用；仅旧配置可用 |
| 旧 `urls_admin/urls_student/urls_teacher` | 不在 `urls_product` |
| 旧 settings | `smass.settings` 仍存在（默认），产品用 `settings_product`；见 08 的默认启动改造 |
| 旧会话 | 不迁移；新产品重新登录 |

---

## 4. 断库测试结论

`scripts/db_unify_detached_test.py` 在验证库重命名 16 张 app01 旧业务表后：

| 角色 | 页面 | 结果 |
|---|---|---|
| uni_student | 工作台/学籍/寝室/考勤/课表 | 200 |
| uni_teacher | 工作台/学生/考勤 | 200 |
| uni_admin | 总览/学籍/用户/组织/系统配置 | 200 |
| 登录 | 三角色 | 302 落地正确 |

失败 0。证明产品三端在旧表不可用时仍可完成已集成操作。
