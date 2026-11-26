#!/usr/bin/env python3
"""Verify Shopify theme edits in the working tree or staged snapshot."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import theme_json

POLICY = ".agents/shopify-harness-policy.json"
THEME_DIRS = ("assets/", "blocks/", "config/", "layout/", "locales/", "sections/", "snippets/", "templates/")
JSONC_DIRS = ("config/", "locales/", "sections/", "templates/")
STYLESHEET_DIRS = ("sections/", "snippets/", "blocks/", "layout/")
STYLESHEET = re.compile(r"\{%-?\s*stylesheet\s*-?%\}")
TEST_NAME = re.compile(r"^tests/[^/]+\.test\.(c|m)?js$")


def git_paths(root, *args):
    data = subprocess.check_output(["git", *args], cwd=root)
    return {os.fsdecode(item) for item in data.split(b"\0") if item}


def changed_files(root, staged, base):
    # Detect renames as deletion + addition so both paths reach the protection check.
    diff = ["diff", "--no-renames", "--name-only", "-z"]
    if base:
        paths = git_paths(root, *diff, base, "--")
        return paths | git_paths(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = git_paths(root, *diff, "--cached")
    if not staged:
        paths.update(git_paths(root, *diff))
        paths.update(git_paths(root, "ls-files", "--others", "--exclude-standard", "-z"))
    return paths


@contextmanager
def check_tree(root, files, args):
    if not args.staged:
        yield root
        return
    tracked = git_paths(root, "ls-files", "--cached", "-z")
    needs_context = args.theme_check or (not args.skip_tests and any(TEST_NAME.match(f) for f in tracked))
    with tempfile.TemporaryDirectory(prefix="shopify-harness-index-") as directory:
        tree = Path(directory).resolve()
        cmd = ["git", "checkout-index", "--ignore-skip-worktree-bits", "--prefix=" + str(tree) + "/"]
        if needs_context:
            subprocess.run([*cmd, "--all"], cwd=root, check=True)
            deps = root / "node_modules"
            if deps.is_dir() and not (tree / "node_modules").exists():
                (tree / "node_modules").symlink_to(deps, target_is_directory=True)
        else:
            paths = tracked.intersection(files | {POLICY})
            data = b"".join(os.fsencode(p) + b"\0" for p in sorted(paths))
            subprocess.run([*cmd, "-z", "--stdin"], cwd=root, input=data, check=True)
        yield tree


def load_policy(root, tree):
    path = tree / POLICY
    # Local-only installs deliberately keep the policy out of the Git index.
    if tree != root and not path.exists() and (root / POLICY).is_file():
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", POLICY], cwd=root)
        if ignored.returncode == 0:
            path = root / POLICY
    policy = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(policy, dict) or set(policy) - {"protected_paths", "forbid_new_stylesheet"}:
        raise ValueError(f"Invalid policy keys in {POLICY}")
    patterns = policy.get("protected_paths", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
        raise ValueError(f"Expected protected_paths to contain path patterns in {POLICY}")
    forbid = policy.get("forbid_new_stylesheet", False)
    if not isinstance(forbid, bool):
        raise ValueError(f"Expected a boolean for forbid_new_stylesheet in {POLICY}")
    return patterns, forbid


def previous_stylesheet_count(root, rel, revision):
    blob = subprocess.run(["git", "show", revision + ":" + rel], cwd=root, capture_output=True)
    return len(STYLESHEET.findall(blob.stdout.decode("utf-8", errors="replace"))) if blob.returncode == 0 else 0


def run_node_tests(tree):
    tests = sorted(str(p.relative_to(tree)) for p in (tree / "tests").glob("*.test.*")
                   if TEST_NAME.match(str(p.relative_to(tree))))
    if tests:
        subprocess.run(["node", "--test", *tests], cwd=tree, check=True)
    return len(tests)


def theme_diagnostics(tree):
    cmd = ["shopify", "theme", "check", "--path", str(tree), "--output", "json", "--fail-level", "error"]
    proc = subprocess.run(cmd, cwd=tree, capture_output=True, text=True)
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    diagnostics = []
    try:
        reports = json.loads(proc.stdout)
        if not isinstance(reports, list):
            raise ValueError("expected a list of Theme Check reports")
        for report in reports:
            path = Path(report["path"])
            rel = os.path.relpath(path, tree) if path.is_absolute() else str(path)
            for item in report["offenses"]:
                diagnostics.append((rel, item["check"], item["message"], item["severity"], item["start_row"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"Invalid Theme Check output (exit {proc.returncode}): {exc}\n{proc.stdout}") from exc
    if proc.returncode and (proc.returncode != 1 or not any(d[3] == "error" for d in diagnostics)):
        raise ValueError(f"Theme Check failed (exit {proc.returncode})")
    return diagnostics


def baseline_errors(root, revision):
    # Use a separate index to export the reference tree without touching the developer's checkout.
    with tempfile.TemporaryDirectory(prefix="shopify-harness-base-") as directory:
        tree = Path(directory).resolve() / "theme"
        tree.mkdir()
        env = dict(os.environ, GIT_INDEX_FILE=str(tree.parent / "index"))
        subprocess.run(["git", "read-tree", revision], cwd=root, env=env, check=True)
        subprocess.run(["git", "checkout-index", "--all", "--prefix=" + str(tree) + "/"],
                       cwd=root, env=env, check=True)
        deps = root / "node_modules"
        if deps.is_dir() and not (tree / "node_modules").exists():
            (tree / "node_modules").symlink_to(deps, target_is_directory=True)
        return Counter(d[:4] for d in theme_diagnostics(tree) if d[3] == "error")


def run_theme_check(root, tree, files, revision):
    diagnostics = theme_diagnostics(tree)
    errors = []
    outside = []
    for path, check, message, severity, row in diagnostics:
        if path in files:
            print(f"[changed] {path}:{row} [{severity}] {check} {message}")
            if severity == "error":
                errors.append(path)
        elif severity == "error":
            outside.append((path, check, message, severity, row))

    # A deleted dependency may surface only on an untouched caller. Compare these errors
    # to the same CLI on the Git baseline before filtering pre-existing findings.
    if outside:
        existing = Counter()
        has_revision = subprocess.run(["git", "rev-parse", "--verify", "--quiet", revision],
                                      cwd=root, stdout=subprocess.DEVNULL)
        if has_revision.returncode == 0:
            existing = baseline_errors(root, revision)
        old_count = 0
        for item in outside:
            key = item[:4]
            if existing[key] > 0:
                existing[key] -= 1
                old_count += 1
                continue
            path, check, message, severity, row = item
            print(f"[theme] {path}:{row} [{severity}] {check} {message}")
            errors.append(path)
        print(f"Pre-existing errors on unchanged files: {old_count}")
    if errors:
        raise ValueError(f"Theme Check reported {len(errors)} relevant error(s)")


def verify(root, tree, files, args):
    patterns, forbid_stylesheet = load_policy(root, tree)
    errors = []
    json_count = 0
    style_count = 0
    for rel in sorted(files):
        if any(fnmatchcase(rel.casefold(), pattern.casefold()) for pattern in patterns):
            message = f"Protected path changed: {rel}"
            if args.allow_protected:
                print("[WARN]", message)
            else:
                errors.append(message)
        path = tree / rel
        if not path.is_file():
            continue
        if rel.endswith(".json"):
            json_count += 1
            parse = theme_json.loads if rel.startswith(JSONC_DIRS) else theme_json.strict_loads
            try:
                parse(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                errors.append(f"Invalid JSON in {rel}: {exc}")
        if forbid_stylesheet and rel.endswith(".liquid") and rel.startswith(STYLESHEET_DIRS):
            style_count += 1
            tags = STYLESHEET.findall(path.read_text(encoding="utf-8"))
            if tags and len(tags) > previous_stylesheet_count(root, rel, args.base or "HEAD"):
                message = f"Theme policy forbids new stylesheet tags: {rel}"
                if args.allow_stylesheet:
                    print("[WARN]", message)
                else:
                    errors.append(message)
    for message in errors:
        print("[FAIL]", message, file=sys.stderr)
    tests = 0 if args.skip_tests else run_node_tests(tree)
    lint = args.theme_check and any(f.startswith(THEME_DIRS) or f == ".theme-check.yml" for f in files)
    if lint:
        run_theme_check(root, tree, files, args.base or "HEAD")
    print(f"Checked {len(files)} file(s): json={json_count}, stylesheet-guard={style_count}, "
          f"tests={tests}, theme-check={'full theme' if lint else 'skipped'}")
    if errors:
        return 1
    print("[PASS] All checks passed.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Repository-relative paths (defaults to Git changes)")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--base", metavar="REV", help="Check the working tree against its merge base with REV (for PR checkouts)")
    scope.add_argument("--staged", action="store_true", help="Check the Git index, including staged test and theme files")
    parser.add_argument("--skip-tests", action="store_true", help="Skip tests/*.test.{js,cjs,mjs}")
    parser.add_argument("--theme-check", action="store_true", help="Lint the complete theme for affected theme paths")
    parser.add_argument("--allow-protected", action="store_true", help="Allow authorized changes to protected paths")
    parser.add_argument("--allow-stylesheet", action="store_true", help="Override the theme's stylesheet policy")
    args = parser.parse_args()
    try:
        root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
        if args.base:
            if args.base.startswith("-"):
                parser.error("expected a Git revision for --base")
            args.base = subprocess.check_output(["git", "merge-base", args.base, "HEAD"], cwd=root, text=True).strip()
        files = {Path(f).as_posix() for f in args.files} if args.files else changed_files(root, args.staged, args.base)
        if any(Path(f).is_absolute() or ".." in Path(f).parts or ".git" in Path(f).parts for f in files):
            parser.error("expected paths within the repository")
        with check_tree(root, files, args) as tree:
            return verify(root, tree, files, args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
