"""极简 .env 加载器。

设计目标：
- 不引入额外第三方依赖（避免 python-dotenv 安装失败导致项目不可启动）；
- 只做 "KEY=VALUE" 这一种最小语法，支持 # 注释与成对引号；
- 使用 ``os.environ.setdefault``，**不覆盖**已在进程环境中显式设置的变量，
  这样 CI/生产可以直接用环境变量而非文件。

注意：本模块只负责读取本地开发配置，不会、也不应该把内容写日志。
"""
import os
from pathlib import Path


def load_env(env_path):
    """从 *env_path* 读取键值对注入 ``os.environ``（已存在的键保持不变）。"""
    path = Path(env_path)
    if not path.is_file():
        return

    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        # 读不到就不注入：让后续显式环境变量或默认值生效
        return

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        if '=' not in line:
            continue

        key, _, value = line.partition('=')
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)
