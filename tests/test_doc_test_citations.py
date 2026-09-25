"""Phantom-citation contract — every doc→test-file citation must resolve.

**The rot class this closes.** Authoritative docs cite test files by name to say
"this rule is enforced by `tests/test_X.py`". Those citations are unchecked prose:
when a test is renamed or consolidated, the citation silently rots into a *phantom*
— a confident pointer to a file that no longer exists. Isolated, each is a nit;
as a class it erodes the docs' credibility as a map of what is actually enforced.
This contract makes the class mechanical: scan the authoritative doc surfaces for
backtick-wrapped ``tests/test_*.py`` citations and assert each resolves against
``git ls-files``.

**Calibration (load-bearing — per the ``calibrate-enforcement-contract-against-
live-population`` lesson).** A naive "any backtick ``tests/test_*.py`` in docs/"
scanner false-positives on records that legitimately *name* a phantom. The detector
was probed over the live tree and tuned to zero false-positives via two exclusions,
each verified against a concrete live site:

  * **Record-file excludes** — findings ledgers and the append-only history archive
    quote phantoms as *data*, not as live claims; rewriting a dated historical row
    to a renamed test would falsify the record. Excluded:
    ``RELEASE_FINDINGS_LEDGER.md``, ``session-archive.md`` (+ the ``reports/`` and
    ``task-packs/`` trees, which hold deep-review reports and pack drafts).
  * **Illustrative / negated citations** — a citation is skipped when its line OR
    the line immediately above it (code-spans stripped first, so filenames like
    ``test_no_unvalidated_*`` don't self-trigger) carries a negation/hypothetical
    token. This distinguishes live claims from: "has **no** companion `X`"
    (FAILURE_MODES.md), "Adding `X` **without** ..." (SHARP_EDGES.md), "real paths
    (`a`, **not** `test_example.py`)" (docs-maintainer.md).

Scope is FILE existence (the load-bearing signal a rename/removal breaks). ``::Class``
suffixes are tolerated but not resolved — a possible future tightening.

**``full_tree`` (``tests/conftest.py::_FULL_TREE_NODEIDS``), narrowly.** Resolution is
against ``git ls-files``. This module was registered whole on the belief that a
shipping export prunes ``tests/`` to a curated subset; the release archive ships
every tracked ``tests/`` path, and on a seeded export the resolver answers, so
only the one test that red there stays registered (measured 2026-09-23). Fail-closed:
if ``git ls-files`` yields nothing, SKIP rather than pass vacuously.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Authoritative doc surfaces. Folder CLAUDE.md routers are authoritative too, so the
# whole CLAUDE.md ladder is swept (not just the root). ``bench/`` (the release-gating
# adversarial benchmark) and ``examples/README.md`` cite real enforcement tests and were
# added here to close a live enumeration-integrity gap — see ``TestSweepCompleteness``,
# which pins that every citation-bearing tracked surface stays inside this set.
_SCAN_GLOBS = (
    "docs/**/*.md", "memory/**/*.md", ".claude/**/*.md", "**/CLAUDE.md",
    "README.md", "ESPALIER_MEMORY.md", "CONTRIBUTING.md", "cc/**/*.md", "tests/README.md",
    "bench/**/*.md", "examples/README.md",
    # CHANGELOG.md is swept, NOT exempted as a record surface, because the
    # sibling contract already decided this: tests/test_doc_source_citations.py
    # sweeps it today (126 docs, CHANGELOG among them) and is green, so this repo
    # already requires CHANGELOG's PRODUCTION-source citations to resolve.
    # Leaving its TEST citations unswept made the two gates disagree about the
    # same file, and TestSweepCompleteness reds on exactly that gap. The cost is
    # real and accepted here rather than hidden: renaming a cited test forces an
    # edit to a dated entry. Weigh that against the alternative before moving it
    # to _EXCLUDE_FILES -- doing so would also be the honest place to record that
    # CHANGELOG is a record surface, which would then argue for adding it to
    # test_doc_source_citations._RECORD_SURFACE_DOCS too, since one file should
    # not be a record for one citation kind and a live surface for the other.
    "CHANGELOG.md",
)
_EXCLUDE_PREFIXES = ("reports/", "task-packs/")
_EXCLUDE_FILES = frozenset({
    "docs/RELEASE_FINDINGS_LEDGER.md",
    "docs/session-archive.md",
})

# ── Enumeration-integrity residue (``TestSweepCompleteness``). ``_SCAN_GLOBS`` is a
# hand-maintained set, so a new citation-bearing doc surface added OUTSIDE it rots
# silently — a whole sibling surface goes unswept while the phantom check passes green
# (the DOMINANT enumeration-integrity class: a flat presence check cannot see an
# absence). The completeness contract reds on any such gap. This is the small residue it
# tolerates: tracked ``.md`` that legitimately carries citation-shaped text yet is NOT a
# live doc surface to sweep. Each entry has a MECHANICAL backstop or a not-a-doc-surface
# rationale — it is deliberately NOT a second hand-list of authoritative doc surfaces
# (that would be the same class one level up); the authoritative set is derived, and only
# these backed exclusions are subtracted.
_COMPLETENESS_EXCLUDED_PREFIXES = (
    "espalier/assets/",   # generated byte-mirror of .claude/+docs/: the SOURCE is swept and
                          # tests/test_package_resource_parity.py pins the copy byte-for-byte,
                          # so the citations here are transitively covered.
    "examples/",          # adopter-facing reference. examples/dogfooding/.claude is that same
                          # parity-pinned mirror; examples/golden + examples/dogfooding/contracts
                          # carry deliberately-illustrative golden-path test names that never
                          # resolve. examples/README.md IS swept (a real citation) via _SCAN_GLOBS.
    "tests/fixtures/",    # scanner corpus: these .md fixtures embed citation-shaped strings as
                          # TEST INPUT for other scanners, not as live doc claims.
)

# group(1) = the `.py` file; group(2) = the ``::Symbol`` chain (or None) so the resolver
# can validate the symbol, not just the file — the rot class "file exists but the cited
# symbol was renamed/moved" (e.g. a class cited at the wrong test file).
#
# TP-373 3-B: the group(2) char class excludes ``.``, so a dotted ``::Class.member`` citation
# does not match this regex at all (the dot terminates the pattern before the closing backtick).
# TP-373 2-D closed Finding E at the PROSE layer — it dropped the phantom member and cites the
# bare class, which DOES resolve through the group(2) branch below.
#
# TP-394 1-A — THE STATED REASON FOR DEFERRING THE MEMBER-LEVEL ARM WAS FALSE, and it sat here
# as a committed fact for two sessions. The claim was that a *tracked* record-file compaction
# summary (``cc/blueprints/compact_summaries/*.md``) already quoted a historical
# ``::Class.member`` whose class was since removed, so a dotted resolver would false-flag it.
# Measured: ``cc/blueprints/`` is gitignored (.gitignore:71) and ``git log --all -- cc/blueprints/``
# is EMPTY — the path has never been tracked in the repo's entire history, not merely untracked
# today. This sweep filters to tracked files, so the blocker never existed. Nothing was blocked;
# a one-line premise nobody grepped deferred a small, closable sub-task.
#
# The member-level arm is implemented below (TP-394 1-D). Its live population is deliberately
# tiny: the literal ``::Class.member`` in ESPALIER_MEMORY.md is a meta-reference to the citation
# SYNTAX and is exempt by exact literal (not by a path-wide exclusion — a path exclusion is the
# latent hand-list this repo has canon about), and the one real phantom it was written to catch
# was fixed by TP-394 1-C. A third dotted citation lived in the fan-out dedup corpus (retired
# to the record branch 2026-09-21), which sat in ``_EXCLUDE_FILES`` below because it quoted
# findings VERBATIM, phantom citations included, and rewriting an entry would falsify the record.
# The remaining exclusions are deliberate and are why this arm is "green over its swept population", not
# "green tree-wide" — the distinction is load-bearing, see TP-394 pass criterion 2.
# ``.`` is inside group 2's class so a ``::Class.member`` citation MATCHES. Without it the
# member text sits between the symbol and the closing backtick, the whole pattern fails, and
# the citation is silently SKIPPED rather than flagged — a dotted phantom was invisible, not
# mis-resolved. Widening the class is therefore the load-bearing half; the member resolver
# below is useless behind a regex that never hands it anything.
_CITATION_RE = re.compile(r"`((?:tests/)?test_[A-Za-z0-9_]+\.py)(?:::([A-Za-z0-9_.:]+))?`")
_CODESPAN_RE = re.compile(r"`[^`]*`")
_NEGATION_RE = re.compile(
    r"\b(?:not|without|no|e\.g|example|examples|hypothetical|imagine)\b", re.IGNORECASE
)


def _tracked_files() -> set[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {line.replace("\\", "/") for line in out.stdout.splitlines() if line.strip()}


def _normalize(cited: str) -> str:
    return cited if cited.startswith("tests/") else f"tests/{cited}"


_symbol_cache: dict[str, frozenset[str]] = {}


def _defined_names(rel: str) -> frozenset[str]:
    """Top-level + nested names a citation's ``::Symbol`` may anchor to: class/func
    defs AND module-level constant assignments (``NUMERIC_CONTRACTS``, ``_BUDGET_MS``,
    ...). Most cited symbols are constants, not defs, so a def-only resolver would
    false-flag them — the assignment branches are load-bearing. An unparseable /
    unreadable file yields the empty set (the file-existence check already gates that
    path). Cached per file."""
    if rel in _symbol_cache:
        return _symbol_cache[rel]
    names: set[str] = set()
    try:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        _symbol_cache[rel] = frozenset()
        return _symbol_cache[rel]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    names.update(e.id for e in t.elts if isinstance(e, ast.Name))
    _symbol_cache[rel] = frozenset(names)
    return _symbol_cache[rel]


_member_cache: dict[tuple[str, str], frozenset[str]] = {}


def _defined_members(rel: str, cls: str) -> frozenset[str]:
    """Names defined in the body of class ``cls`` in ``rel``: methods, nested classes,
    AND class-body assignments. The assignment branches carry the same weight they do in
    ``_defined_names`` — cited members are often class constants, and a def-only member
    resolver would false-flag every one of them. Returns the empty set when the class is
    absent or the file will not parse; callers must check the CLASS resolves first, or an
    empty set reads as "no such member" when the truth is "no such class". Cached per
    (file, class)."""
    key = (rel, cls)
    if key in _member_cache:
        return _member_cache[key]
    members: set[str] = set()
    try:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        _member_cache[key] = frozenset()
        return _member_cache[key]
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == cls):
            continue
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                members.add(stmt.name)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                members.add(stmt.target.id)
            elif isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name):
                        members.add(t.id)
                    elif isinstance(t, (ast.Tuple, ast.List)):
                        members.update(e.id for e in t.elts if isinstance(e, ast.Name))
    _member_cache[key] = frozenset(members)
    return _member_cache[key]


def _symbol_phantom(cited: str, sym: str) -> bool:
    """True when the cited ``::Symbol`` chain does not resolve in ``cited``.

    BOTH separators resolve through one walk: pytest's canonical ``Class::method``
    node-id form and the dotted ``Class.member`` form. Treating them separately is what
    left the DOMINANT form unguarded — measured on the live tree, ``::Class::method`` has
    13 citations and ``::Class.member`` has 3, and an earlier draft of this resolver
    handled only the 3. It discarded everything after ``::`` before splitting, so a
    renamed *method* under an existing class resolved green: precisely the rot this
    module exists to catch, in the shape the repo actually writes.

    Resolves at most two levels — ``Class`` then its member. A deeper chain (``A.b.c``)
    resolves its first two segments and stops: attribute chains below a member are not
    statically resolvable from a ClassDef body without following types, and guessing
    there would false-flag. Stated rather than silently truncated, and pinned as dormant
    by ``test_deeper_chains_are_dormant_not_merely_disclosed``.

    A trailing separator is stripped: widening group 2 to admit ``.`` also admits a
    sentence period that lands inside the backticks (``…::TestPlanGuard.``), which would
    otherwise split to an empty member and false-flag on punctuation alone."""
    parts = [p for p in sym.replace("::", ".").rstrip(".").split(".") if p]
    if not parts:
        return False
    if parts[0] not in _defined_names(cited):
        return True
    if len(parts) > 1 and parts[1] not in _defined_members(cited, parts[0]):
        return True
    return False


def _is_illustrative(lines: list[str], idx: int) -> bool:
    """A citation on line ``idx`` (0-based) is illustrative/negated if a negation
    token appears on that line or the one above it, with code-spans stripped so a
    filename's own substrings can't self-trigger."""
    window = lines[idx - 1: idx + 1] if idx > 0 else lines[idx: idx + 1]
    text = _CODESPAN_RE.sub(" ", "\n".join(window))
    return bool(_NEGATION_RE.search(text))


def _scan_surface_files():
    seen: set[Path] = set()
    for glob in _SCAN_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if path in seen:
                continue
            seen.add(path)
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel in _EXCLUDE_FILES or any(rel.startswith(p) for p in _EXCLUDE_PREFIXES):
                continue
            yield rel, path


# A SYNTAX placeholder, not a citation: a ``test_<one char>`` stem, the same family
# the sibling contract's ``_is_placeholder_path`` already recognises (``x.py``,
# ``X.md``). A RULE, deliberately, not an allowlist entry — the live instance
# (``tests/test_X.py`` in CHANGELOG.md, describing what the guard used to validate)
# was suppressed only because the line ABOVE it happens to contain the word "not",
# which is about ``::Symbol`` vs file and has nothing to do with the placeholder. A
# pure copy-edit unmasks it, and the gate would then red on a dated entry the
# record-surface doctrine says must not be edited to fix.
_PLACEHOLDER_STEM_RE = re.compile(r"/test_[A-Za-z0-9]\.py$")


def _is_placeholder_citation(cited: str) -> bool:
    return bool(_PLACEHOLDER_STEM_RE.search("/" + cited.lstrip("/")))


def _find_phantoms(tracked: set[str]) -> list[tuple[str, int, str]]:
    phantoms: list[tuple[str, int, str]] = []
    for rel, path in _scan_surface_files():
        # Only a TRACKED doc can rot a shipping citation. Gitignored local state
        # — the ``cc/`` session summaries and compaction blueprints — legitimately
        # quotes historical phantoms as record data (the same reason
        # ``session-archive.md`` is excluded), and is absent on a fresh clone / in
        # CI. Restricting the scan to tracked files matches this contract's stated
        # ``git ls-files`` resolution philosophy and avoids that false-positive.
        if rel not in tracked:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines):
            for m in _CITATION_RE.finditer(line):
                cited = _normalize(m.group(1))
                if cited not in tracked:                       # file-level phantom
                    if not _is_illustrative(lines, i) and not _is_placeholder_citation(cited):
                        phantoms.append((rel, i + 1, m.group(1)))
                    continue
                sym = m.group(2)                               # symbol-level phantom
                if sym and _symbol_phantom(cited, sym):
                    if not _is_illustrative(lines, i):
                        phantoms.append((rel, i + 1, f"{m.group(1)}::{sym}"))
    return phantoms


def _citation_bearing_surfaces_outside_sweep(
    tracked: set[str],
) -> list[tuple[str, int, str]]:
    """Tracked ``.md`` files that carry a live (non-illustrative) ``tests/test_*.py``
    citation yet are NOT reached by ``_scan_surface_files`` and NOT in the backed
    completeness residue. A non-empty result is the enumeration-integrity gap: a
    citation-bearing surface the hand-maintained ``_SCAN_GLOBS`` cannot see, whose
    citation would rot undetected.

    The residue subtracted is exactly the enumerator's OWN declared excludes
    (``_EXCLUDE_FILES``/``_EXCLUDE_PREFIXES`` — record files it consciously skips) plus
    ``_COMPLETENESS_EXCLUDED_PREFIXES`` (mirrors / fixtures / illustrative scaffolds).
    Illustrative/negated citations flow through the SAME ``_is_illustrative`` calibration
    the phantom check uses, so a scaffold naming a demo test does not false-flag."""
    swept = {rel for rel, _ in _scan_surface_files()}
    gaps: list[tuple[str, int, str]] = []
    for rel in sorted(tracked):
        if not rel.endswith(".md") or rel in swept:
            continue
        if rel in _EXCLUDE_FILES or any(rel.startswith(p) for p in _EXCLUDE_PREFIXES):
            continue
        if any(rel.startswith(p) for p in _COMPLETENESS_EXCLUDED_PREFIXES):
            continue
        try:
            lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines):
            for m in _CITATION_RE.finditer(line):
                if not _is_illustrative(lines, i):
                    gaps.append((rel, i + 1, m.group(1)))
                    break
            else:
                continue
            break
    return gaps


class TestDocTestCitations:
    def test_every_cited_test_file_exists(self):
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")

        phantoms = _find_phantoms(tracked)
        assert not phantoms, (
            "Doc→test citations point at test files that don't exist (rot on "
            "rename/consolidation). Repoint each to the live enforcer, or — if the "
            "mention is illustrative/negated — reword so the calibrated exclusion "
            "recognises it:\n  "
            + "\n  ".join(f"{rel}:{ln}  `{cite}`" for rel, ln, cite in phantoms)
        )


class TestSymbolResolution:
    """The ``::Symbol`` half of the rot class: a citation whose file exists but whose
    cited symbol was renamed/moved is a phantom too. These tests pin the resolver's
    load-bearing assignment-awareness and the end-to-end symbol-flagging path."""

    def test_module_level_constant_symbol_resolves(self):
        """Load-bearing. Cited ``::Symbol``s are frequently module-level CONSTANTS
        (``ast.Assign`` / ``ast.AnnAssign`` targets), not class/func defs — e.g. the
        live citations to ``NUMERIC_CONTRACTS`` / ``_BUDGET_MS`` / ``ALLOWED_STAR_HOOKS``.
        A def-only resolver would fail to resolve them and false-flag those citations,
        redding this contract; the assignment-aware resolver must find them. (Remove the
        ``Assign``/``AnnAssign`` branches of ``_defined_names`` and this test goes RED —
        that is the earn-the-red for the load-bearing design decision.)"""
        assert "NUMERIC_CONTRACTS" in _defined_names("tests/test_documented_claims.py")
        assert "_BUDGET_MS" in _defined_names("tests/test_redos.py")
        assert "_WORST_CASE_BODY_LEN" in _defined_names("tests/test_redos.py")
        assert "ALLOWED_STAR_HOOKS" in _defined_names(
            "tests/test_hook_matcher_precision.py")
        # class/func defs still resolve through the same helper.
        assert "TestUnicodeNormalization" in _defined_names("tests/test_hooks.py")

    def test_phantom_symbol_in_real_file_is_flagged(self, tmp_path, monkeypatch):
        """A ``::Symbol`` whose file exists but whose symbol does not is flagged; a
        citation to a real symbol in the same file is not. Exercises the full
        ``_find_phantoms`` symbol branch over a controlled tree."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_synthetic.py").write_text(
            "class RealClass:\n    pass\n", encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.md").write_text(
            "Enforced by `tests/test_synthetic.py::RealClass`.\n"
            "Enforced by `tests/test_synthetic.py::MissingClass`.\n", encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys.modules[__name__], "_SCAN_GLOBS", ("docs/**/*.md",))
        monkeypatch.setattr(sys.modules[__name__], "_symbol_cache", {})
        cites = {c for _, _, c
                 in _find_phantoms({"tests/test_synthetic.py", "docs/x.md"})}
        assert "tests/test_synthetic.py::MissingClass" in cites
        assert "tests/test_synthetic.py::RealClass" not in cites

    def test_negated_symbol_citation_is_suppressed(self, tmp_path, monkeypatch):
        """A phantom ``::Symbol`` on a negated line is suppressed by the (unchanged)
        negation window — mirrors ``ESPALIER_MEMORY.md`` / ``cc/GOAL.md`` discussing the phantom
        with 'which does NOT exist'."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_synthetic.py").write_text(
            "class RealClass:\n    pass\n", encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.md").write_text(
            "There is no `tests/test_synthetic.py::MissingClass` (it was removed).\n",
            encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys.modules[__name__], "_SCAN_GLOBS", ("docs/**/*.md",))
        monkeypatch.setattr(sys.modules[__name__], "_symbol_cache", {})
        assert not _find_phantoms({"tests/test_synthetic.py", "docs/x.md"})

    def test_dotted_member_citation_resolves(self):
        """A ``::Class.member`` citation must MATCH before it can be resolved. This is
        the load-bearing half of the dotted arm, and the failure it closes is silence,
        not a wrong answer: with ``.`` outside group 2's character class the member text
        blocks the closing backtick, so the whole pattern fails and the citation is
        SKIPPED — never flagged, never counted. A resolver added without widening the
        class would sit behind a regex that never hands it anything."""
        m = _CITATION_RE.search(
            "`tests/test_hooks.py::TestUnicodeNormalization.test_nfkc_folds`")
        assert m is not None, "dotted member citation did not match at all"
        assert m.group(1) == "tests/test_hooks.py"
        assert m.group(2) == "TestUnicodeNormalization.test_nfkc_folds"
        # The undotted form keeps its existing capture — widening must not disturb it.
        m2 = _CITATION_RE.search("`tests/test_hooks.py::TestUnicodeNormalization`")
        assert m2 is not None and m2.group(2) == "TestUnicodeNormalization"

    def test_phantom_dotted_member_is_flagged(self, tmp_path, monkeypatch):
        """End-to-end: a real class with a MISSING member is flagged, while a real
        member on the same class is not. The class half must keep passing on its own —
        a bare-class citation that resolves is TP-373 2-D's shipped behavior and this
        arm adds to it rather than replacing it."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_synthetic.py").write_text(
            "class RealClass:\n"
            "    ATTR = 1\n"
            "    def real_method(self):\n        pass\n",
            encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.md").write_text(
            "A `tests/test_synthetic.py::RealClass.real_method`.\n"
            "A `tests/test_synthetic.py::RealClass.ATTR`.\n"
            "A `tests/test_synthetic.py::RealClass.missing_method`.\n"
            "A `tests/test_synthetic.py::RealClass`.\n", encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys.modules[__name__], "_SCAN_GLOBS", ("docs/**/*.md",))
        monkeypatch.setattr(sys.modules[__name__], "_symbol_cache", {})
        monkeypatch.setattr(sys.modules[__name__], "_member_cache", {})
        cites = {c for _, _, c
                 in _find_phantoms({"tests/test_synthetic.py", "docs/x.md"})}
        assert "tests/test_synthetic.py::RealClass.missing_method" in cites
        assert "tests/test_synthetic.py::RealClass.real_method" not in cites
        assert "tests/test_synthetic.py::RealClass.ATTR" not in cites, (
            "class-body assignments are members too — a def-only member resolver "
            "would false-flag every cited class constant")
        assert "tests/test_synthetic.py::RealClass" not in cites

    def test_deeper_chains_are_dormant_not_merely_disclosed(self):
        """``_symbol_phantom`` resolves two levels and stops, so a broken THIRD segment
        (``Class.member.attr``) passes silently. Its docstring discloses that — but a
        disclosure decays into a blind spot the moment the population grows one.

        This pins the gap as DORMANT rather than merely stated: zero live citations carry
        a chain deeper than ``Class.member`` today. If one ever lands, this REDs and the
        limitation must be answered instead of inherited. A docstring cannot do that."""
        deep = re.compile(r"`[^`]*::[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+[^`]*`")
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        hits: list[str] = []
        for rel, path in _scan_surface_files():
            if rel not in tracked:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            hits += [f"{rel}: {h}" for h in deep.findall(text)]
        assert not hits, (
            "a citation now carries a symbol chain deeper than Class.member, which "
            f"_symbol_phantom resolves only two levels of — extend it or exempt these: {hits}"
        )

    def test_defined_members_empty_for_absent_class_and_unparsable_file(self, tmp_path,
                                                                        monkeypatch):
        """``_defined_members`` returns the empty set for BOTH 'class absent' and 'file
        will not parse'. The two are indistinguishable to the caller, which is only safe
        because ``_symbol_phantom`` checks the CLASS resolves first — pinned here so a
        later refactor that adds a second call site cannot quietly inherit the assumption
        without a test noticing."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_ok.py").write_text(
            "class RealClass:\n    def m(self):\n        pass\n", encoding="utf-8")
        (tmp_path / "tests" / "test_bad.py").write_text(
            "class RealClass:\n  def m(self)\n", encoding="utf-8")  # SyntaxError
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys.modules[__name__], "_member_cache", {})
        monkeypatch.setattr(sys.modules[__name__], "_symbol_cache", {})
        assert _defined_members("tests/test_ok.py", "RealClass") == frozenset({"m"})
        assert _defined_members("tests/test_ok.py", "NoSuchClass") == frozenset()
        assert _defined_members("tests/test_bad.py", "RealClass") == frozenset()
        # The invariant that makes the ambiguity safe: an absent class is caught by the
        # class check, so the empty set is never read as "no such member".
        assert _symbol_phantom("tests/test_ok.py", "NoSuchClass.m") is True
        assert _symbol_phantom("tests/test_ok.py", "RealClass.m") is False

    def test_syntax_placeholder_dotted_citation_is_exempt(self):
        """``ESPALIER_MEMORY.md`` carries a bare ``::Class.member`` as a meta-reference to
        the citation SYNTAX. It needs no allowlist entry: it is exempt **by construction**,
        because group 1 requires a real ``test_*.py`` path and the placeholder has none.

        This is a REGRESSION PIN, not an earned red — it passes before and after the
        dotted arm, and says so rather than implying it caught something. Its value is
        forward: if anyone ever loosens group 1 to accept a bare filename, this reds and
        forces the placeholder question to be answered deliberately instead of by an
        exemption list nobody revisits."""
        assert _CITATION_RE.search("`::Class.member`") is None
        # And it is genuinely the live literal, not a hypothetical.
        memory_md = (REPO_ROOT / "ESPALIER_MEMORY.md").read_text(encoding="utf-8")
        assert "`::Class.member`" in memory_md, (
            "the placeholder this test exempts is gone — re-derive whether the "
            "by-construction exemption still describes the live tree")


class TestSweepCompleteness:
    """Enumeration-integrity for the citation sweep. ``TestDocTestCitations`` verifies
    citations INSIDE ``_SCAN_GLOBS`` resolve; this verifies the sweep's own COVERAGE —
    that the hand-maintained glob set actually reaches every citation-bearing tracked doc
    surface, so a NEW sibling surface added outside it reds instead of rotting silently.
    A flat presence check can never catch that absence; only a coverage check can."""

    def test_every_citation_bearing_surface_is_swept(self):
        """The live-tree contract. Any tracked ``.md`` carrying a live ``tests/test_*.py``
        citation must be swept or in the backed residue — an out-of-sweep gap reds."""
        tracked = _tracked_files()
        if not tracked:
            pytest.skip("`git ls-files` yielded nothing — not a dev tree / fresh clone")
        gaps = _citation_bearing_surfaces_outside_sweep(tracked)
        assert not gaps, (
            "Tracked doc surfaces carry live `tests/test_*.py` citations but sit OUTSIDE "
            "the sweep (`_SCAN_GLOBS`) — their citations rot undetected (the "
            "enumeration-integrity gap). Sweep each by adding it to `_SCAN_GLOBS`, or — if "
            "it is a generated mirror / fixture / non-authoritative surface — add a backed "
            "entry to `_COMPLETENESS_EXCLUDED_PREFIXES`:\n  "
            + "\n  ".join(f"{rel}:{ln}  `{cite}`" for rel, ln, cite in gaps)
        )

    def test_out_of_sweep_citation_is_flagged(self, tmp_path, monkeypatch):
        """Earn-the-red for the coverage check, over a controlled tree: a citation-bearing
        ``.md`` OUTSIDE the sweep and OUTSIDE the residue is flagged; a swept one and a
        residue-excluded one are not. Remove the membership guard and the gap goes
        unflagged — that is the red this pins."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_synthetic.py").write_text("x = 1\n", encoding="utf-8")
        for d in ("docs", "outside", "vendored"):
            (tmp_path / d).mkdir()
        for d in ("docs/swept", "outside/gap", "vendored/mirror"):
            (tmp_path / f"{d}.md").write_text(
                "Enforced by `tests/test_synthetic.py`.\n", encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys.modules[__name__], "_SCAN_GLOBS", ("docs/**/*.md",))
        monkeypatch.setattr(
            sys.modules[__name__], "_COMPLETENESS_EXCLUDED_PREFIXES", ("vendored/",))
        tracked = {"tests/test_synthetic.py", "docs/swept.md",
                   "outside/gap.md", "vendored/mirror.md"}
        flagged = {rel for rel, _, _ in _citation_bearing_surfaces_outside_sweep(tracked)}
        assert flagged == {"outside/gap.md"}

    def test_out_of_sweep_illustrative_citation_is_not_flagged(self, tmp_path, monkeypatch):
        """An out-of-sweep surface whose only citation is illustrative/negated is NOT a
        gap — the ``_is_illustrative`` calibration flows through the coverage check too,
        so a scaffold naming a demo test (e.g. ``examples/golden``) does not false-flag."""
        (tmp_path / "outside").mkdir()
        (tmp_path / "outside" / "scaffold.md").write_text(
            "For example `tests/test_g1_earn_the_gate.py` (illustrative).\n",
            encoding="utf-8")
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys.modules[__name__], "_SCAN_GLOBS", ("docs/**/*.md",))
        monkeypatch.setattr(
            sys.modules[__name__], "_COMPLETENESS_EXCLUDED_PREFIXES", ())
        assert not _citation_bearing_surfaces_outside_sweep({"outside/scaffold.md"})
