#!/usr/bin/env python3
"""Run lightweight, diff-scoped verification checks for Shopify theme edits."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

LEADING_BLOCK_COMMENT = re.compile(r"^\s*(?:/\*.*?\*/\s*)+", re.S)
PROTECTED_PATTERNS = (
    re.compile(r"(^|/)snippets/dataLayer[^/]*\.liquid$", re.I),
)


def repo_root(cwd: Path) -> Path:
    out = subprocess.check_output(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    return Path(out).resolve()


def changed_files(root: Path, staged_only: bool) -> list[str]:
    paths: set[str] = set()
    if staged_only:
        cmds = [["git", "-C", str(root), "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]]
    else:
        cmds = [
            ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
            ["git", "-C", str(root), "diff", "--name-only", "-z", "--diff-filter=ACMR"],
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        ]
    for cmd in cmds:
        out = subprocess.check_output(cmd)
        for item in out.decode("utf-8", errors="surrogateescape").split("\0"):
            if item:
                paths.add(item)
    return sorted(paths)


def check_protected(files: list[str], allow_protected: bool) -> list[str]:
    hits = [f for f in files if any(p.search(f) for p in PROTECTED_PATTERNS)]
    if not hits:
        return []
    if allow_protected:
        print(f"[WARN] Protected tracking files modified (allowed by flag): {', '.join(hits)}")
        return []
    return [f"Protected tracking file modified without --allow-protected: {f}" for f in hits]


def check_json_files(root: Path, files: list[str]) -> tuple[int, list[str]]:
    json_files = [f for f in files if f.endswith(".json") and (root / f).is_file()]
    errors: list[str] = []
    for rel in json_files:
        path = root / rel
        try:
            raw = path.read_text(encoding="utf-8")
            cleaned = LEADING_BLOCK_COMMENT.sub("", raw, count=1)
            json.loads(cleaned)
        except Exception as exc:
            errors.append(f"Invalid JSON in {rel}: {exc}")
    return len(json_files), errors


def run_node_tests(root: Path) -> tuple[int, list[str]]:
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return 0, []
    test_files = sorted(
        str(p.relative_to(root))
        for p in tests_dir.iterdir()
        if p.is_file() and re.search(r"\.test\.(c|m)?js$", p.name)
    )
    if not test_files:
        return 0, []
    if not shutil.which("node"):
        return len(test_files), ["Node.js not found in PATH; skipped tests"]
    proc = subprocess.run(
        ["node", "--test", *test_files],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return len(test_files), [f"node --test failed (exit {proc.returncode}):\n{output}"]
    return len(test_files), []


def run_theme_check(root: Path, files: list[str]) -> tuple[int, list[str]]:
    liquid_files = [f for f in files if f.endswith(".liquid") and (root / f).is_file()]
    if not liquid_files:
        return 0, []
    if not shutil.which("shopify"):
        return len(liquid_files), ["shopify CLI not found in PATH; cannot run --theme-check"]
    proc = subprocess.run(
        ["shopify", "theme", "check", *liquid_files],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return len(liquid_files), [f"shopify theme check failed (exit {proc.returncode}):\n{output}"]
    return len(liquid_files), []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Explicit relative file paths to check (defaults to git changes)")
    parser.add_argument("--staged", action="store_true", help="Only inspect staged git changes")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests/*.test.*")
    parser.add_argument("--theme-check", action="store_true", help="Run targeted shopify theme check on changed .liquid files")
    parser.add_argument("--allow-protected", action="store_true", help="Allow edits to protected tracking files (dataLayer*.liquid)")
    args = parser.parse_args()

    try:
        root = repo_root(Path.cwd())
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Must run inside a Git repository: {exc}", file=sys.stderr)
        return 1

    files = sorted(set(args.files)) if args.files else changed_files(root, args.staged)
    errors: list[str] = []

    errors.extend(check_protected(files, args.allow_protected))
    json_count, json_errors = check_json_files(root, files)
    errors.extend(json_errors)

    test_count = 0
    if not args.skip_tests:
        test_count, test_errors = run_node_tests(root)
        errors.extend(test_errors)

    liquid_checked = 0
    if args.theme_check:
        liquid_checked, tc_errors = run_theme_check(root, files)
        errors.extend(tc_errors)

    print(
        f"Checked {len(files)} file(s): "
        f"json={json_count}, tests={test_count}, theme-check-liquid={liquid_checked}"
    )
    if errors:
        for err in errors:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1
    print("[PASS] All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
