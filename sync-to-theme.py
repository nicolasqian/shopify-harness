#!/usr/bin/env python3
"""安装或更新 Shopify 主题的共享代理规则和工具。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
STATE = ".tmp/shopify-harness-sync.json"
TEAM_STATE = ".agents/shopify-harness.lock.json"


def checked_path(base, name):
    relative = Path(name)
    if relative.is_absolute() or relative.as_posix() != name or any(
        part in ("..", ".git") for part in relative.parts
    ) or not relative.parts:
        raise ValueError(f"无效路径 {name}")
    path = base / relative
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError(f"路径不是普通文件或经过符号链接 {path}")
    for parent in path.parents:
        if parent == base:
            break
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"目标目录被普通文件占用 {parent}")
    return path


def fingerprint(path):
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest + ("+x" if path.stat().st_mode & 0o111 else "")


def write_atomic(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
    try:
        temp.write_bytes(data)
        temp.chmod(mode)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def sources_for(profile):
    manifests = [ROOT / "manifest.txt"]
    if profile == "ecoflow":
        manifests.append(ROOT / "profiles/ecoflow/manifest.txt")
    sources = {}
    for manifest in manifests:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            dest, separator, source = line.partition(" => ")
            if dest in sources or dest in (STATE, TEAM_STATE):
                raise ValueError(f"清单包含重复或保留路径 {dest}")
            sources[dest] = checked_path(ROOT, source if separator else dest)
    if not sources:
        raise ValueError("文件清单为空")
    return sources


def git_names(theme, *args):
    output = subprocess.check_output(["git", "-C", str(theme), *args])
    return {os.fsdecode(name) for name in output.split(b"\0") if name}


def sync(theme, dry_run, profile):
    local = profile == "ecoflow"
    state_name = STATE if local else TEAM_STATE
    other_state = TEAM_STATE if local else STATE
    if (theme / other_state).is_file():
        raise ValueError(f"此主题已有另一种安装模式的基线 {other_state}，请沿用原模式")
    state = checked_path(theme, state_name)
    previous = json.loads(state.read_text()) if state.exists() else {}
    if not isinstance(previous, dict) or not all(isinstance(v, str) for v in previous.values()):
        raise ValueError(f"同步记录格式异常 {state}")
    sources = sources_for(profile)
    if local:
        # check-ignore 同时排除已跟踪文件，沿用 EcoFlow 各分支的忽略范围。
        ignored = subprocess.run(
            ["git", "-C", str(theme), "check-ignore", "-z", "--stdin"],
            input=b"".join(os.fsencode(p) + b"\0" for p in [*sources, state_name]), capture_output=True,
        )
        if ignored.returncode not in (0, 1):
            raise ValueError(ignored.stderr.decode())
        safe = set(ignored.stdout.decode().split("\0"))
    else:
        deleted = git_names(theme, "ls-files", "--deleted", "-z")
        deleted.update(git_names(theme, "diff", "--cached", "--no-renames", "--diff-filter=D", "--name-only", "-z"))
        if state_name in deleted:
            raise ValueError(f"团队同步基线已被删除，请先核对 {state_name}")
    pending, conflicts, current = [], [], {}
    for name, src in sources.items():
        dst = checked_path(theme, name)
        desired, actual = fingerprint(src), fingerprint(dst)
        if desired is None:
            raise ValueError(f"缺少源文件 {src}")
        current[name] = desired
        if local and name not in safe:
            conflicts.append(f"{name}（已跟踪或未被忽略）")
        elif not local and name in deleted:
            conflicts.append(f"{name}（团队副本有待提交的删除）")
        elif actual != desired:
            if actual != previous.get(name):
                conflicts.append(f"{name}（副本有差异，核对源文件 {src.relative_to(ROOT)}）")
            else:
                pending.append((name, src, dst))
    if local and state_name not in safe:
        conflicts.append(f"{state_name}（已跟踪或未被忽略）")
    if conflicts:
        raise ValueError("同步已停止，请核对以下路径：\n" + "\n".join(conflicts))
    for name, src, dst in pending:
        print(name)
        if not dry_run:
            data = src.read_bytes()
            mode = src.stat().st_mode & 0o777
            if hashlib.sha256(data).hexdigest() + ("+x" if mode & 0o111 else "") != current[name]:
                raise ValueError(f"源文件在同步期间发生变化，请重试 {name}")
            if fingerprint(checked_path(theme, name)) != previous.get(name):
                raise ValueError(f"主题副本在同步期间发生变化，请核对 {name}")
            write_atomic(dst, data, mode)
    if not dry_run and current != previous:
        write_atomic(state, (json.dumps(current, indent=2) + "\n").encode(), 0o600 if local else 0o644)
    print(f"{'预览' if dry_run else '同步完成'}（{profile}）：清单 {len(sources)} 项，需要复制 {len(pending)} 项")
    if not local:
        print("主题入口 AGENTS.md 请引用 .agents/shopify-harness.md；Claude Code 接入见 README。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme", type=Path, help="目标 Shopify 主题仓库根目录")
    parser.add_argument("--dry-run", action="store_true", help="仅检查并列出变化")
    parser.add_argument("--profile", choices=("ecoflow", "generic"), default="ecoflow",
                        help="ecoflow 使用已有的 Git 忽略约定（默认），generic 允许提交共享文件")
    args = parser.parse_args()
    theme = args.theme.resolve()
    top = subprocess.check_output(["git", "-C", str(theme), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(top).resolve() != theme or not (theme / "layout/theme.liquid").is_file():
        raise ValueError("目标必须是 Shopify 主题的 Git 工作区根目录")
    fd = os.open(theme, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sync(theme, args.dry_run, args.profile)
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
