#!/usr/bin/env python3
# Dev-only maintainer tool. Not installed by adopters (scripts/ is not packaged
# in the wheel/sdist); kept in-tree for harness self-maintenance.
"""Dead-rule audit: walks write_guard rules against the benchmark corpus
and reports zero-firing candidates.

For each pattern-matching rule in:
  - tools/cc/hooks/_bash_patterns.py (compiled regex extractors named `_*_RE`)
  - tools/cc/hooks/_protected_zones.py (PROTECTED_PREFIXES, PROTECTED_FILES)

walk bench/corpus/BC-*.json canonical_attempts and count which rules fire.
Rules with zero firings across the corpus are *candidates for review*: either
no test pins the rule's purpose, or the rule is genuinely dead and removable.

Approximations (this is an audit, not a verification gate):
  - Regex rules: `.search(command)` against the raw command string. Slight
    over-count for inner regexes that compose with an outer extractor
    (e.g. `_PY_FILE_OPEN_RE` fires only inside `_PYTHON_DASH_C_RE` bodies in
    production, but counts independently here). False positives are tolerable;
    a "dead" verdict means the audit found zero firings under a loose match.
  - Path rules: best-effort `os.path.normpath` resolution of file_path / extracted
    candidates against PROTECTED_PREFIXES (startswith) and PROTECTED_FILES
    (equality). Production uses _normalize_path with NFKC + casefold; the audit
    doesn't, so it's a lower bound on path-rule firings.

Stdlib-only. No espalier import. Existence is pinned by
`tests/_surface_expected.py`; output behavior is not test-contracted.

The `sys.path.insert` at module load is the standalone-script bridge for
hooks: `tools/cc/hooks/` is not a package, so loading `_bash_patterns` and
`_protected_zones` requires putting the hooks directory on `sys.path`
explicitly.

Usage:
    python scripts/audit_dead_rules.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
CORPUS_DIR = REPO_ROOT / "bench" / "corpus"

sys.path.insert(0, str(HOOKS_DIR))
import _bash_patterns  # noqa: E402
import _protected_zones  # noqa: E402


def collect_regex_rules() -> list[tuple[str, re.Pattern]]:
    rules: list[tuple[str, re.Pattern]] = []
    for name in sorted(dir(_bash_patterns)):
        if not name.endswith("_RE"):
            continue
        obj = getattr(_bash_patterns, name)
        if isinstance(obj, re.Pattern):
            rules.append((name, obj))
    return rules


def collect_path_rules() -> list[tuple[str, str, str]]:
    rules: list[tuple[str, str, str]] = []
    for prefix in _protected_zones.PROTECTED_PREFIXES:
        rules.append((f"PREFIX::{prefix}", "prefix", prefix))
    for filepath in sorted(_protected_zones.PROTECTED_FILES):
        rules.append((f"FILE::{filepath}", "file", filepath))
    return rules


def load_corpus() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for path in sorted(CORPUS_DIR.glob("BC-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        bc_id = data["id"]
        for attempt in data.get("canonical_attempts", []):
            out.append((bc_id, attempt))
    return out


def _candidate_paths_for_attempt(tool_input: dict) -> list[str]:
    paths: list[str] = []
    fp = tool_input.get("file_path")
    if isinstance(fp, str):
        paths.append(fp)
    cmd = tool_input.get("command")
    if isinstance(cmd, str):
        try:
            paths.extend(_bash_patterns._candidate_paths_from_bash(cmd))
            paths.extend(_bash_patterns._candidate_paths_from_powershell(cmd))
            # The operands a verb removes or relocates (§C52): a rule keyed on
            # a delete or a move is live only if this audit reads them too.
            paths.extend(p for _effect, p in _bash_patterns.iter_removed_or_relocated_operands(cmd))
            paths.extend(p for _effect, p in _bash_patterns.iter_ps_removed_or_relocated_operands(cmd))
        except Exception as exc:  # noqa: BLE001 -- best-effort path extraction; surface to stderr for visibility
            print(
                f"[audit_dead_rules] candidate-path extract failed: {exc}",
                file=sys.stderr,
            )
    return paths


def _normalize(candidate: str) -> str:
    norm = os.path.normpath(candidate.replace("\\", "/")).replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _path_matches_prefix(candidate: str, prefix: str) -> bool:
    norm = _normalize(candidate)
    return norm.startswith(prefix) or ("/" + prefix) in norm


def _path_matches_file(candidate: str, target: str) -> bool:
    norm = _normalize(candidate)
    return norm == target or norm.endswith("/" + target)


def main() -> int:
    regex_rules = collect_regex_rules()
    path_rules = collect_path_rules()
    corpus = load_corpus()

    firings: dict[str, set[str]] = defaultdict(set)

    for bc_id, attempt in corpus:
        tool_input = attempt.get("tool_input") or {}
        command = tool_input.get("command") if isinstance(tool_input.get("command"), str) else ""

        for name, pattern in regex_rules:
            if command and pattern.search(command):
                firings[name].add(bc_id)

        candidates = _candidate_paths_for_attempt(tool_input)
        for rule_name, kind, value in path_rules:
            for candidate in candidates:
                if not isinstance(candidate, str):
                    continue
                if kind == "prefix" and _path_matches_prefix(candidate, value):
                    firings[rule_name].add(bc_id)
                    break
                if kind == "file" and _path_matches_file(candidate, value):
                    firings[rule_name].add(bc_id)
                    break

    all_rule_names = [name for name, _ in regex_rules] + [name for name, _, _ in path_rules]
    rows = sorted(all_rule_names, key=lambda n: (len(firings.get(n, set())), n))

    bc_classes = {bc for bc, _ in corpus}
    print(f"Dead-rule audit -- bench/corpus/ ({CORPUS_DIR.relative_to(REPO_ROOT)})")
    print("=" * 70)
    print(f"Corpus  : {len(bc_classes)} bypass classes, {len(corpus)} canonical attempts")
    print(f"Rules   : {len(regex_rules)} regex extractors + {len(path_rules)} protected-path entries = {len(all_rule_names)} total")
    print()
    header = f"{'Rule':<48} {'Fires':>6}  Classes"
    print(header)
    print("-" * 100)
    for name in rows:
        hits = firings.get(name, set())
        classes_text = ", ".join(sorted(hits)) if hits else "(none)"
        if len(classes_text) > 42:
            classes_text = classes_text[:39] + "..."
        marker = "  <-- DEAD" if not hits else ""
        print(f"{name:<48} {len(hits):>6}  {classes_text}{marker}")

    dead = [n for n in all_rule_names if not firings.get(n)]
    print()
    print(f"Dead candidates ({len(dead)}):")
    if dead:
        for name in dead:
            print(f"  - {name}")
    else:
        print("  (none -- every rule has at least one corpus firing)")

    print()
    print("Note: 'dead' here means no canonical_attempt in bench/corpus/ exercises this")
    print("rule under loose lexical matching. Manual review required before deletion --")
    print("the rule may pin a behavior the corpus does not yet cover.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
