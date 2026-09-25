"""Shared helper: resolve relative markdown links INSIDE a built artifact.

Not a test module (leading underscore) — no marker classification needed.

The class this exists for is invisible to every other check: the working tree
always resolves, so a doc that links across an exclusion boundary looks fine in
the repo, in the suite, and to ``git grep``. The only oracle that can see it is
one that builds the artifact and resolves links *inside* it.

Calibration lives here rather than in the callers, because getting the
extractor wrong produces false findings that get the guard neutered. Four rules,
each measured against the live population rather than assumed:

1. **Skip fenced code blocks.** A link inside ``` fences renders as literal
   text, so it can never 404. ``memory/README.md`` documents the cross-link
   *format* with a worked example inside a fence; counting it produced two
   phantom findings on the first pass.
2. **Skip template placeholders.** ``memory/<slug>.md`` and a bare ``...`` are
   illustrative spellings, not paths.
3. **Resolve citer-directory first, repo-root second.** A bare ``FOO.md`` inside
   ``docs/CONVENTIONS.md`` means ``docs/FOO.md``. Getting this backwards
   silently drops every same-directory link.
4. **Directories count as present.** A link to ``bench/corpus`` resolves for
   someone who extracted the artifact.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

# A markdown link whose target is relative (not an absolute URL, in-page
# anchor, or mailto:).
_RELATIVE_LINK_RE = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:)([^)\s]+)\)")

# Illustrative spellings that are not paths.
_PLACEHOLDER_RE = re.compile(r"[<>]|^\.\.\.$")


def strip_fenced_blocks(text: str) -> str:
    """Blank out ``` fenced regions, preserving line count for reporting.

    Public so sibling pointer-derivation helpers share one implementation
    rather than adding a fourth copy of the fence walk.
    """
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


def _normalize(joined: Path) -> str | None:
    parts: list[str] = []
    for part in joined.parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts) or None


def iter_relative_links(
    text: str, citer_relpath: str
) -> list[tuple[str, list[str], str]]:
    """Yield ``(raw_target, [candidate resolutions], fragment)`` for one document.

    The third element exists because discarding it made every anchor unvalidatable:
    ``page.md#some-heading`` was checked only as far as ``page.md``, so renaming the
    heading broke the link while every checker in the tree still called it resolved.
    Empty string when the link carries no ``#fragment``.
    """
    results: list[tuple[str, list[str], str]] = []
    base = Path(citer_relpath).parent
    for raw in _RELATIVE_LINK_RE.findall(strip_fenced_blocks(text)):
        target, _, fragment = raw.partition("#")
        target = target.strip()
        if not target or target.startswith("/"):
            continue
        if _PLACEHOLDER_RE.search(target):
            continue
        candidates = [_normalize(base / target)]
        if not target.startswith("."):
            candidates.append(_normalize(Path(target)))
        results.append((target, [c for c in candidates if c], fragment.strip()))
    return results


def artifact_members(root: Path) -> set[str]:
    """Every file AND directory in the extracted artifact."""
    return {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*")}


# The absolute form the front-door docs use: a GitHub file/tree/raw URL into a
# named repository at a named ref. `path` stops at `)`, whitespace or `#`.
_ABSOLUTE_GITHUB_LINK_RE = re.compile(
    r"https://github\.com/(?P<slug>[^/\s)]+/[^/\s)]+)/(?P<kind>blob|tree|raw)/"
    r"(?P<ref>[^/\s)]+)/(?P<path>[^)\s#]+)"
)


def absolute_links_to_unshipped_paths(
    root: Path, slug: str, classify: Callable[[str], str]
) -> tuple[list[str], int]:
    """``(violations, checked)`` for every absolute
    ``https://github.com/<slug>/(blob|tree|raw)/<ref>/<path>`` link inside the
    ``*.md`` files under ``root``.

    The relative arm (``dangling_links``) skips ``https://`` on purpose. This arm
    reads the absolute form the front-door docs use and judges ``<path>``
    through ``classify`` (``espalier.surface_contract.classify_release_path``):
    anything but ``public`` names a path the public repository does not carry,
    so the link 404s exactly like a dangling relative one -- and no other check
    sees it, because the working tree resolves it fine. A directory link
    (``tree/<ref>/<dir>``) is judged by its own path; the files it holds are
    judged when they are linked. Links into OTHER repositories are not this
    arm's question and are not counted. Fenced code is stripped first, as the
    relative arm does. A bare URL that ends a sentence or sits in an autolink
    carries its punctuation into ``path`` (the regex stops at ``)``, whitespace
    or ``#``), so trailing ``.,;:>`` are stripped before judging -- unstripped,
    an unknown path classifies ``public`` and a dead link is counted clean (the
    2026-09-22 code review drove it). Run over the archive index tree only: the
    wheel and the adopter doc payloads are byte-mirrors of the same files
    (``tests/test_deploy_doc_parity.py``), so one population covers all three.
    """
    violations: list[str] = []
    checked = 0
    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = strip_fenced_blocks(path.read_text(encoding="utf-8", errors="replace"))
        for m in _ABSOLUTE_GITHUB_LINK_RE.finditer(text):
            if m.group("slug") != slug:
                continue
            checked += 1
            bucket = classify(m.group("path").rstrip(".,;:>").rstrip("/"))
            if bucket != "public":
                violations.append(f"{rel} -> {m.group(0)} ({bucket})")
    return violations, checked


def dangling_links(
    root: Path, allowlist: dict[str, str]
) -> tuple[list[str], int]:
    """Return ``(violations, resolved_count)`` for an extracted artifact.

    ``allowlist`` maps ``"<citer> -> <target>"`` to a stated reason. Every entry
    must carry one: an exclusion inside a mechanical gate is itself an
    un-tested assertion.
    """
    present = artifact_members(root)
    violations: list[str] = []
    resolved = 0

    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(root)).replace("\\", "/")
        text = path.read_text(encoding="utf-8", errors="replace")
        for target, candidates, _fragment in iter_relative_links(text, rel):
            if any(c in present for c in candidates):
                resolved += 1
                continue
            key = f"{rel} -> {target}"
            if key in allowlist:
                continue
            violations.append(key)

    return violations, resolved
