# 08 数据库配置与站点切换

> 本章记录 V2.2 从“三库并行”到“唯一业务库”的配置切换与实际运行结果。

---

## 1. 统一配置

```python
# smass/settings_campus.py
CAMPUS_DB_NAME = os.environ.get('CAMPUS_DB', 'smass_campus')
if CAMPUS_DB_NAME != 'smass_campus':
    raise RuntimeError('校园业务库名必须为 smass_campus ...')
DATABASES['default']['NAME'] = CAMPUS_DB_NAME
DATABASES['default']['TEST']['NAME'] = 'test_smass_campus'
INSTALLED_APPS += ['smass_simulation']   # 仅用于批次索引，不改变业务权威
ROOT_URLCONF = 'smass.urls_product'
MFA_ENABLED = os.environ.get('SMASS_MFA_ENABLED', '0') == '1'
```

- 继承 `settings_product`：完整业务 app、三端路由、模板与安全语义；
- 库名**硬校验**：只允许 `smass_campus`，写错直接启动失败；
- 不连接 `smass_product_dev` / `smass_simulation` / `smass_unified_verify`。

## 2. 默认启动入口

`manage.py` 默认 `DJANGO_SETTINGS_MODULE = smass.settings_campus`：

```powershell
cd E:\PythonWeb\smass\.local\clean-dev
& "C:\Users\MSIPC\.conda\envs\smass\python.exe" manage.py runserver 127.0.0.1:8050 --noreload
```

旧配置保留为代码档案，需显式指定才会使用（不会再被默认启动连上）：

```powershell
python manage.py runserver --settings=smass.settings_product      # 旧产品库（退役中）
python manage.py runserver --settings=smass.settings_simulation   # 旧仿真库（退役中）
```

## 3. 实际切换记录

| 步骤 | 结果 |
|---|---|
| 停止旧服务 | 原 8050 为 `--settings=smass.settings_simulation`（仿真库） |
| 切换配置 | `manage.py` 默认改为 `settings_campus` |
| 启动新服务 | 命令见上；PID **44592**（实测 `Get-NetTCPConnection` 确认） |
| 连接核验 | `connection.settings_dict['NAME'] == 'smass_campus'` |
| 数据规模 | 16800 学籍 / 17985 账号（含 `dev_admin`） |

## 4. 六类角色登录验证（实测）

| 角色 | 账号 | 登录 | 落地 | 首页 |
|---|---|---|---|---|
| 学生 | `sim_stu_S202300001` | 302 | `/student/` | 200 |
| 教师 | `sim_tea_T000001` | 302 | `/teacher/` | 200 |
| 辅导员 | `sim_tea_T001118`（counselor 成员） | 302 | `/teacher/` | 200 |
| 学院管理员 | `sim_adm_01_admin` | 302 | `/admin/` | 200 |
| 宿管 | `sim_dorm_m01` | 302 | `/admin/` | 200 |
| 超级管理员 | `dev_admin` | 302 | `/admin/` | 200 |

口令：仿真账号为 `SIMULATION_PASSWORD`（未设置时的生成器默认值）；`dev_admin` 沿用产品库原口令。

## 5. 仍待更新的入口（下一轮）

- `.env.example`、`README`、部署/启动脚本、E2E 脚本；
- `scripts/perf_simulation.py` 等仍显式使用 `settings_simulation`（应改为 `settings_campus`）；
- `DSH_RESUME.md`、`SMART_CAMPUS_MASTER_LEDGER.md` 已同步更新。
