# SMASS — 校园服务与管理系统

基于 **Django + MySQL** 的校园基础信息管理系统，提供管理员后台（人员/组织/职务 CRUD、Excel 批量导入）、
学生个人主页与本班通讯录、教师信息页。

> 本项目由早期 Django 3.2 模板起步，现运行于 **Django 5.2 / Python 3.12 / MySQL 8**。
> 认证、密码、权限、CSRF 与数据导入链路已于 2026-10 完成一轮集中修复，详见
> [`docs/SMASS_Change_Log.md`](docs/SMASS_Change_Log.md) 与 [`docs/SMASS_Security_Report.md`](docs/SMASS_Security_Report.md)。

---

## 1. 技术栈

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12 | 推荐用 Conda 独立环境 |
| Django | 5.2.13 | 单体架构，无前后端分离 |
| MySQL | 8.0 | 默认库名 `smass` |
| 驱动 | PyMySQL（默认）/ mysqlclient | 见 `smass/__init__.py` 的适配逻辑 |
| 前端 | Bootstrap 3（后台）+ Bootstrap 5 / NiceAdmin（学生端） | UI 统一留待 R2 |
| Excel | openpyxl | 批量导入 / 模版下载 |

---

## 2. 目录结构

```
smass/
├── manage.py
├── requirements.txt / environment.yml / .env.example
├── smass/                     # 项目配置
│   ├── settings.py            # 全部配置走环境变量
│   ├── env_loader.py          # 极简 .env 读取（无第三方依赖）
│   ├── urls.py                # URL 总入口
│   ├── urls_account.py        # 登录/登出
│   ├── urls_admin.py          # 后台（命名路由）
│   ├── urls_student.py / urls_teacher.py
├── app01/
│   ├── models.py              # 领域模型（不含任何密码哈希逻辑）
│   ├── form/                  # 登录表单 / 后台 ModelForm
│   ├── views/                 # account / admin(9 模块) / student / teacher
│   ├── services/              # 账户、CRUD、导入服务层
│   ├── middleware/auth.py     # 角色准入（粗粒度）
│   ├── utils/                 # 权限装饰器、分页、bootstrap 样式、加密兼容
│   ├── management/commands/seed_dev.py
│   └── tests/                 # 79 个自动化测试
├── templates/                 # layout / admin / login / student / teacher
├── static/                    # 第三方前端资源
├── scripts/                   # check.ps1（质量门禁）、db_inspect.py
└── docs/                      # 审计、变更、测试、迁移、安全、R2 设计
```

---

## 3. 快速开始（Windows + Conda）

### 3.1 创建环境

```powershell
conda env create -f environment.yml
conda activate smass
# 或直接用 pip：
#   python -m pip install -r requirements.txt
```

> ⚠️ **不要用** PATH 里的 `python`：Windows 上它常是 Microsoft Store 的占位符，
> 运行会静默失败。请使用 `conda run -n smass python ...` 或激活环境后的 `python`。

### 3.2 配置

```powershell
Copy-Item .env.example .env
# 然后编辑 .env：至少填写 DB_PASSWORD；生产环境还要设置 DJANGO_SECRET_KEY 与 DJANGO_DEBUG=False
```

可用变量（完整清单见 `.env.example`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DJANGO_DEBUG` | `True` | 生产必须为 `False` |
| `DJANGO_SECRET_KEY` | 开发占位值 | `DEBUG=False` 时**必须**提供，否则启动报错 |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | 逗号分隔 |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` | `smass/root//localhost/3306` | MySQL 连接 |
| `DB_TEST_NAME` | `test_smass` | 测试库名 |
| `DJANGO_SESSION_COOKIE_AGE` | `86400` | 会话有效期（秒） |

### 3.3 建库

```sql
CREATE DATABASE smass DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

> 库/表字符集建议 `utf8mb4`。历史库若为 `utf8`，中文可用但不支持 emoji，迁移建议见
> `docs/SMASS_Migration_Report.md`。

### 3.4 迁移

```powershell
conda run -n smass python manage.py migrate
```

### 3.5 初始化开发数据（幂等）

```powershell
conda run -n smass python manage.py seed_dev
```

该命令会创建学院/专业/年级/班级/教师/学生/管理员/部门等最小数据集，
**只在 `DEBUG=True` 时允许执行**，重复运行不会产生重复数据，也不会覆盖已有密码。
新建账号的随机初始密码会在标准输出中**只显示一次**，请立即记录。

### 3.6 启动

```powershell
conda run -n smass python manage.py runserver 127.0.0.1:8000
```

入口：

| 角色 | 地址 |
|---|---|
| 角色选择 | <http://127.0.0.1:8000/login/> |
| 管理员 | <http://127.0.0.1:8000/login/account/admin/> |
| 学生 | <http://127.0.0.1:8000/login/account/student/> |
| 教师 | <http://127.0.0.1:8000/login/account/teacher/> |

---

## 4. 测试与质量门禁

```powershell
# 全量测试（会创建并销毁 MySQL 测试库 test_smass）
conda run -n smass python manage.py test app01 -v 1

# 一键门禁：check + 迁移一致性 + 测试 + 部署审计
pwsh -File scripts\check.ps1
```

数据库状态巡检（只读，不输出密码）：

```powershell
conda run -n smass python scripts\db_inspect.py
```

---

## 5. 常见问题

**Q: `python` 命令没有任何输出/直接打开商店？**
用 `conda run -n smass python ...`，或激活环境后再执行。

**Q: 报 `mysqlclient 1.4.3 or newer is required`？**
`smass/__init__.py` 已优先使用 `MySQLdb`，缺失时用 PyMySQL 并声明兼容的
`version_info`。若仍报错，确认 `PyMySQL` 已安装且 `smass` 包被实际导入（即 `DJANGO_SETTINGS_MODULE=smass.settings`）。

**Q: 中文乱码或分页/导入报编码错误？**
检查库与表字符集是否为 `utf8mb4`，并确认 `.env` 未被覆盖。

**Q: 登录提示"账号或密码错误"，但我确定密码对？**
密码统一走 Django 哈希。若账号是历史数据（旧 MD5），首次登录会被自动升级；
若账号是从旧版本导入的明文/双重哈希数据，也会在首次正确登录时修复。
都不行则让管理员用"重置密码"生成一次性口令（页面只显示一次）。

**Q: 忘记管理员密码？**
```powershell
conda run -n smass python manage.py shell -c "from app01 import models; from app01.services import accounts; a=models.Admin.objects.first(); print(a.pk, accounts.reset_password(a))"
```
输出的一次性密码只显示一次，登录后请立即修改。

---

## 6. 安全约定（开发时请遵守）

1. 密码只经 `app01.services.accounts` 写入，模型 `save()` 不再做任何哈希。
2. 新增后台接口必须带 `@admin_required` 与 `@require_POST`（写操作）。
3. 搜索字段必须在视图里显式声明 `SEARCH_FIELDS`，不得拼接用户输入为 ORM 字段名。
4. 批量导入必须先校验再入库，禁止静默半成功。
5. 日志（`logs/smass.log`）只记录操作者标识、事件、对象类型/主键，不记录密码、哈希、完整身份证号。

---

## 7. R2.1 统一账号原型（隔离，不切换正式路径）

```powershell
# 迁移与运行（仅 smass_r21_proto）
conda run -n smass python manage.py migrate --settings=smass.settings_r21
conda run -n smass python manage.py test r21_account --settings=smass.settings_r21
conda run -n smass python manage.py verify_account_consistency --strict-count --settings=smass.settings_r21

# 浏览器（三端强制改密）
conda run -n smass python manage.py test r21_account.tests.test_browser_r21 --settings=smass.settings_r21
```

- 数据库白名单：写入仅 `smass_r21_*`；`smass` 只读；`smass_proto_*` 保留。
- **正式认证路径未切换**，`AUTH_USER_MODEL` 未改，旧表未删。
- 详见 `docs/SMASS_R21_*.md`。