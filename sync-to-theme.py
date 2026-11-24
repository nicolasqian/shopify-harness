#!/usr/bin/env python3
"""按清单同步 EcoFlow US 的 harness 文件。"""
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


def checked_path(base, name):
    relative = Path(name)
    if relative.is_absolute() or relative.as_posix() != name or any(
        part in ("..", ".git") for part in relative.parts
    ) or not relative.parts:
        raise ValueError(f"无效路径 {name}")
    path = base / relative
    if path.resolve() != path or (path.exists() and not path.is_file()):
        raise ValueError(f"路径不是普通文件或经过符号链接 {path}")
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


def sync(theme, dry_run):
    state = checked_path(theme, STATE)
    previous = json.loads(state.read_text()) if state.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError(f"同步记录格式异常 {state}")
    names = (ROOT / "manifest.txt").read_text().splitlines()
    if not names or len(names) != len(set(names)) or STATE in names:
        raise ValueError("文件清单为空、重复或包含同步记录")
    # 默认 check-ignore 会排除已跟踪文件，同时保护当前分支的业务文件。
    ignored = subprocess.run(
        ["git", "-C", str(theme), "check-ignore", "-z", "--stdin"],
        input="\0".join([*names, STATE, ""]).encode(), capture_output=True,
    )
    if ignored.returncode not in (0, 1):
        raise ValueError(ignored.stderr.decode())
    safe = set(ignored.stdout.decode().split("\0"))
    pending, conflicts, current = [], [], {}
    for name in names:
        src = checked_path(ROOT, name)
        dst = checked_path(theme, name)
        desired, actual = fingerprint(src), fingerprint(dst)
        if desired is None:
            raise ValueError(f"缺少源文件 {src}")
        current[name] = desired
        if name not in safe:
            conflicts.append(f"{name}（已跟踪或未被忽略）")
        elif actual != desired:
            if actual != previous.get(name):
                conflicts.append(f"{name}（主题副本与上次同步记录不同）")
            else:
                pending.append((name, src, dst))
    if STATE not in safe:
        conflicts.append(f"{STATE}（已跟踪或未被忽略）")
    if conflicts:
        raise ValueError("同步已停止，请核对以下路径：\n" + "\n".join(conflicts))
    for name, src, dst in pending:
        print(name)
        if not dry_run:
            data = src.read_bytes()
            mode = src.stat().st_mode & 0o777
            if hashlib.sha256(data).hexdigest() + ("+x" if mode & 0o111 else "") != current[name]:
                raise ValueError(f"源文件在同步期间发生变化，请重试 {name}")
            write_atomic(dst, data, mode)
    if not dry_run and current != previous:
        write_atomic(state, (json.dumps(current, indent=2) + "\n").encode(), 0o600)
    print(f"{'预览' if dry_run else '同步完成'}：清单 {len(names)} 项，需要复制 {len(pending)} 项")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme", type=Path, help="ecoflow-tech 主题仓库根目录")
    parser.add_argument("--dry-run", action="store_true", help="仅检查并列出变化")
    args = parser.parse_args()
    theme = args.theme.resolve()
    top = subprocess.check_output(["git", "-C", str(theme), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(top).resolve() != theme or not (theme / "layout/theme.liquid").is_file():
        raise ValueError("目标必须是 Shopify 主题的 Git 工作区根目录")
    fd = os.open(theme, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sync(theme, args.dry_run)
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
