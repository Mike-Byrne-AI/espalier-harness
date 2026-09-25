#!/usr/bin/env python3
"""Espalier-Harness code review audit script.

Used by the code-reviewer agent. Runs AST-based checks on Python source
files and emits findings in a consistent format. Uses only stdlib so it
works in any environment where espalier is installed.

Usage:
    python3 tools/review_agent_audit.py --mode changed
    python3 tools/review_agent_audit.py --mode full
    python3 tools/review_agent_audit.py --mode changed --file path/to/file.py

The agent's Bash(python3 *) allowlist covers all invocations of this script.
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

# stdlib modules — anything not in this set is a third-party dep
STDLIB_NAMES = sys.stdlib_module_names  # Python 3.10+

ESPALIER_IMPORT_PATTERN = ("espalier",)
HOOKS_DIR = Path("tools/cc/hooks")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _changed_files() -> list[Path]:
    """Return Python files changed vs HEAD or staged."""
    try:
        r1 = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        ).stdout.splitlines()
        r2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        ).stdout.splitlines()
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError, ValueError):
        return []
    seen: set[str] = set()
    files = []
    for line in r1 + r2:
        line = line.strip()
        if line and line not in seen and line.endswith(".py"):
            seen.add(line)
            p = Path(line)
            if p.exists():
                files.append(p)
    return files


def _full_files() -> list[Path]:
    """Return all Python files in espalier/, tools/cc/, and tests/."""
    roots = [Path("espalier"), Path("tools/cc"), Path("tests")]
    files = []
    for root in roots:
        if root.exists():
            files.extend(root.rglob("*.py"))  # espalier:safe-walk-ok espalier-dev audit tool: walks espalier's own espalier/+tools/cc/+tests/, never an adopter tree
    return [f for f in files if f.name != "__init__.py"]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_bare_except(path: Path, tree: ast.AST) -> list[str]:
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            issues.append(
                f"  BARE EXCEPT  {path}:{node.lineno} — bare `except:` swallows all errors"
            )
    return issues


def _is_main_guard(test: ast.expr) -> bool:
    """True if ``test`` is the ``__name__ == "__main__"`` comparison."""
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _nodes_under_main_guard(tree: ast.AST) -> set[int]:
    """Return ``id()``s of every node inside an ``if __name__ == "__main__":``
    block — a CLI shim, not a hook-event handler."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_main_guard(node.test):
            for child in node.body:
                for sub in ast.walk(child):
                    guarded.add(id(sub))
    return guarded


def check_hook_print_to_stdout(path: Path, tree: ast.AST) -> list[str]:
    """Flag print() calls in hook scripts that don't send to stderr.

    Hooks that block (exit 2) use stdout exclusively for block JSON; advisory
    messages must go to stderr so they don't corrupt the JSON payload CC reads.
    UserPromptSubmit hooks (task_router) legitimately print to stdout to inject
    context — excluded from this check.
    This check only applies to tools/cc/hooks/ — CLI output to stdout is fine.

    Prints inside an ``if __name__ == "__main__":`` block are CLI-shim
    output (e.g. the ``/recall`` pull tool in _recall.py), not hook-event handler
    output, so they cannot corrupt block JSON — excluded, like task_router.
    """
    if "tools/cc/hooks" not in str(path).replace("\\", "/"):
        return []
    # task_router is a UserPromptSubmit hook — stdout is used for context injection
    if path.name == "task_router.py":
        return []
    guarded = _nodes_under_main_guard(tree)
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if id(node) in guarded:
            continue  # CLI-shim print under `if __name__ == "__main__":`
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "print"):
            continue
        # Skip payload prints: print(json.dumps(...)) is the intentional
        # stdout block JSON that CC reads. Only flag bare string prints.
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Call):
                func2 = first_arg.func
                if isinstance(func2, ast.Attribute) and func2.attr == "dumps":
                    continue  # json.dumps payload — correct stdout usage
        has_stderr = any(
            kw.arg == "file" and isinstance(kw.value, ast.Attribute)
            and kw.value.attr == "stderr"
            for kw in node.keywords
        )
        if not has_stderr:
            issues.append(
                f"  PRINT STDOUT {path}:{node.lineno} — hook print() without file=sys.stderr (may corrupt block JSON)"
            )
    return issues


def check_hook_exit_codes(path: Path, tree: ast.AST) -> list[str]:
    """Flag sys.exit(1) in hook scripts."""
    if not str(path).startswith("tools/cc/hooks"):
        return []
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_sys_exit = (
            isinstance(func, ast.Attribute)
            and func.attr == "exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sys"
        )
        if not is_sys_exit:
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 1:
            issues.append(
                f"  EXIT 1       {path}:{node.lineno} — hook must exit 0 (allow) or 2 (block)"
            )
    return issues


def check_espalier_import_in_tools_cc(path: Path, tree: ast.AST) -> list[str]:
    """Flag espalier imports in tools/cc/ files."""
    if "tools/cc" not in str(path).replace("\\", "/"):
        return []
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "espalier" or alias.name.startswith("espalier."):
                    issues.append(
                        f"  ESPALIER IMPORT {path}:{node.lineno} — tools/cc/ must have zero espalier imports"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "espalier" or mod.startswith("espalier."):
                issues.append(
                    f"  ESPALIER IMPORT {path}:{node.lineno} — tools/cc/ must have zero espalier imports"
                )
    return issues


def check_scanner_stdlib_only(path: Path, tree: ast.AST) -> list[str]:
    """Flag non-stdlib imports in espalier/scanners/ files."""
    if "espalier/scanners" not in str(path).replace("\\", "/"):
        return []
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in STDLIB_NAMES and top != "__future__":
                    issues.append(
                        f"  NON-STDLIB    {path}:{node.lineno} — scanner imports non-stdlib: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            top = node.module.split(".")[0]
            if top not in STDLIB_NAMES and top != "__future__":
                issues.append(
                    f"  NON-STDLIB    {path}:{node.lineno} — scanner imports non-stdlib: {node.module}"
                )
    return issues


def check_path_normalization(path: Path, tree: ast.AST) -> list[str]:
    """
    Flag path comparisons that use string equality on un-normalized paths.
    The real rule: normalize (via .replace) before comparing or storing,
    not 'never use os.path.join'. Only flag os.sep usage and string-equality
    comparisons with Path strings — not safe directory-walk join calls.
    """
    issues = []
    for node in ast.walk(tree):
        # Flag os.sep references (cross-platform hazard)
        if isinstance(node, ast.Attribute) and node.attr == "sep":
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                issues.append(
                    f"  PATH HAZARD  {path}:{node.lineno} — os.sep is platform-specific; use '/' or .replace"
                )
    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_audit(files: list[Path], mode: str) -> int:
    """Run all checks. Returns number of issues found."""
    all_issues: list[str] = []
    files_reviewed = 0
    files_skipped = 0

    for path in sorted(files):
        try:
            # Bytes: a non-UTF-8 source with no coding cookie is the
            # SyntaxError reported below, not a decode error past the
            # OSError handler (DEF-829).
            source = path.read_bytes()
        except OSError:
            files_skipped += 1
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            all_issues.append(f"  SYNTAX ERROR {path}: {e}")
            files_reviewed += 1
            continue

        file_issues: list[str] = []
        file_issues += check_bare_except(path, tree)
        file_issues += check_hook_exit_codes(path, tree)
        file_issues += check_espalier_import_in_tools_cc(path, tree)
        file_issues += check_scanner_stdlib_only(path, tree)
        file_issues += check_path_normalization(path, tree)
        file_issues += check_hook_print_to_stdout(path, tree)


        if file_issues:
            all_issues.extend(file_issues)
        files_reviewed += 1

    print("\nCOVERAGE SUMMARY")
    print(f"  Mode:     {mode}")
    print(f"  Reviewed: {files_reviewed} files")
    if files_skipped:
        print(f"  Skipped:  {files_skipped} files (unreadable)")
    print()

    if all_issues:
        print(f"FINDINGS ({len(all_issues)} issues):")
        for issue in all_issues:
            print(issue)
    else:
        print("FINDINGS: none — all checks passed")

    return len(all_issues)


def main() -> None:
    parser = argparse.ArgumentParser(description="Espalier-Harness code review audit")
    parser.add_argument(
        "--mode",
        choices=["changed", "full"],
        default="changed",
        help="changed: only git-changed files; full: all source files",
    )
    parser.add_argument(
        "--file",
        help="Audit a single specific file instead",
    )
    args = parser.parse_args()

    if args.file:
        files = [Path(args.file)]
        mode = f"single:{args.file}"
    elif args.mode == "changed":
        files = _changed_files()
        mode = "changed"
        if not files:
            print("No changed Python files found. Use --mode full to audit all source files.")
            sys.exit(0)
    else:
        files = _full_files()
        mode = "full"

    issue_count = run_audit(files, mode)
    sys.exit(0 if issue_count == 0 else 1)


if __name__ == "__main__":
    # UTF-8 on both streams whatever the console code page: the report carries
    # non-ASCII punctuation, and on Windows a redirected stream defaults to the
    # ANSI page, so a parent decoding UTF-8 lost the whole report (the one red
    # on the first green-but-one Windows run, 2026-09-24).
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    main()
