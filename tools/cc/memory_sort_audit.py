#!/usr/bin/env python3
"""Audit the two-store memory split for re-sort backslide.

The sorting rule in ``docs/MEMORY_SYSTEMS.md`` routes a fact to exactly one
home: operator/machine/collaboration -> Claude Code's machine-local auto
memory; harness/code/discipline -> the committed repo layer (``memory/``,
``docs/``). A one-time re-sort fixes the store; nothing stops the next session
re-opening the gap, because the reflex when asked to "remember" is to write
auto memory. This is the detector for that drift.

Two classes, both calibrated to zero false positives against the live store
(a detector that fires on most of the population is noise, not signal).

What "clean" does and does not cover -- read this before trusting a silent run.
Class 1's silence is carried mostly by the pointer-marker short-circuit, not by
the slug matcher: measured against the 39 auto entries already collapsed to
pointers (each a KNOWN twin), the slug matcher alone re-identifies 10 of 39
(~26%). The two stores routinely name one lesson with disjoint vocabulary
("commit-message-no-internal-language" vs "commit-messages-must-stand-alone"),
and no filename heuristic closes that. So a clean class-1 run means "no
duplicate I can recognize by name," NOT "no duplicate." It is a floor on drift,
not a proof of its absence. Class 2 is exact and repo-local, and is the half to
trust.

  1. ``[duplicated-across-stores]`` -- an auto-memory topic file whose subject
     already has a committed twin, and which is NOT a pointer at that twin.
     The committed-twin set is the whole committed layer the sorting rule
     targets: ``memory/`` entries, ``docs/sharp-edges/`` footguns, and
     ``docs/STANDING_PRINCIPLES.md`` -- each finding names the twin's real home.
     Two full copies of one idea drift apart and neither side knows which is
     current. Note this deliberately does NOT flag "mentions a repo path":
     ~63% of the live store does, most of it legitimate operator context.
  2. ``[unlinked-repo-memory]`` -- a ``memory/*.md`` file whose reverse-link
     header is unsubstantiated: it claims a repo ``ESPALIER_MEMORY.md`` row that
     does not link back (citation rot); or it declares its home ONLY as a
     gitignored/removed path (a dead breadcrumb -- e.g. a landed-and-deleted
     task-pack) that a fresh clone lacks; or it declares no home at all -- and
     in every case nothing in the tracked tree references it. A file that
     honestly declares ``Linked from: (unlinked)``, that is reached via a folder
     router / ``docs/`` / a sibling cross-link, or that carries a durable
     co-home alongside a soft path breadcrumb, is correctly homed and is not
     flagged.

Advisory reporter: always exits 0, prints nothing when clean. It is
deliberately not wired as a blocking gate -- the knowledge store is an
advisory channel, and blocking a session on store tidiness is the wrong
friction.

Stdlib-only; zero espalier imports (``tools/cc/`` runs standalone).

Usage:
    python3 tools/cc/memory_sort_audit.py           # advisory findings, exit 0
    python3 tools/cc/memory_sort_audit.py --repo .  # explicit repo root
"""
from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
from pathlib import Path

# Reuse the cwd->~/.claude/projects resolver rather than inlining a second
# copy: the encoding is PER-CHARACTER, and a re-encode that collapses runs of
# separators computes the wrong dir and silently finds nothing -- which would
# make this audit report "clean" for the wrong reason. Sibling import via
# sys.path, mirroring session_summary.py -> read_summary. read_summary's
# main() is __main__-guarded, so importing it has no side effect.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_summary import _project_dir  # noqa: E402

# Committed project-memory filename, routed through one per-file constant so a
# future rename is a value flip. Per-file (not a shared import) — tools/cc scripts
# run standalone; adding a sibling import risks the copy-subset footgun.
# NOTE: the auto-memory index guard below (entry.name == "MEMORY.md") names a
# DIFFERENT file — Claude's machine-local store — which keeps its literal name.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

# Files in memory/ that document the convention rather than being an entry.
_NON_ENTRY = {"README.md", "CLAUDE.md"}

# A machine-local note collapsed to a pointer at its committed twin announces
# itself with one of these markers, in the blockquote-bold form the convention
# specifies (docs/MEMORY_SYSTEMS.md). Both spellings are live in the store;
# matching only one silently misreads every note using the other as an
# un-migrated duplicate. Matching is anchored to the marker's own line rather
# than the whole body, so a note that merely DISCUSSES the migration convention
# in prose does not exempt itself from class 1.
_POINTER_MARKERS = ("Migrated to the repo", "Canonized in the repo")
_POINTER_LINE_RE = re.compile(
    r"^\s*>?\s*\*\*(?:" + "|".join(re.escape(m) for m in _POINTER_MARKERS) + r"):\*\*",
    re.MULTILINE,
)

# Reverse-link header the memory/ convention requires (memory/README.md).
# DOTALL on purpose: a claim may wrap across continuation lines, and a
# line-bounded `.` would truncate at the first newline -- silently skipping
# verification of anything on line 2+ and reporting clean for the wrong reason.
# Bounded by the caller to the first _HEADER_LINES lines of the file.
_LINKED_FROM_RE = re.compile(r"\*\*Linked from:\*\*(.*)", re.DOTALL)

# How many leading lines of an entry the header must appear within, matching
# the convention test (tests/test_categorized_memory_layout.py).
_HEADER_LINES = 10

# Slug-similarity threshold for calling two entries the same subject. The two
# stores name the same lesson slightly differently ("verify-pack-scope-out-
# rationale" vs "verify-a-packs-scope-out-rationale"), so an exact match alone
# under-reports; requiring >=3 shared MEANINGFUL tokens AND >60% overlap of the
# shorter slug keeps a pair like "fix-the-pack-and-proceed" / "fix-the-pack-and-
# stop" from false-merging on function words alone. The stopword set is what
# makes that true -- without it, three shared articles clear the bar.
_SLUG_STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "not", "to", "of", "and", "or", "for",
     "in", "on", "it", "its", "be", "as", "at", "by", "with"}
)
_MIN_SHARED_TOKENS = 3
_MIN_OVERLAP_RATIO = 0.6


def _read(path: Path) -> str:
    """File text, or empty string if unreadable (fail-soft: an advisory audit
    must never crash the caller over one bad file)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _same_subject(slug_a: str, slug_b: str) -> bool:
    """True when two entry slugs name the same lesson."""
    if slug_a == slug_b:
        return True
    tokens_a = set(slug_a.split("-")) - _SLUG_STOPWORDS
    tokens_b = set(slug_b.split("-")) - _SLUG_STOPWORDS
    shared = tokens_a & tokens_b
    if len(shared) < _MIN_SHARED_TOKENS:
        return False
    return len(shared) / max(1, min(len(tokens_a), len(tokens_b))) > _MIN_OVERLAP_RATIO


# Heading -> slug for the monolithic-doc twin arm. Only ##/### headings
# (deeper levels are structural sub-points, not lesson titles). Strip backticks,
# punctuation, and a leading section number so "## 13.7 `git checkout <file>`
# nukes uncommitted work" -> "git-checkout-file-nukes-uncommitted-work",
# comparable to an auto-memory slug via _same_subject.
_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)

# Headings excluded from the monolithic-doc twin set. Two kinds:
#   (a) structural scaffolding, not a lesson title (a 1-2 token heading like
#       "Scope" / "See also" is already gated by the >= _MIN_SHARED_TOKENS floor
#       below; the (a) entries are PRE-EMPTIVE guards for 3+-token scaffolding
#       headings -- none collide in the 4 docs today, they keep a future
#       "## Table of contents"-style heading from becoming a phantom twin);
#   (b) a CONVENTION/architecture heading that shares subsystem vocabulary with a
#       DISTINCT auto-memory footgun and would false-match it. Example: the
#       state_cache convention heading below shares {state,cache,freshness,check,
#       writes} with the note `freshness-check-writes-state-cache-git-stash-
#       strands-work` (a git-stash footgun, a different lesson, not canonized in
#       CONVENTIONS.md) -- a coincidental token overlap, not a real duplicate.
#       This one IS live: it is pinned by a regression test (see
#       tests/test_memory_sort_audit.py::test_convention_heading_collision_suppressed).
# Calibrated to FP=0 against the live store. To fix a future collision,
# EXTEND this set (name the exact heading slug); never lower the token floor.
_GENERIC_HEADINGS = frozenset(
    {
        # (a) pre-emptive scaffolding guards (not observed in the 4 docs today):
        "table-of-contents",
        "how-to-use-this-doc",
        "how-to-read-this",
        # (b) convention-vs-footgun collision, verified live + regression-pinned:
        "consumers-read-state-cache-only-freshness-check-writes-it",
    }
)


# The monolithic docs the sorting rule routes harness lessons into, keyed by
# section heading. If a future doc split relocates a section registry out of one
# of these (e.g. carving CONVENTIONS.md's invariant registry into its own file),
# that new file MUST be added here too, or every relocated section becomes an
# un-twinned (false-clean) duplicate surface.
_MONOLITHIC_TWINS = (
    "docs/SHARP_EDGES.md",
    "docs/FAILURE_MODES.md",
    "docs/CONVENTIONS.md",
    "docs/AUTONOMOUS_EXECUTION.md",
)


def _section_slugs(text: str) -> list[str]:
    """The ##/### headings of a monolithic doc, slugified to the same shape as an
    auto-memory filename stem. Each surviving slug is a twin subject: a lesson
    that lives inside the doc under that heading. Filtered to >= _MIN_SHARED_TOKENS
    content tokens (a shorter heading cannot clear _same_subject's shared-token
    floor anyway) and past the generic-heading stop-set, so structural scaffolding
    ("Scope", "Overview") never becomes a phantom twin."""
    slugs: list[str] = []
    for raw in _HEADING_RE.findall(text):
        s = raw.lower().replace("`", "")
        # Drop a leading numeric section number ("13.7 ...", "1.20 ..") so the
        # slug is the lesson title, not the numbering.
        s = re.sub(r"^\d[\d.\-]*\s+", "", s)
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        content = [t for t in s.split("-") if t and t not in _SLUG_STOPWORDS]
        if s and s not in _GENERIC_HEADINGS and len(content) >= _MIN_SHARED_TOKENS:
            slugs.append(s)
    return slugs


def _tracked_files(repo: Path) -> list[str]:
    """Repo-relative tracked paths, or [] outside a work tree (fail-soft)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line]


def _has_inbound_link(repo: Path, entry: Path, tracked: list[str]) -> bool:
    """True when any OTHER tracked file references ``entry`` by filename or by
    ``[[slug]]`` wiki-link."""
    rel = f"memory/{entry.name}"
    wiki = f"[[{entry.stem}]]"
    for tracked_rel in tracked:
        if tracked_rel == rel:
            continue
        body = _read(repo / tracked_rel)
        if not body:
            continue
        if entry.name in body or wiki in body:
            return True
    return False


# A **Linked from:** home is "dead" for a fresh cloner when its declared PATH
# target is not a tracked file (gitignored, removed after landing, or a typo).
# Extract ONLY explicit path syntax -- a markdown-link target `](path)` or a
# backtick-quoted path containing a slash -- so a prose sentence that happens to
# contain slashes (a cool-store note, a run of ids) is never misread as a broken
# home. A bare "CLAUDE.md" is deliberately NOT treated as a path: the rule
# under-flags (safe) rather than guessing at prose.
_PATH_HOME_RE = re.compile(r"\]\(([^)]+)\)|`([^`]+/[^`]+)`")


def _extract_path_homes(claim: str) -> list[str]:
    """The path targets a ``Linked from:`` claim declares as the entry's home:
    markdown-link targets and backtick-quoted slash paths. URLs and pure in-doc
    anchors are not repo homes and are dropped."""
    homes: list[str] = []
    for md, backtick in _PATH_HOME_RE.findall(claim):
        raw = (md or backtick).strip().split("#", 1)[0].strip()
        if raw and not raw.startswith(("http://", "https://", "mailto:")):
            homes.append(raw)
    return homes


def _is_dead_path(home: str, tracked: set[str]) -> bool:
    """True when a declared path-home resolves to no tracked file (nor a tracked
    directory) -- a gitignored / removed / mistyped target a fresh clone lacks.
    Keys off the TRACKED set, not local existence, so a gitignored file present
    on this machine is still correctly 'dead' for a cloner. ``Linked from:``
    lives in ``memory/*.md``, so a leading ``../`` is resolved relative to
    ``memory/`` as well as the repo root; if either resolution is tracked (a
    file or a directory prefix), the home is alive."""
    for base in ("memory", ""):
        rel = posixpath.normpath(posixpath.join(base, home))
        if rel in (".", "") or rel.startswith(".."):
            continue
        if rel in tracked:
            return False
        prefix = rel.rstrip("/") + "/"
        if any(t.startswith(prefix) for t in tracked):  # a tracked directory
            return False
    return True


def _audit_duplicates(repo: Path) -> list[str]:
    """Class 1 -- an auto-memory entry duplicating a committed twin."""
    auto_dir = _project_dir(repo) / "memory"
    if not auto_dir.is_dir():
        # "Nothing to audit" and "clean" are different results that would
        # otherwise render identically as silence. A fresh clone, a second
        # machine, CI, or a changed CC projects layout all land here -- say so
        # on stderr (stdout stays the findings channel; exit stays 0) so a
        # silent run is never misread as a verified-clean one.
        # ASCII only: runtime prints are portability-contract'd
        # (tests/test_portability_contract.py) for native-Windows consoles.
        print(
            f"[memory_sort_audit] no machine-local store at {auto_dir} -- "
            f"cross-store duplicate check (class 1) not audited",
            file=sys.stderr,
        )
        return []
    # The committed layer spans memory/ AND the docs/ homes the sorting rule
    # routes harness lessons to (docs/MEMORY_SYSTEMS.md: "harness/code/
    # discipline -> the committed repo layer (memory/, docs/)"). Globbing only
    # memory/ left a fail-open: an auto note duplicating a docs/sharp-edges/ or
    # STANDING_PRINCIPLES twin was never flagged, contradicting the docstring.
    # Each twin carries its display path so the finding points at the real home.
    # Calibrated 0-FP against the live store. Re-run the calibration (extend
    # _GENERIC_HEADINGS, never lower the token floor) before adding a fifth
    # monolithic doc or relocating a section registry into its own new file
    # (which must also be added to _MONOLITHIC_TWINS above).
    twins: list[tuple[str, str]] = []
    for p in sorted((repo / "memory").glob("*.md")):
        if p.name not in _NON_ENTRY:
            twins.append((p.stem, f"memory/{p.name}"))
    for p in sorted((repo / "docs" / "sharp-edges").glob("*.md")):
        if p.name not in _NON_ENTRY:
            twins.append((p.stem, f"docs/sharp-edges/{p.name}"))
    # Exact-filename tripwire, not a fuzzy match: "standing-principles" is a
    # 2-token slug, below _MIN_SHARED_TOKENS, so only a byte-exact auto entry
    # matches (via the _same_subject equality short-circuit). Guarded on
    # existence so a rename auto-drops it like the globbed arms above -- never a
    # phantom twin naming a doc that no longer exists.
    if (repo / "docs" / "STANDING_PRINCIPLES.md").is_file():
        twins.append(("standing-principles", "docs/STANDING_PRINCIPLES.md"))
    # Monolithic docs carry many lessons under ##/### headings; each heading is a
    # twin subject. The per-file docs/ arms above are blind to these, so an auto
    # note duplicating a SHARP_EDGES.md / FAILURE_MODES.md / CONVENTIONS.md /
    # AUTONOMOUS_EXECUTION.md section read false-clean: the sorting rule routes
    # footguns/failure-modes HERE, but the twin-scan never read them.
    for rel in _MONOLITHIC_TWINS:
        doc = repo / rel
        if not doc.is_file():
            continue
        for heading in _section_slugs(_read(doc)):
            twins.append((heading, rel))
    findings: list[str] = []
    for entry in sorted(auto_dir.glob("*.md")):
        if entry.name == "MEMORY.md":
            continue  # the index, not an entry
        if _POINTER_LINE_RE.search(_read(entry)):
            continue  # already collapsed to a pointer -- correctly sorted
        for slug, twin_path in twins:
            if _same_subject(entry.stem, slug):
                findings.append(
                    f"[duplicated-across-stores] auto-memory {entry.name} "
                    f"duplicates committed {twin_path} -- collapse the "
                    f"machine-local copy to a pointer (docs/MEMORY_SYSTEMS.md: "
                    f"one home per fact)"
                )
                break
    return findings


def _audit_unlinked(repo: Path) -> list[str]:
    """Class 2 -- a committed memory/ entry whose reverse link is unsubstantiated."""
    index = _read(repo / _MEMORY_FILENAME)
    tracked = _tracked_files(repo)
    tracked_set = set(tracked)
    findings: list[str] = []
    for entry in sorted((repo / "memory").glob("*.md")):
        if entry.name in _NON_ENTRY:
            continue
        header = "\n".join(_read(entry).splitlines()[:_HEADER_LINES])
        match = _LINKED_FROM_RE.search(header)
        indexed = f"({entry.name})" in index or f"memory/{entry.name}" in index
        if match is None:
            # No declared home. Only a finding if nothing else reaches it.
            # `tracked` empty => not a work tree (or git unavailable): the
            # inbound-link scan has nothing to read, so _has_inbound_link is
            # False for EVERY entry and this branch would call each one
            # orphaned. Fail soft and skip -- matching the dead-path branch
            # below and _tracked_files' documented fail-soft contract.
            if tracked and not _has_inbound_link(repo, entry, tracked):
                findings.append(
                    f"[unlinked-repo-memory] memory/{entry.name} declares no "
                    f"'**Linked from:**' home and nothing in the tracked tree "
                    f"references it -- orphaned from every recall path"
                )
            continue
        claim = match.group(1)
        if f"{_MEMORY_FILENAME} row" in claim and not indexed:
            findings.append(
                f"[unlinked-repo-memory] memory/{entry.name} claims a {_MEMORY_FILENAME} "
                f"row, but {_MEMORY_FILENAME} has no link back to it -- citation rot; "
                f"repoint the claim or restore the index row"
            )
            continue
        # A declared home made up ONLY of dead path target(s) is not a home: a
        # gitignored/removed path (e.g. a landed-and-deleted task-pack) a fresh
        # clone lacks. Fall through to the same reachability check as a
        # headerless entry -- a durable co-home (a live path) or any inbound
        # link keeps it homed; a SOLE dead breadcrumb with nothing else
        # reaching it is orphaned (the broader case collapse-adds-... instanced,
        # via a path target instead of a session-row claim).
        # `tracked_set` empty => not a work tree (or git unavailable): the
        # dead-path test cannot distinguish a removed path from a live one, so
        # fail soft and skip it rather than manufacture a false positive.
        homes = _extract_path_homes(claim)
        if tracked_set and homes and all(_is_dead_path(h, tracked_set) for h in homes):
            if not indexed and not _has_inbound_link(repo, entry, tracked):
                findings.append(
                    f"[unlinked-repo-memory] memory/{entry.name} declares its home "
                    f"only as gitignored/removed path(s) {homes} that a fresh clone "
                    f"lacks, and nothing else references it -- dead breadcrumb; "
                    f"repoint to a durable home"
                )
    return findings


def audit(repo: Path) -> list[str]:
    """Every drift finding for ``repo``, both classes, in stable order."""
    return _audit_duplicates(repo) + _audit_unlinked(repo)


def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            # .resolve() in BOTH branches: _project_dir encodes the path
            # STRING per-character, so an unresolved-vs-resolved mismatch
            # between the two invocation forms computes a different
            # ~/.claude/projects/<enc> dir -- which does not exist, which
            # returns no findings, which reads as clean.
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError, ValueError):  # strict decode: a structured answer (DEF-821)
        pass
    return Path.cwd().resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the two-store memory split for re-sort backslide."
    )
    parser.add_argument("--repo", default=None, help="repo root (default: git toplevel)")
    args = parser.parse_args(argv)

    for finding in audit(_repo_root(args.repo)):
        print(finding)
    return 0  # advisory reporter: never blocks, even with findings


if __name__ == "__main__":
    sys.exit(main())
