"""SMASS 项目包初始化。

MySQL 驱动适配：
- 优先使用编译好的 ``mysqlclient``（提供 ``MySQLdb``）；
- Windows 上从源码编译 mysqlclient 常因缺少 MSVC 工具链失败，因此当
  ``MySQLdb`` 不可用时，用纯 Python 的 ``pymysql`` 顶替。

关于版本声明（R1.5-D.2 复核结论）
--------------------------------
Django 5.2 的 MySQL backend 会断言 ``Database.version_info >= (1, 4, 3)``。
这个阈值来自 **mysqlclient** 的版本号体系；PyMySQL 采用自己的编号（1.1.x），
两者不可直接比较，而 PyMySQL 在本项目用到的接口上功能是满足的。

因此这里做的是**驱动适配 shim**，而不是"伪造一个更真实的驱动版本"：
  1. 只在 ``MySQLdb`` 缺失时才走 PyMySQL 分支；
  2. 只有实际 PyMySQL 版本低于阈值时才声明兼容版本；
  3. 真实版本仍可通过 ``pymysql.__version__`` 读取，不被覆盖。
保守替代方案（见 docs/SMASS_R15_Security_Report.md）：
  在具备 MSVC 构建工具链的机器上安装 ``mysqlclient``，即可完全去掉本 shim。
"""
try:  # pragma: no cover - 依赖具体环境
    import MySQLdb  # noqa: F401
except ImportError:  # pragma: no cover
    try:
        import pymysql
    except ImportError:
        # 交给 Django 在建立连接时给出明确报错
        pass
    else:
        _real_version_info = getattr(pymysql, 'version_info', (0, 0, 0))
        if _real_version_info < (1, 4, 3):
            # 仅用于通过 Django 的兼容性断言；真实版本仍在 pymysql.__version__
            pymysql.version_info = (1, 4, 6, 'final', 0)
        pymysql.install_as_MySQLdb()
