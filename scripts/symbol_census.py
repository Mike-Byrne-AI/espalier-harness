#!/usr/bin/env python3
"""Every mention of a symbol across the surfaces a rename must sweep -- untruncated.

Why this exists
---------------
On 2026-09-05 a rename census was run as ``grep -rn old_name tests/ | head -40``.
It showed three test files. The untruncated run showed five, plus a name-keyed
test roster that stayed green while walking one function fewer, plus four docs.
Each miss surfaced one failed run later, one at a time: four fix-and-rerun
rounds for one rename. A census is only a census when its output is complete,
and a census that a reader has to remember to run over the right directories
with the right flags is one that will be run over the wrong ones.

What it does
------------
Walks the tracked tree (``git ls-files``) plus the gitignored working state
that also names symbols (the forward ledger and its probes, the goal snapshot),
matches each NAME as a whole identifier (``(?<!\\w)NAME(?!\\w)``, so a dotted
prefix ``cli._deploy_file`` counts and ``_deploy_files`` does not), and prints
EVERY hit grouped by surface. Nothing is elided: a file with sixty hits lists
sixty line numbers, because the sixty-first would have been the one that
mattered.

Three classifications a rename treats differently, decided mechanically:

* **mirror** -- a byte- or subset-pinned copy of another file, read from
  ``espalier.mirror_registry`` (the census of mirror rows), never hand-listed.
  Edit the source of truth and run the row's sync; the line printed says which.
* **record** -- a surface that legitimately keeps old names (a findings corpus,
  a session archive, the changelog, a struck ledger row's PRIOR TEXT). Counted,
  not listed unless ``--include-records``; editing one falsifies the record.
* **live** -- everything else. A live mention after a rename is work.

Exit status is ``1`` while live mentions remain and ``0`` when none do, so
``python3 scripts/symbol_census.py old_name && echo swept`` is a post-rename
check. ``--json`` emits the same census for a script.

Usage::

    python3 scripts/symbol_census.py _deploy_file
    python3 scripts/symbol_census.py _seed_stamp_line _SEED_ADAPT_HEADER --include-records
    python3 scripts/symbol_census.py NAME --json
    python3 scripts/symbol_census.py NAME --root /path/to/repo
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_DEFAULT_ROOT = _HERE.parents[1]

#: Gitignored working state that names symbols and breaks when one moves: the
#: ledger probes did exactly that on 2026-09-05 (a probe reading a constant that
#: had moved reported UNRESOLVED). Absent files are skipped silently.
_UNTRACKED_STATE: tuple[str, ...] = (
    "task-packs/FORWARD_LEDGER.md",
    "task-packs/LEDGER_PROBES.json",
    "cc/GOAL.md",
    "cc/GOAL_OWED.json",
)

#: Surfaces that keep old names on purpose. The first two are the declared
#: record set in ``tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS``
#: (a stale pointer there is expected aging); the changelog is a dated record
#: of what each entry said when it landed; the ledger keeps a struck row's
#: PRIOR TEXT verbatim and so is a record for old names even while its LIVE
#: rows may need re-anchoring -- which is why ledger hits are printed under
#: their own heading rather than hidden.
_RECORD_SURFACES: tuple[str, ...] = (
    "docs/session-archive.md",
    "memory/CONVERGENCE_LEDGER.md",
    "CHANGELOG.md",
    # the session log: the most old-name-dense file in the repo and a record
    # by Core Rule 13; classifying it live made the "swept" exit unreachable
    # for exactly the names most worth censusing (failure-mode pass, driven)
    "ESPALIER_MEMORY.md",
)

#: Directories that hold generated or foreign bytes, never a rename target.
_SKIP_DIR_PREFIXES: tuple[str, ...] = ("build/", "dist/", ".git/")
_SKIP_DIR_PARTS: frozenset[str] = frozenset({"__pycache__", ".pytest_cache", "node_modules"})

#: Group order for the human report; a hit path lands in the first prefix that
#: matches, else "other". The order is also the sweep order a rename wants.
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source", ("espalier/", "tools/cc/")),
    ("tests", ("tests/",)),
    ("scripts", ("scripts/",)),
    ("bench", ("bench/",)),
    ("claude", (".claude/",)),
    ("docs", ("docs/", "README.md", "CONTRIBUTING.md", "CLAUDE.md")),
    ("memory", ("memory/",)),
    ("workflows", (".github/",)),
    ("ledger", ("task-packs/", "cc/")),
)


def _tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"symbol_census: `git ls-files` failed under {root}: "
                         f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return [p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def population(root: Path) -> list[str]:
    """Repo-relative paths to scan: tracked files plus the untracked state."""
    files = _tracked_files(root)
    seen = set(files)
    for rel in _UNTRACKED_STATE:
        if rel not in seen and (root / rel).is_file():
            files.append(rel)
    out = []
    for rel in files:
        if rel.startswith(_SKIP_DIR_PREFIXES):
            continue
        if any(part in _SKIP_DIR_PARTS for part in rel.split("/")):
            continue
        out.append(rel)
    return out


def _mirror_rows(root: Path):
    """The mirror registry's rows, imported from the tree under scan so the
    census follows the registry rather than restating it. A tree without the
    engine (an adopter repo) has no mirror rows to speak of."""
    sys.path.insert(0, str(root))
    try:
        from espalier import mirror_registry  # type: ignore
    except Exception:  # noqa: BLE001 -- no engine here means no rows, not a crash
        return ()
    finally:
        sys.path.pop(0)
    return tuple(mirror_registry.MIRROR_ROWS)


def classify(rel: str, mirror_rows) -> tuple[str, str]:
    """``(kind, detail)`` -- kind is ``mirror`` / ``record`` / ``live``; detail
    is the sync command for a mirror, the group name otherwise.

    A registry row whose mirror side is a whole TREE (a directory prefix) or a
    whole FILE that is byte-pinned is a mirror everywhere in it. A row whose
    mirror side is a single file mirrored only in a GENERATED REGION (the
    subset+transform rows on ``implement-pack.md`` and the reflect skill) is
    live outside that region -- the first cut called every line of those two
    files "mirror", so a stale mention in their ordinary prose read as swept
    (code-review pass, driven on this very batch's text).
    """
    for row in mirror_rows:
        for prefix in row.mirrors:
            region_only = (not prefix.endswith("/")) and "transform" in str(row.kind)
            if region_only:
                continue
            if rel.startswith(prefix):
                return "mirror", f"{row.name}: {row.sync}"
    if rel in _RECORD_SURFACES:
        return "record", "record"
    for group, prefixes in _GROUPS:
        if rel.startswith(prefixes):
            return "live", group
    return "live", "other"


#: A struck ledger member row: `| ~~`DEF-N`~~ | ... PRIOR TEXT: ...`.
_STRUCK_ROW = re.compile(r"^\|\s*~~`")


def _pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")


def census(root: Path, names: list[str]) -> dict:
    """The full census: every hit of every name, classified, never truncated."""
    rows = _mirror_rows(root)
    patterns = {n: _pattern(n) for n in names}
    hits: list[dict] = []
    scanned = 0
    for rel in population(root):
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: not a rename target
        scanned += 1
        kind, detail = classify(rel, rows)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pat in patterns.items():
                if pat.search(line):
                    k, d = kind, detail
                    if rel.endswith("FORWARD_LEDGER.md") and _STRUCK_ROW.match(line):
                        k, d = "record", "record"   # a struck row's PRIOR TEXT keeps old names on purpose
                    hits.append({"name": name, "path": rel, "line": lineno,
                                 "kind": k, "detail": d,
                                 "text": line.strip()[:200]})
    live = [h for h in hits if h["kind"] == "live"]
    groups_hit = {h["detail"] for h in live}
    return {
        "names": names,
        "scanned_files": scanned,
        "hits": hits,
        "live": len(live),
        "mirror": sum(1 for h in hits if h["kind"] == "mirror"),
        "record": sum(1 for h in hits if h["kind"] == "record"),
        "groups_without_live_hits": [g for g, _ in _GROUPS if g not in groups_hit],
    }


def render(result: dict, *, include_records: bool) -> str:
    out: list[str] = []
    names = ", ".join(result["names"])
    out.append(f"symbol census: {names}  ({result['scanned_files']} files scanned)")
    by_kind_group: dict[tuple[str, str], list[dict]] = {}
    for h in result["hits"]:
        by_kind_group.setdefault((h["kind"], h["detail"]), []).append(h)
    order = [("live", g) for g, _ in _GROUPS] + [("live", "other")]
    order += sorted(k for k in by_kind_group if k[0] == "mirror")
    if include_records:
        order.append(("record", "record"))
    for key in order:
        group = by_kind_group.get(key)
        if not group:
            continue
        kind, detail = key
        heading = {"live": f"[{detail}]", "mirror": f"[mirror -- edit the SoT, then: {detail}]",
                   "record": "[record -- old names are expected here]"}[kind]
        out.append("")
        out.append(f"{heading}  {len(group)} hit(s)")
        by_path: dict[str, list[dict]] = {}
        for h in group:
            by_path.setdefault(h["path"], []).append(h)
        for path, phits in by_path.items():
            lines = ", ".join(str(h["line"]) for h in phits)
            out.append(f"  {path}  ({len(phits)}): {lines}")
            for h in phits:
                out.append(f"      {h['line']:>5}: {h['text']}")
    out.append("")
    out.append(f"live: {result['live']}   mirror: {result['mirror']}   "
               f"record: {result['record']}"
               + ("" if include_records else "  (records not listed; --include-records)"))
    quiet = result["groups_without_live_hits"]
    if quiet:
        out.append(f"no live hits in: {', '.join(quiet)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="+", help="symbol name(s) to census, matched as whole identifiers")
    ap.add_argument("--root", default=str(_DEFAULT_ROOT), help="repo root (default: this checkout)")
    ap.add_argument("--include-records", action="store_true",
                    help="also list hits on record surfaces (counted either way)")
    ap.add_argument("--json", action="store_true", help="machine-readable census")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    result = census(root, args.names)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render(result, include_records=args.include_records))
    return 1 if result["live"] else 0


if __name__ == "__main__":
    sys.exit(main())
