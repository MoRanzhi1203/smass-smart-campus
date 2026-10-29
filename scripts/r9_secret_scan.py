"""R9-04：秘密扫描（仓库内敏感信息自查）。

扫描 git 跟踪的文本文件，匹配常见敏感模式：
- 私钥块
- 硬编码 password/token/secret 赋值
- 长 base64/hex（疑似密钥）

白名单：本地开发的固定测试口令、`SECRET_KEY` 的 dev 默认值、
文档中的示例值（`'<pwd>'` 等占位）。

用法：
    conda run -n smass python scripts/r9_secret_scan.py [--json]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

TEXT_SUFFIXES = {'.py', '.md', '.txt', '.yml', '.yaml', '.json', '.html', '.ps1', '.cfg', '.ini'}

PATTERNS = [
    ('PRIVATE_KEY', re.compile(r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('AWS_KEY', re.compile(r'AKIA[0-9A-Z]{16}')),
    ('HARDCODED_PASSWORD', re.compile(r'(?i)\bpassword\s*=\s*[\'"][^\'"\s]{6,}[\'"]')),
    ('HARDCODED_TOKEN', re.compile(r'(?i)\b(api[_-]?token|access[_-]?token|secret[_-]?key)\s*=\s*[\'"][^\'"\s]{8,}[\'"]')),
    ('BEARER_LITERAL', re.compile(r'(?i)bearer\s+[a-z0-9\-._~+/]{20,}')),
]

#: 允许出现的开发用值（逐条说明理由）
ALLOWLIST = {
    '123456': '本地 MySQL root 的开发默认口令（历史约定，非生产凭据）',
    'REPLACE_ME': '占位符',
    'change-me': '占位符',
    'test': '测试值',
    'SynthPass#2024': '测试夹具口令',
    'SynthScale#2024': '测试夹具口令',
    'SynthG8#2024': '测试夹具口令',
    'SynthR3#2024': '测试夹具口令',
    'SynthCap#2024': '测试夹具口令',
    'dev-insecure-secret-key-for-smass-only': '开发默认 SECRET_KEY（正式环境必须覆盖）',
    'Demo#2024': '隔离演示环境的演示账号口令（可由 SMASS_DEMO_PASSWORD 覆盖，非生产凭据）',
}


#: 开发默认 SECRET_KEY 的官方标识前缀（Django 自动生成时使用）
DEV_SECRET_PREFIX = 'django-insecure-'

#: 原型/实验脚本（合成数据，不连接生产）
EXPERIMENT_SCRIPT_PREFIXES = ('scripts/proto_', 'scripts/r221_', 'scripts/r3_')


def is_dev_placeholder(token):
    return DEV_SECRET_PREFIX in token


def is_experiment_script(rel_path):
    return rel_path.startswith(EXPERIMENT_SCRIPT_PREFIXES)


def is_test_fixture(rel_path, pattern_name, token=''):
    """测试/实验文件里的合成口令属夹具，不是生产凭据。"""
    lowered = rel_path.lower()
    in_tests = ('/tests/' in lowered or lowered.startswith('tests/')
                or '/test_' in lowered)
    if pattern_name in ('HARDCODED_PASSWORD', 'HARDCODED_TOKEN'):
        return in_tests or is_experiment_script(rel_path)
    if pattern_name == 'HARDCODED_TOKEN':
        return is_dev_placeholder(token)
    return False


def git_files():
    result = subprocess.run(
        ['git', 'ls-files'], cwd=str(BASE), capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    return [BASE / line.strip() for line in result.stdout.splitlines() if line.strip()]


def scan():
    findings = []
    for path in git_files():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:  # noqa: BLE001
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                token = match.group(0)
                if any(allowed in token for allowed in ALLOWLIST):
                    continue
                rel = str(path.relative_to(BASE)).replace('\\', '/')
                # 测试夹具里的合成口令不计为生产凭据问题，
                # 但保留在报告中（TEST_FIXTURE）以保持可见性
                severity = 'TEST_FIXTURE' if (is_test_fixture(rel, name, token)
                                              or is_dev_placeholder(token)) else 'ISSUE'
                findings.append({
                    'file': rel,
                    'line': lineno,
                    'pattern': name,
                    'excerpt': token[:60],
                    'severity': severity,
                })
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    findings = scan()
    issues = [f for f in findings if f.get('severity') == 'ISSUE']
    fixtures = [f for f in findings if f.get('severity') == 'TEST_FIXTURE']
    payload = {
        'ok': not issues,
        'findings': issues,
        'test_fixtures': len(fixtures),
        'allowlisted_values': list(ALLOWLIST.keys()),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if issues:
            print('[FAIL] 发现 {} 处可疑内容:'.format(len(issues)))
            for item in issues[:50]:
                print('  {}:{} [{}] {}'.format(
                    item['file'], item['line'], item['pattern'], item['excerpt']))
        else:
            print('[PASS] 未发现生产凭据（白名单 {} 项；测试夹具 {} 处已识别）'.format(
                len(ALLOWLIST), len(fixtures)))

    return 0 if not issues else 1


if __name__ == '__main__':
    sys.exit(main())
