"""SMASS 项目包初始化。

MySQL 驱动适配说明：
- 优先使用编译好的 ``mysqlclient``（提供 ``MySQLdb``）；
- Windows 上从源码编译 mysqlclient 常因缺少 MSVC 工具链失败，因此当
  ``MySQLdb`` 不可用时，退化为用纯 Python 的 ``pymysql`` 顶替。

关于 ``version_info``：Django 5.2 的 MySQL backend 会断言
``Database.version_info >= (1, 4, 3)``，而 PyMySQL 上报的是自身的 (1, 1, 2)。
社区通行做法是把 ``version_info`` 声明为兼容值后再 ``install_as_MySQLdb()``，
PyMySQL 1.1.x 与 mysqlclient 1.4.x 在本项目用到的接口上是一致的。
"""
try:  # pragma: no cover - 依赖具体环境
    import MySQLdb  # noqa: F401
except ImportError:  # pragma: no cover
    try:
        import pymysql

        # 让 Django 的版本断言通过（PyMySQL 功能上满足要求）
        pymysql.version_info = (1, 4, 6, 'final', 0)
        pymysql.install_as_MySQLdb()
    except ImportError:
        # 交给 Django 在建立连接时给出明确报错
        pass
