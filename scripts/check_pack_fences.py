#!/usr/bin/env python3
"""Resolve a pack's PRESCRIBED python fences against the module they land in.

A pack writes code that does not exist yet, against a module it is not part of.
Nothing type-checks it, nothing imports it, and ``ruff`` never sees it -- so a
prescribed snippet can reference a name the target module has no way to resolve,
and the defect only surfaces as a ``NameError`` after someone pastes it in. That
is not hypothetical: one pack prescribed ``os.pathsep``/``os.environ`` for
``espalier/cli.py``, where ``os`` is never imported (it appears once, inside a
comment). A ``NameError`` plus ``ruff F821``, caught by nobody.

What this checks
----------------
For each fence tagged ``python target=<path>``: parse it, collect the names it
*reads* but never *binds*, and ask whether the target module binds them anywhere.

Deliberately an "anywhere in the module" test, not a scope-accurate one. A
prescribed fence is usually a fragment destined for the inside of some function,
and its insertion point is unknown here -- so a scope-accurate check would flag
every reference to an enclosing function's local as unresolvable. The same pack
above reads ``subprocess``, which ``cli.py`` imports only *inside* two functions;
a module-level-only scan would have called that a defect. Over-approximating the
target namespace makes the check quiet and keeps what it does say true: a name
bound NOWHERE in the target is certainly unresolvable there.

Why the tag is required
-----------------------
A pack quotes existing source and prescribes new source in the same syntax, and
no scanner can separate them without a convention that marks which is which --
so an untagged fence is reported as SKIPPED, never as clean. The
``blueprint-authoring`` skill defines the tag (section *Code-fix output format*).
``--infer`` guesses a target from the nearest preceding backticked ``.py`` path;
it is OFF by default, and the calibration behind that default is recorded in
``## Coverage`` below.

Coverage is always printed. A checker that silently examines nothing reads
exactly like a clean bill of health -- ``docs/FAILURE_MODES.md`` §13.20.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import re
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Opening fence: 3+ backticks, optional language, optional info string.
_FENCE_RE = re.compile(r"^(?P<ticks>`{3,})(?P<lang>[A-Za-z0-9_+-]*)(?P<info>[^\n]*)$")
#: ``target=path`` / ``target="path"`` in a fence info string.
_TARGET_RE = re.compile(r"""target=(?P<q>["']?)(?P<path>[^\s"']+)(?P=q)""")
#: A backticked path ending .py, for --infer.
_PATH_HINT_RE = re.compile(r"`([\w./-]+\.py)`")

_BUILTINS = frozenset(dir(builtins)) | {"__file__", "__name__", "__doc__"}


class Fence:
    __slots__ = ("lineno", "lang", "target", "body", "inferred")

    def __init__(self, lineno: int, lang: str, target: str | None, body: str,
                 inferred: bool = False):
        self.lineno, self.lang, self.target, self.body = lineno, lang, target, body
        #: True when ``target`` is this script's guess rather than the author's
        #: declaration. An unresolvable GUESS is our failure, not the pack's, and
        #: must never be reported as a finding against the pack.
        self.inferred = inferred


#: Directories that never hold a prescribed target, skipped when resolving a
#: bare basename to a repo path.
#: ``.venv/`` and friends are in .gitignore -- this repo EXPECTS in-tree
#: virtualenvs, and the release walk creates one. A non-editable install puts a
#: second espalier/cli.py under it, which would make a bare-basename target read
#: `ambiguous` on one machine and `ok` on another: a verdict that depends on the
#: developer's tree, which is this repo's autonomous-green-is-env-relative edge.
_RESOLVE_SKIP = ("task-packs/", ".git/", "__pycache__/", "espalier/_vendor/",
                 "espalier/assets/", "examples/", "build/", "dist/",
                 ".venv/", "venv/", "env/", ".tox/", "node_modules/")


def resolve_target(rel: str) -> tuple[Path | None, str]:
    """Resolve a fence target to a real file. Returns ``(path, status)``.

    Packs overwhelmingly cite a bare basename (``cli.py``) rather than a
    repo-relative path, so a literal ``root / rel`` test answers "does not
    exist" for a file that plainly does. Measured: on the Done corpus that
    single shortcut accounted for 95 of 123 reports -- and it is why the one
    pack carrying a KNOWN real defect was never checked at all.

    A basename matching more than one file is ``ambiguous`` and is NOT resolved
    to a guess; picking one would make the answer depend on walk order.
    """
    direct = _ROOT / rel
    if direct.is_file():
        return direct, "ok"
    if "/" in rel:
        return None, "missing"
    # Segment match, not substring: `"build/" in "prebuild/helper.py/"` is True,
    # so a substring test would skip a real file under a future `prebuild/` and
    # then report a well-formed pack's declared target as missing -- a false BLOCK
    # by a different route.
    _skip = {s.rstrip("/") for s in _RESOLVE_SKIP}
    hits = [
        p for p in _ROOT.rglob(rel)
        if not (_skip & set(p.relative_to(_ROOT).parts))
    ]
    if len(hits) == 1:
        return hits[0], "ok"
    return None, "ambiguous" if hits else "missing"


def iter_fences(md_text: str, *, infer: bool = False) -> list[Fence]:
    """Every fenced block, with nesting handled by backtick-run length.

    A fence closes only on a run at least as long as the one that opened it --
    which is what lets a pack wrap a ```python example inside a ````markdown
    block. Matching on any run of three would end the outer fence at the inner
    one and silently truncate every example that uses the documented form.
    """
    out: list[Fence] = []
    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        ticks = m.group("ticks")
        lang = (m.group("lang") or "").lower()
        info = m.group("info") or ""
        j = i + 1
        while j < len(lines):
            c = _FENCE_RE.match(lines[j])
            if c and len(c.group("ticks")) >= len(ticks) and not c.group("lang"):
                break
            j += 1
        body = "\n".join(lines[i + 1: j])
        target, inferred = None, False
        tm = _TARGET_RE.search(info)
        if tm:
            target = tm.group("path")
        elif infer and lang in ("python", "py"):
            inferred = True
            # Nearest preceding backticked .py path, within a bounded look-back.
            for k in range(i - 1, max(-1, i - 25), -1):
                hits = _PATH_HINT_RE.findall(lines[k])
                if hits:
                    target = hits[-1]
                    break
        if lang in ("python", "py"):
            out.append(Fence(i + 1, lang, target, body, inferred))
        else:
            # Descend. The authoring skill's own example form wraps a ```python
            # prescription inside a ````markdown block, so treating the outer
            # fence as opaque hides exactly the fences worth checking. Safe
            # because nothing is checked without a `target=` tag: a meta-example
            # that merely shows what a fence looks like stays untagged and is
            # skipped, the same as any other untagged fence.
            for inner in iter_fences(body, infer=infer):
                out.append(Fence(inner.lineno + i + 1, inner.lang, inner.target,
                                 inner.body, inner.inferred))
        i = j + 1
    return out


def bound_names(tree: ast.AST) -> set[str]:
    """Every name bound ANYWHERE in ``tree`` -- imports, defs, args, stores.

    Over-approximates on purpose; see the module docstring.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.alias) and node.asname:
            names.add(node.asname)
        # Structural pattern matching binds OUTSIDE the Name/Store walk: a bare
        # capture (`case [a, b]:`), a star pattern (`case {**rest}:`) and a
        # mapping's rest all bind without producing a Store Name. Missing them
        # reports a fence's own capture as unbound in the target -- a false
        # BLOCK, which is the one failure this checker cannot afford.
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def free_names(tree: ast.AST) -> set[str]:
    """Names read but never bound inside ``tree``."""
    loaded = {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return loaded - bound_names(tree) - _BUILTINS


def check_pack(pack: Path, *, infer: bool = False) -> tuple[list[str], dict[str, int]]:
    """Return ``(findings, coverage)``."""
    findings: list[str] = []
    cov = {"total": 0, "checked": 0, "skipped": 0, "unparseable": 0, "no_target": 0}
    text = pack.read_text(encoding="utf-8")
    for fence in iter_fences(text, infer=infer):
        cov["total"] += 1
        if not fence.target:
            cov["skipped"] += 1
            continue
        tpath, status = resolve_target(fence.target)
        if tpath is None:
            cov["no_target"] += 1
            # Only a DECLARED target can be wrong. An inferred one that does not
            # resolve is this script guessing badly, and reporting it as a pack
            # defect is how a checker manufactures its own false-positive rate.
            if not fence.inferred:
                findings.append(
                    f"{pack.name}:{fence.lineno}  declared target is {status}: "
                    f"{fence.target}"
                )
            continue
        try:
            # Dedent first. A prescribed fence is usually a FRAGMENT lifted from
            # inside a function, so it carries that function's base indent and
            # `ast.parse` rejects it with "unexpected indent" at line 1. Measured:
            # on the very pack this check exists to have caught, both
            # tagged fences failed exactly that way and were written off as
            # unparseable, which is the checker declining to look at the only
            # thing it was built for.
            fence_tree = ast.parse(textwrap.dedent(fence.body))
        except SyntaxError:
            # A fragment (a bare `elif`, a dangling `)`) is not a defect -- it is
            # a snippet whose enclosing context the pack shows in prose. Counted,
            # never asserted about.
            cov["unparseable"] += 1
            continue
        try:
            target_tree = ast.parse(tpath.read_text(encoding="utf-8"))
        except (SyntaxError, OSError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError subclasses ValueError, NOT OSError -- without it
            # a non-UTF-8 target raises a raw traceback instead of a finding.
            findings.append(f"{pack.name}:{fence.lineno}  cannot parse target: {exc}")
            continue
        cov["checked"] += 1
        missing = sorted(free_names(fence_tree) - bound_names(target_tree))
        for name in missing:
            findings.append(
                f"{pack.name}:{fence.lineno}  '{name}' is not bound anywhere in "
                f"{fence.target} -- prescribed code would raise NameError "
                f"(and trip ruff F821)"
            )
    return findings, cov


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Resolve a pack's prescribed python fences against their "
                    "target modules.",
    )
    ap.add_argument("packs", nargs="+", help="TP-*.md paths")
    ap.add_argument(
        "--require-coverage", action="store_true",
        help="exit 2 when no fence was actually resolved -- for automation, which "
             "cannot read the coverage line the way a human can",
    )
    ap.add_argument(
        "--infer", action="store_true",
        help="guess an untagged fence's target from the nearest preceding "
             "backticked .py path (OFF by default -- see the module docstring)",
    )
    ns = ap.parse_args(argv)

    if ns.infer:
        # The number, not an adjective. Measured 2026-08-07 over the 167-pack
        # Done corpus: --infer resolved 134 fences and every finding classified by
        # hand (8 of them, across two packs) was a FALSE positive -- a quoted
        # snippet read as prescribed, or a guessed target that was simply the
        # wrong file. It also failed to surface the one pack carrying a known
        # real defect. Treat its output as leads to read, never as a gate.
        print(
            "WARNING: --infer guesses targets. Calibrated over the Done corpus, "
            "every hand-classified finding it produced was a false positive, and "
            "it missed the one known true defect. Read its output as leads, not "
            "as a verdict.",
            file=sys.stderr,
        )

    all_findings: list[str] = []
    totals = {"total": 0, "checked": 0, "skipped": 0, "unparseable": 0, "no_target": 0}
    for raw in ns.packs:
        p = Path(raw)
        if not p.is_file():
            print(f"missing pack: {raw}", file=sys.stderr)
            return 1
        findings, cov = check_pack(p, infer=ns.infer)
        all_findings.extend(findings)
        for k, v in cov.items():
            totals[k] += v

    # Always, even on a clean run: silence and "nothing was examined" must not
    # look the same.
    print(
        f"fences: {totals['total']} python  |  {totals['checked']} checked  |  "
        f"{totals['skipped']} skipped (untagged)  |  "
        f"{totals['unparseable']} unparseable fragment(s)  |  "
        f"{totals['no_target']} bad target"
    )
    if not totals["checked"]:
        # Unconditional on `checked`, not on `total`. Gating this on "there were
        # some fences" silenced it in the one case where it is most obviously
        # true -- a pack with no python fences at all -- and a checker that
        # examines nothing must never read the same as one that found nothing.
        print(
            "  NOTE: NOTHING WAS RESOLVED -- no fence carried a `target=` tag. "
            "This is NOT a clean bill of health. Tag prescribed fences per the "
            "blueprint-authoring skill, or re-run with --infer."
        )
        if ns.require_coverage:
            print(
                "  --require-coverage was set and coverage is zero -> exit 2",
                file=sys.stderr,
            )
            return 2
    for f in all_findings:
        print(f"BLOCK  {f}")
    return 1 if all_findings else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
