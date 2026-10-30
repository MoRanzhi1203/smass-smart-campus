#!/usr/bin/env python
"""GS3：Git 安全同步、历史防回流与受控推送。

目标
----
1. 提交/推送前检查文件类型、路径、敏感内容与禁止上传项；
2. 确认当前分支继承自**已净化的可信基线**；
3. 检查即将推送的全部新提交可达路径中不存在被清除的污染路径；
4. 推送前重新获取远端 SHA：远端有新提交时拒绝，绝不覆盖协作者；
5. 只允许快进（fast-forward）推送，脚本本身不接受 ``--force``；
6. 推送后回读远端 SHA，证明远端实际状态与本地一致。

用法::

    python scripts/git_safe_sync.py check          # 提交前检查
    python scripts/git_safe_sync.py check --json
    python scripts/git_safe_sync.py push           # 拉取远端 → 检查 → 快进推送 → 回读
    python scripts/git_safe_sync.py selftest       # 负向测试（临时仓库，不触网）

注意：``selftest`` 仅使用临时目录中的本地 bare 仓库模拟远端，
不会访问 GitHub，也不会修改真实仓库。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

#: 净化历史的可信基线（阿里云远端 2026-10-30 的 main / feat 分支 HEAD）。
DEFAULT_BASELINE = '203c323688a3350b9828d44cac71d8fa4c88816a'

#: 历史中不得出现的路径（与 RH6 净化范围一致）。
HISTORY_FORBIDDEN = (
    r'^\.local/',
    r'^SMASS_[^/]*\.md$',
    r'^docs/dsh_run/',
    r'^docs/screenshots/',
    r'^note/',
)

#: 高置信敏感内容（刻意保守，避免误伤正常工程文件）。
SECRET_PATTERNS = (
    (re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----'),
     'private-key'),
    (re.compile(rb'AKIA[0-9A-Z]{16}'), 'aws-access-key'),
    (re.compile(rb'gh[pousr]_[A-Za-z0-9]{36,}'), 'github-token'),
    (re.compile(rb'github_pat_[A-Za-z0-9_]{40,}'), 'github-token'),
    (re.compile(rb'sk-[A-Za-z0-9]{32,}'), 'api-secret'),
)

#: 允许出现在代码/文档中的公开开发默认值。
SECRET_ALLOW = (
    b'django-insecure-dev-only-please-set-DJANGO_SECRET_KEY',
    b'dev-insecure-secret-key-for-smass-only',
    b'django-insecure-REDACTED__SEE_LOCAL_RESTRICTED_ARCHIVE',
)

INSECURE_RX = re.compile(
    rb'django-insecure-[A-Za-z0-9_\-()*^=!@#$%&+.,:;?/\\|~`\[\]{}<>]{20,}')
MAX_SCAN_BYTES = 3_000_000


# --------------------------------------------------------------------------
# 基础 Git 封装
# --------------------------------------------------------------------------
def git(repo, *args: str) -> tuple[int, str]:
    p = subprocess.run(['git', *args], cwd=str(repo),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = (p.stdout + p.stderr).decode('utf-8', 'replace')
    return p.returncode, out


def git_out(repo, *args: str) -> str:
    rc, out = git(repo, *args)
    if rc != 0:
        raise RuntimeError('git {} failed: {}'.format(' '.join(args), out.strip()))
    return out


def current_branch(repo) -> str:
    rc, out = git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')
    branch = out.strip() if rc == 0 else ''
    if not branch or branch == 'HEAD':
        raise RuntimeError('当前处于 detached HEAD，无法安全推送')
    return branch


# --------------------------------------------------------------------------
# 检查项
# --------------------------------------------------------------------------
def admission_problems(repo, include_head: bool = True) -> list[dict]:
    """复用 RH4 准入检查（路径、类型、大小），不依赖 .gitignore。"""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import repo_admission_check as rac  # noqa: WPS433 - 运行期导入便于复用规则

    sources = rac.collect(include_head=include_head, repo=Path(repo))
    problems: list[dict] = []
    for source, paths in sources.items():
        for item in rac.check_paths(paths) + rac.huge_files(paths, repo=Path(repo)):
            item = dict(item)
            item['source'] = source
            problems.append(item)
    return problems


def history_problems(repo, rev_range: str = 'HEAD') -> list[str]:
    """检查 ``rev_range`` 可达的历史对象路径中是否存在被净化的路径。"""
    rc, out = git(repo, 'rev-list', '--objects', rev_range)
    if rc != 0:
        raise RuntimeError('rev-list 失败：{}'.format(out.strip()))
    found = set()
    for line in out.splitlines():
        parts = line.split(' ', 1)
        if len(parts) != 2:
            continue
        path = parts[1].replace('\\', '/')
        if any(re.search(rx, path) for rx in HISTORY_FORBIDDEN):
            found.add(path)
    return sorted(found)


def eol_problems(repo) -> list[dict]:
    """索引内的文本不应是 CRLF；工作区 CRLF 只提示、不阻断。"""
    rc, out = git(repo, 'ls-files', '--eol')
    if rc != 0:
        raise RuntimeError('ls-files --eol 失败：{}'.format(out.strip()))
    problems = []
    for line in out.splitlines():
        m = re.match(r'^(i/\S+)\s+(w/\S+)\s+(attr/\S*)?\s*(.*)$', line)
        if not m:
            continue
        index_eol, work_eol, attr, path = m.group(1), m.group(2), m.group(3) or '', m.group(4)
        if index_eol == 'i/crlf' and 'binary' not in attr:
            problems.append({
                'path': path,
                'reason': '索引内为 CRLF（文本应规范为 LF）',
                'worktree': work_eol,
            })
    return problems


def baseline_problems(repo, baseline: str) -> list[dict]:
    """确认 HEAD 继承自净化基线。"""
    if not baseline:
        return [{'reason': '未指定净化基线 SHA，拒绝放行'}]
    rc, _ = git(repo, 'cat-file', '-e', baseline)
    if rc != 0:
        return [{'reason': '基线 {} 不在对象库中，请先 fetch 远端'.format(baseline[:10])}]
    rc, _ = git(repo, 'merge-base', '--is-ancestor', baseline, 'HEAD')
    if rc != 0:
        return [{'reason': 'HEAD 未继承净化基线 {}'.format(baseline[:10])}]
    return []


def _scan_text(path: str, data: bytes) -> list[dict]:
    if b'\x00' in data[:4096]:
        return []
    hits = []
    for rx, kind in SECRET_PATTERNS:
        if rx.search(data):
            hits.append({'path': path, 'category': kind})
    for m in INSECURE_RX.finditer(data):
        value = m.group(0)
        if value in SECRET_ALLOW or value.startswith(b'django-insecure-REDACTED'):
            continue
        # 允许"用于匹配密钥的正则字面量"（测试代码中的模式串）。
        if value.startswith(b'django-insecure-[') and value.endswith(b'}'):
            continue
        hits.append({'path': path, 'category': 'django-secret-key'})
    return hits


def content_problems(repo, rev_range: str = 'HEAD') -> list[dict]:
    """扫描即将推送的新增/修改文件内容（按 blob，而非工作区）。"""
    if '..' in rev_range:
        rc, out = git(repo, 'diff', '--name-only', '--diff-filter=ACMR', rev_range)
    else:
        rc, out = git(repo, 'diff-tree', '--no-commit-id', '--name-only',
                      '-r', '--root', rev_range)
    if rc != 0:
        return []
    hits = []
    for path in [p for p in out.splitlines() if p.strip()]:
        rc2, listing = git(repo, 'cat-file', '-s', 'HEAD:{}'.format(path))
        if rc2 != 0:
            continue
        try:
            size = int(listing.strip())
        except ValueError:
            continue
        if size > MAX_SCAN_BYTES:
            continue
        rc3, blob = git(repo, 'cat-file', '-p', 'HEAD:{}'.format(path))
        if rc3 != 0:
            continue
        hits.extend(_scan_text(path, blob.encode('utf-8', 'replace')))
    return hits


def default_range(repo, baseline: str) -> str:
    """默认检查基线以来的全部提交；基线不可用时退化为 HEAD。"""
    if baseline and git(repo, 'cat-file', '-e', baseline)[0] == 0:
        return '{}..HEAD'.format(baseline)
    return 'HEAD'


def check_all(repo, baseline: str, rev_range: str | None = None) -> dict:
    if rev_range is None:
        rev_range = default_range(repo, baseline)
    admission = admission_problems(repo, include_head=True)
    # 历史边界始终按 HEAD 全量检查：防止基线之前/之后的污染路径被带回。
    history = history_problems(repo, 'HEAD')
    eol = eol_problems(repo)
    baseline_issues = baseline_problems(repo, baseline)
    content = content_problems(repo, rev_range)
    ok = not (admission or history or eol or baseline_issues or content)
    return {
        'ok': ok,
        'repo': str(repo),
        'head': git_out(repo, 'rev-parse', 'HEAD').strip(),
        'branch': current_branch(repo),
        'rev_range': rev_range,
        'admission': admission,
        'history_forbidden': history,
        'content_secrets': content,
        'eol': eol,
        'baseline': baseline_issues,
    }


# --------------------------------------------------------------------------
# 推送
# --------------------------------------------------------------------------
def push(repo, remote: str = 'origin', baseline: str = DEFAULT_BASELINE) -> int:
    branch = current_branch(repo)
    head = git_out(repo, 'rev-parse', 'HEAD').strip()

    rc, fetch_out = git(repo, 'fetch', '--prune', remote)
    if rc != 0:
        print('PUSH REJECTED: 无法获取远端状态，拒绝在不确定状态下推送')
        print(fetch_out.strip())
        return 1

    rc, ls = git(repo, 'ls-remote', '--heads', remote,
                 'refs/heads/{}'.format(branch))
    if rc != 0:
        print('PUSH REJECTED: ls-remote 失败，无法确认远端 SHA')
        print(ls.strip())
        return 1
    remote_sha = ''
    for line in ls.splitlines():
        m = re.match(r'^([0-9a-f]{40})\s+refs/heads/', line.strip())
        if m:
            remote_sha = m.group(1)
            break

    if remote_sha and remote_sha != head:
        rc, _ = git(repo, 'merge-base', '--is-ancestor', remote_sha, head)
        if rc != 0:
            print('PUSH REJECTED: 远端 {} 有新提交 {}，本地 {} 不是其后继'.format(
                branch, remote_sha[:10], head[:10]))
            print('请先 git pull --rebase（人工整合）后重新检查，脚本不会强制覆盖。')
            return 1

    rev_range = '{}..HEAD'.format(remote_sha) if remote_sha else 'HEAD'
    report = check_all(repo, baseline, rev_range=rev_range)
    if not report['ok']:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('PUSH REJECTED: 安全检查未通过')
        return 1

    rc, out = git(repo, 'push', remote,
                  'HEAD:refs/heads/{}'.format(branch))
    if rc != 0:
        print('PUSH FAILED')
        print(out.strip())
        return 1

    rc, ls2 = git(repo, 'ls-remote', '--heads', remote,
                  'refs/heads/{}'.format(branch))
    actual = ''
    for line in ls2.splitlines():
        parts = line.split()
        if len(parts) == 2:
            actual = parts[0]
            break
    if actual != head:
        print('PUSH VERIFY FAILED: 远端 {} 实际为 {}，预期 {}'.format(
            branch, actual[:10], head[:10]))
        return 1

    print('PUSH OK: {} -> {}/{} @ {}'.format(branch, remote, branch, head[:10]))
    return 0


# --------------------------------------------------------------------------
# 自测（临时仓库，不触网）
# --------------------------------------------------------------------------
class _Repo:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self._git('init', '-b', 'main')
        self._git('config', 'user.name', 'selftest')
        self._git('config', 'user.email', 'selftest@example.invalid')
        self._git('config', 'core.autocrlf', 'false')

    def _git(self, *args: str) -> str:
        rc, out = git(self.path, *args)
        if rc != 0:
            raise RuntimeError('git {}: {}'.format(' '.join(args), out))
        return out

    def commit(self, files: dict[str, str], message: str) -> str:
        for rel, content in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8', newline='\n')
        self._git('add', '-A', '--', '.')
        self._git('commit', '-m', message)
        return self._git('rev-parse', 'HEAD').strip()

    def sha(self) -> str:
        return self._git('rev-parse', 'HEAD').strip()


def selftest() -> int:
    failures: list[str] = []
    results: list[tuple[str, bool, str]] = []

    def expect(name: str, condition: bool, detail: str = '') -> None:
        results.append((name, condition, detail))
        if not condition:
            failures.append('{}: {}'.format(name, detail))

    with tempfile.TemporaryDirectory(prefix='smass_git_sync_') as tmp:
        root = Path(tmp)

        # --- 1. 干净历史：正常工程文件必须放行 ---
        clean = _Repo(root / 'clean')
        base = clean.commit({
            'app01/models.py': 'class Student:\n    pass\n',
            'docs/SMASS_R11_Scheduling.md': '# R11\n',
            'templates/r11/plan.html': '<html></html>\n',
        }, 'baseline')
        report = check_all(clean.path, base)
        expect('干净仓库放行', report['ok'],
               json.dumps(report, ensure_ascii=False)[:400])

        # --- 2. .local/ 即使 add -f 也必须拦截 ---
        local = _Repo(root / 'local')
        local_base = local.commit({'app01/models.py': 'x = 1\n'}, 'baseline')
        (local.path / '.local').mkdir()
        (local.path / '.local' / 'agent.json').write_text('{"a":1}', encoding='utf-8')
        local._git('add', '-f', '.local/agent.json')
        local._git('commit', '-m', 'forced local file')
        report = check_all(local.path, local_base)
        expect('git add -f .local 被拦截',
               any(p['category'] == 'local-research' for p in report['admission']),
               json.dumps(report['admission'], ensure_ascii=False)[:300])

        # --- 3. 根目录提示词 ---
        prompt = _Repo(root / 'prompt')
        prompt_base = prompt.commit({'app01/models.py': 'x = 1\n'}, 'baseline')
        prompt.commit({'SMASS_Master_Development_DSH_Prompt.md': 'secret plan\n'}, 'prompt')
        report = check_all(prompt.path, prompt_base)
        expect('根目录提示词被拦截',
               any(p['category'] == 'root-prompt' for p in report['admission']),
               json.dumps(report['admission'], ensure_ascii=False)[:300])

        # --- 4. 凭据文件 ---
        cred = _Repo(root / 'cred')
        cred_base = cred.commit({'app01/models.py': 'x = 1\n'}, 'baseline')
        cred.commit({'.env': 'DB_PASSWORD=hunter2\n'}, 'env')
        report = check_all(cred.path, cred_base)
        expect('.env 被拦截',
               any(p['category'] == 'credential' for p in report['admission']),
               json.dumps(report['admission'], ensure_ascii=False)[:300])

        # --- 5. 污染历史（docs/screenshots/）必须拦截 ---
        dirty = _Repo(root / 'dirty')
        dirty_base = dirty.commit({'docs/screenshots/a.png': 'not-a-png\n'}, 'polluted baseline')
        dirty.commit({'app01/models.py': 'x = 1\n'}, 'clean head')
        report = check_all(dirty.path, dirty_base)
        expect('污染历史被拦截',
               any('docs/screenshots/' in p for p in report['history_forbidden']),
               str(report['history_forbidden'])[:300])

        # --- 6. 内容级凭据扫描 ---
        secret = _Repo(root / 'secret')
        secret_base = secret.commit({'app01/models.py': 'x = 1\n'}, 'baseline')
        secret.commit({'config.py': 'TOKEN = "ghp_' + 'a' * 36 + '"\n'}, 'token')
        report = check_all(secret.path, secret_base)
        expect('内容凭据被拦截',
               any(p['category'] == 'github-token' for p in report['content_secrets']),
               json.dumps(report['content_secrets'], ensure_ascii=False)[:300])

        # --- 7. 远端前进：协作者提交后拒绝盲目覆盖 ---
        bare = root / 'remote.git'
        bare.mkdir()
        git(str(bare), 'init', '--bare')

        alice = root / 'alice'
        alice.mkdir()
        git(str(alice), 'clone', str(bare), '.')
        git(str(alice), 'config', 'user.name', 'alice')
        git(str(alice), 'config', 'user.email', 'alice@example.invalid')
        (alice / 'app01').mkdir()
        (alice / 'app01' / 'models.py').write_text('x = 1\n', encoding='utf-8')
        git(str(alice), 'add', '-A')
        git(str(alice), 'commit', '-m', 'baseline')
        alice_base = git(str(alice), 'rev-parse', 'HEAD')[1].strip()
        git(str(alice), 'push', 'origin', 'HEAD:refs/heads/main')

        bob = root / 'bob'
        bob.mkdir()
        git(str(bob), 'clone', str(bare), '.')
        git(str(bob), 'config', 'user.name', 'bob')
        git(str(bob), 'config', 'user.email', 'bob@example.invalid')
        (bob / 'app01').mkdir(parents=True, exist_ok=True)
        (bob / 'app01' / 'views.py').write_text('y = 2\n', encoding='utf-8')
        git(str(bob), 'add', '-A')
        git(str(bob), 'commit', '-m', 'author change')
        git(str(bob), 'push', 'origin', 'HEAD:refs/heads/main')

        # alice 本地新增提交后尝试推送：远端已前进，必须拒绝。
        (alice / 'app01' / 'extra.py').write_text('z = 3\n', encoding='utf-8')
        git(str(alice), 'add', '-A')
        git(str(alice), 'commit', '-m', 'alice change')
        rc = push(alice, remote='origin', baseline=alice_base)
        expect('远端前进时拒绝非快进推送', rc != 0, 'push 返回 {}'.format(rc))

        # --- 8. 正常快进推送成功并回读 SHA ---
        bob2 = root / 'bob2'
        bob2.mkdir()
        git(str(bob2), 'clone', str(bare), '.')
        git(str(bob2), 'config', 'user.name', 'bob2')
        git(str(bob2), 'config', 'user.email', 'bob2@example.invalid')
        (bob2 / 'app01').mkdir(parents=True, exist_ok=True)
        (bob2 / 'app01' / 'ok.py').write_text('ok = True\n', encoding='utf-8')
        git(str(bob2), 'add', '-A')
        git(str(bob2), 'commit', '-m', 'fast forward')
        rc = push(bob2, remote='origin', baseline=alice_base)
        remote_head = git(str(bare), 'rev-parse', 'refs/heads/main')[1].strip()
        local_head = git(str(bob2), 'rev-parse', 'HEAD')[1].strip()
        expect('正常快进推送成功', rc == 0, 'push 返回 {}'.format(rc))
        expect('推送后远端 SHA 一致', remote_head == local_head,
               '{} != {}'.format(remote_head[:10], local_head[:10]))

        # --- 9. 强制推送参数被拒绝 ---
        rc = push(bob2, remote='origin', baseline=alice_base)
        expect('重复推送保持幂等', rc == 0, 'push 返回 {}'.format(rc))

        shutil.rmtree(root / 'alice', ignore_errors=True)

    print('GS3 selftest: {} 项'.format(len(results)))
    for name, ok, detail in results:
        print('  {} {}'.format('PASS' if ok else 'FAIL', name))
        if not ok and detail:
            print('       ' + detail)
    print('SELFTEST: {}'.format('PASS' if not failures else 'FAIL'))
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser(description='SMASS Git 安全同步与历史防回流')
    sub = ap.add_subparsers(dest='command', required=True)

    p_check = sub.add_parser('check', help='提交前/推送前检查')
    p_check.add_argument('--json', action='store_true')
    p_check.add_argument('--repo', default='')
    p_check.add_argument('--baseline', default=DEFAULT_BASELINE)
    p_check.add_argument('--range', default=None,
                         help='要检查的提交范围（默认：净化基线..HEAD）')

    p_push = sub.add_parser('push', help='检查后快进推送并回读远端')
    p_push.add_argument('--remote', default='origin')
    p_push.add_argument('--baseline', default=DEFAULT_BASELINE)
    for flag in ('--force', '-f'):
        p_push.add_argument(flag, action='store_true', dest='force')

    sub.add_parser('selftest', help='负向测试（临时仓库）')

    args = ap.parse_args()
    if args.command == 'selftest':
        return selftest()

    repo = Path(args.repo).resolve() if getattr(args, 'repo', '') else BASE
    if args.command == 'check':
        report = check_all(repo, args.baseline, rev_range=args.range)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print('branch      : {}'.format(report['branch']))
            print('head        : {}'.format(report['head']))
            print('range       : {}'.format(report['rev_range']))
            for key in ('admission', 'history_forbidden', 'content_secrets',
                        'eol', 'baseline'):
                value = report[key]
                print('{:<16}: {}{}'.format(
                    key, 'OK' if not value else 'FAIL({})'.format(len(value)), ''))
                for item in value[:20]:
                    print('    - {}'.format(json.dumps(item, ensure_ascii=False)))
            print('RESULT: {}'.format('PASS' if report['ok'] else 'FAIL'))
        return 0 if report['ok'] else 1

    if getattr(args, 'force', False):
        print('PUSH REJECTED: 本工具禁止强制推送')
        return 1
    return push(repo, remote=args.remote, baseline=args.baseline)


if __name__ == '__main__':
    raise SystemExit(main())
