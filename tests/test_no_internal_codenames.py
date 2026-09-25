"""Internal-codename denylist guard — TP-92 task 92-G; the local pattern arm
is DEF-708 (TP-452 1-G, 2026-09-21).

Walks `git ls-files` and asserts that no tracked file contains an internal
codename. Two pattern sources:

- ``FORBIDDEN_PATTERNS`` (tracked, in this file) — names that are safe to
  print: the codename ``Morrison`` (and its full file-reference form
  ``Task-Packs-Morrison-Inspired``). The codename has no meaning outside the
  internal project history; OSS readers searching for the referenced file
  find nothing.
- ``.local-codenames.txt`` at the repo root (gitignored, classified
  ``local_only``, never shipped) — the operator's own terms: a third party's
  name, a private narrative. One regex per line, ``#`` comments, blank lines
  skipped, the whole line is the pattern. A tracked denylist that spells a
  sensitive name is itself the leak, so those terms live only on the
  operator's machine; the gate reads the file when present and runs on the
  tracked list alone when it is absent (a fresh clone, a contributor's
  machine, CI). A hit is reported by the file's LINE NUMBER, never by the
  term, so a pasted failure carries nothing. A line that does not compile
  fails the gate with its line number rather than silently dropping the arm.
  ⚠ An absent file is a silent green for the local terms — no test can tell
  "not armed" from "nothing to enforce" — so ``scripts/check_handoff_landing.py``
  refuses the handoff on the operator's tree when the arm is off. Keep the
  regexes literal or simple: every tracked line is matched against each one,
  and a pattern that spends more than ``PATTERN_BUDGET_S`` over the tree fails
  the gate by label. A pattern cannot start with ``#`` (spell it ``[#]``), and
  a trailing ``# note`` is part of the pattern, not a comment. The file is
  read as ``utf-8-sig`` (a BOM does not disarm line 1); a file that does not
  decode fails loud. ``memory/local-codename-arm.md`` is where a session
  learns to recreate the file.

Excluded paths (historical-record + self-reference surfaces):

- ``docs/session-archive.md`` — pruned ESPALIER_MEMORY.md row archive; retaining
  historical references is the file's purpose.
- ``cc/blueprints/*.json`` (incl. ``latest.json``) — frozen session
  reasoning state. Sister-shape to ``session-archive.md``.
- every ``task-packs/`` path OUTSIDE the ship set — derived from
  ``surface_contract.is_shipped_task_pack_surface``, so ``Done/``,
  ``Merged/``, ``Scrapped/``, the dated archive files and a findings JSON
  are excluded with nothing to remember when a new kind appears. Defensive:
  those are gitignored and pruned from the filesystem-walk fallback, but a
  tracked-by-accident record should not block HERE (the tracked-noise gate
  and the ship-set gate name the stray). A pack directly under
  ``task-packs/`` or ``task-packs/Deferred/`` and the ledger ARE scanned:
  public since 2026-09-21.
- ``tests/test_no_internal_codenames.py`` (this file) — structural
  self-reference. The denylist test cannot search for tokens without
  containing them; the codenames here are the contract definition, not
  leakage. Sister-shape to ``_bash_patterns.py`` containing the regexes
  it pins. The LOCAL file is deliberately not self-excluded: gitignored and
  walker-pruned it never reaches the scan, and a force-added copy SHOULD red
  on its own lines.
"""
from __future__ import annotations

import ast
import re
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"Morrison",
    r"Task-Packs-Morrison-Inspired",
)

#: The local arm (DEF-708). Repo-relative so the .gitignore row, the classifier
#: entry and the check-ignore row below all name the same string.
LOCAL_PATTERNS_REL = ".local-codenames.txt"

EXCLUDED_PATH_PATTERNS: tuple[str, ...] = (
    r"^docs/session-archive\.md$",
    r"^cc/blueprints/.*\.json$",
    r"^tests/test_no_internal_codenames\.py$",
)


def _tracked_files() -> list[str]:
    from espalier.repo_mode import list_tracked_or_walked_files

    files, _source = list_tracked_or_walked_files(REPO_ROOT)
    return files


def _is_excluded(path: str) -> bool:
    """Historical-record and self-reference surfaces the scan skips.

    The task-pack arm is DERIVED from the one predicate that owns the shipping
    boundary (``is_shipped_task_pack_surface``), not a copy of its subtree
    names: a pack outside the ship set is a record, a pack inside it is public
    and scanned. The three regex rows are the surfaces no classifier owns.
    """
    if path.startswith("task-packs/"):
        from espalier.surface_contract import is_shipped_task_pack_surface

        return not is_shipped_task_pack_surface(path)
    return any(re.search(pat, path) for pat in EXCLUDED_PATH_PATTERNS)


#: Per-pattern wall-clock budget over the whole tree, in seconds. Every
#: operator regex runs against every tracked line (465,320 lines / 24 MB
#: measured 2026-09-21), and a catastrophic pattern would otherwise run into
#: pytest's 60 s thread timeout, which kills the worker with a stack naming
#: `re` and never the line. Charged per file, so one pathological line still
#: costs its own time before the check fires -- a bound, not a guard.
PATTERN_BUDGET_S = 10.0


class LocalPatternError(ValueError):
    """A line of the local arm cannot be used. Loud by design: a dropped line
    would turn the arm off for that term with every test green. The message
    carries the file, the line and the label -- never the pattern text."""


def load_local_patterns(path: Path) -> tuple[tuple[str, str], ...]:
    """``(regex, label)`` pairs from the local arm; ``()`` when the file is absent.

    The label is ``<file>#<line>`` — what a failure prints — so the term itself
    never appears in a report. ``utf-8-sig``: a BOM written by Notepad would
    otherwise ride on line 1, compile, match nothing and count as armed. The
    frame is hidden and the cause dropped so a ``pytest -l`` re-run cannot
    print the file's lines or the chained ``re.error``'s pattern.
    """
    __tracebackhide__ = True
    if not path.is_file():
        return ()
    try:
        raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise LocalPatternError(
            f"{path.name}: unreadable ({type(exc).__name__})"
        ) from None
    out: list[tuple[str, str]] = []
    for lineno, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            re.compile(line)
        except re.error as exc:
            raise LocalPatternError(
                f"{path.name}:{lineno}: does not compile (position {exc.pos})"
            ) from None
        out.append((line, f"{path.name}#{lineno}"))
    return tuple(out)


def _all_patterns(root: Path) -> tuple[tuple[str, str], ...]:
    """The tracked list (labelled by its own text) plus the local arm."""
    tracked = tuple((p, p) for p in FORBIDDEN_PATTERNS)
    return tracked + load_local_patterns(root / LOCAL_PATTERNS_REL)


def _scan(
    root: Path,
    rel_paths: Iterable[str],
    labelled: Sequence[tuple[str, str]],
    *,
    budget_s: float = PATTERN_BUDGET_S,
) -> list[tuple[str, int, str]]:
    """``(rel, lineno, label)`` for every line of every non-excluded path that
    matches any pattern, in tracked order, then line, then pattern order. One
    loop for both scanning classes below. Patterns run outermost per file so
    each one's time can be charged to its label; the frame is hidden because
    its locals hold the compiled patterns."""
    __tracebackhide__ = True
    compiled = [(re.compile(p), label) for p, label in labelled]
    spent = [0.0] * len(compiled)
    offenders: list[tuple[str, int, str]] = []
    for rel in rel_paths:
        if _is_excluded(rel):
            continue
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        hits: list[tuple[int, int, str]] = []
        for i, (pattern, label) in enumerate(compiled):
            started = time.perf_counter()
            for lineno, line in enumerate(lines, start=1):
                if pattern.search(line):
                    hits.append((lineno, i, label))
            spent[i] += time.perf_counter() - started
            if spent[i] > budget_s:
                raise LocalPatternError(
                    f"{label}: spent more than {budget_s:g}s over the tree -- "
                    "simplify the pattern"
                )
        hits.sort()
        offenders.extend((rel, lineno, label) for lineno, _i, label in hits)
    return offenders


class TestNoInternalCodenames:
    """Tracked files must not leak internal project codenames."""

    def test_no_morrison_codename_in_tracked_files(self):
        tracked = _tracked_files()
        assert tracked, "git ls-files returned no paths — repo state is suspicious"

        offenders = _scan(REPO_ROOT, tracked, _all_patterns(REPO_ROOT))

        assert not offenders, (
            "Internal codename(s) found in tracked files:\n"
            + "\n".join(
                f"  - {path}:{lineno}  (matched: {label})"
                for path, lineno, label in offenders
            )
            + "\nScrub the term in-place, or add the path to "
            "EXCLUDED_PATH_PATTERNS if it is a historical-record surface. "
            f"A `{LOCAL_PATTERNS_REL}#N` label is line N of the local arm."
        )


def _machine_local_tokens() -> list[tuple[str, str]]:
    """``(regex, why)`` for strings that identify THIS machine or session.

    DERIVED, never literal. Writing the operator's own username into a tracked
    test to forbid it would leak the very thing it forbids, and a shape-based
    rule (``/Users/<word>``) is a false-positive engine here: 14 tracked files
    carry generic placeholders (``/Users/x``, ``/Users/someone``,
    ``/Users/yourname``) that are correct documentation. So the home path is read
    from the environment at run time — it names whoever is running, which on a
    contributor's machine or in CI is exactly the right target and is never
    stored anywhere.
    """
    home = str(Path.home()).rstrip("/")
    tokens = [
        (re.escape(home), "absolute home directory of the running user"),
        # Claude Code's project-scratch mangling of an absolute path: every "/"
        # becomes "-", so /Users/x/Repo -> -Users-x-Repo. A pasted scratch path
        # carries the username in this form and would survive a "/Users/" grep.
        (re.escape(home.replace("/", "-")), "mangled home path (scratch-dir form)"),
        # Per-session scratch root: /private/tmp/claude-<uid>/... — machine-local
        # by construction and dead the moment the session ends.
        (r"/private/tmp/claude-\d+/", "per-session scratch root"),
    ]
    return [(pat, why) for pat, why in tokens if pat]


class TestNoMachineLocalPaths:
    """Tracked files must not carry paths that identify the operator's machine.

    The trigger was real: a review workflow moved from untracked to tracked
    carrying two absolute scratch paths with the operator's username and a dead
    session UUID — in a repo one decision away from being public. Every existing
    release-surface guard passed and was useless here, correctly: ``.gitattributes``
    export-ignores ``.claude/workflows/`` and ``surface_contract`` classifies it
    ``local_only``, so the wheel, the sdist and the Download-ZIP are all clean.
    None of those surfaces is ``git clone``, which is the one that matters.
    """

    def test_no_machine_local_path_in_tracked_files(self):
        tracked = _tracked_files()
        assert tracked, "git ls-files returned no paths — repo state is suspicious"

        offenders = _scan(REPO_ROOT, tracked, _machine_local_tokens())

        assert not offenders, (
            "Machine-local path(s) in tracked files — these ship in every clone:\n"
            + "\n".join(f"  - {p}:{n}  ({why})" for p, n, why in offenders)
            + "\nReplace with a portable form (e.g. ${TMPDIR:-/tmp}/<name>/)."
        )

    def test_scan_detects_a_planted_machine_local_path(self):
        """Earn the red. The derived tokens must actually fire, or the gate above
        is a green that proves nothing on a machine whose home path never appears.
        """
        home = str(Path.home()).rstrip("/")
        planted = (
            f"build under {home}/scratch/lane/\n"
            f"or {home.replace('/', '-')}/scratch/\n"
            # Deliberately not this machine's uid — the fixture should not carry a
            # real, stable identifier of the operator just to prove a regex fires.
            "or /private/tmp/claude-999999/x/\n"
        )
        compiled = [re.compile(p) for p, _ in _machine_local_tokens()]
        hits = [
            lineno
            for lineno, line in enumerate(planted.splitlines(), start=1)
            for pat in compiled
            if pat.search(line)
        ]
        assert sorted(set(hits)) == [1, 2, 3], hits
        # ...and the generic placeholders real docs use must NOT fire.
        benign = "see /Users/x/Repo, /Users/someone/site-packages, /Users/yourname/..."
        assert not any(pat.search(benign) for pat in compiled), (
            "a generic placeholder path was flagged — the rule has become "
            "shape-based instead of identity-based"
        )


# ── DEF-708: the local pattern arm and the derived exclusion ─────────────────


class TestLocalPatternArm:
    """The second pattern source, read from a gitignored root file.

    Mutations named before the rows were written (STANDING_PRINCIPLES 19):
    ``load_local_patterns`` returning ``()`` — the planted term below goes
    unreported; the .gitignore row dropped — the check-ignore row reds (rc 1
    measured before the row existed); the classifier entry dropped — the
    classify row reds. The rows call the real loader on a real file: only the
    path is a parameter.
    """

    def test_loader_skips_comments_and_blanks_and_labels_by_line(self, tmp_path):
        local = tmp_path / LOCAL_PATTERNS_REL
        local.write_text("# a comment\n\n  zebra-\\d{3}  \n#another\n(?i)quokka\n", encoding="utf-8")
        assert load_local_patterns(local) == (
            ("zebra-\\d{3}", f"{LOCAL_PATTERNS_REL}#3"),
            ("(?i)quokka", f"{LOCAL_PATTERNS_REL}#5"),
        )

    def test_loader_is_empty_when_the_file_is_absent(self, tmp_path):
        assert load_local_patterns(tmp_path / LOCAL_PATTERNS_REL) == ()

    def test_a_bom_on_line_one_does_not_disarm_it(self, tmp_path):
        """Notepad on the Windows walk host writes a BOM. Read as plain utf-8
        the first pattern carries U+FEFF, compiles, matches nothing and counts
        as armed -- both review lanes drove it to a silent green."""
        local = tmp_path / LOCAL_PATTERNS_REL
        local.write_bytes(b"\xef\xbb\xbfzebra-\\d{3}\n")
        assert load_local_patterns(local) == (("zebra-\\d{3}", f"{LOCAL_PATTERNS_REL}#1"),)

    def test_a_file_that_does_not_decode_fails_loud(self, tmp_path):
        local = tmp_path / LOCAL_PATTERNS_REL
        local.write_bytes(b"caf\xe9\n")  # CP1252, not UTF-8
        with pytest.raises(LocalPatternError, match="unreadable"):
            load_local_patterns(local)

    def test_a_line_that_does_not_compile_fails_with_its_line_number(self, tmp_path):
        """...and the message carries neither the pattern nor the chained
        ``re.error`` (whose ``.pattern`` is the term), so a pasted failure
        stays clean. A bad group name is the case that echoes the term."""
        local = tmp_path / LOCAL_PATTERNS_REL
        local.write_text("fine\n(?P<zebra corp>x)\n", encoding="utf-8")
        with pytest.raises(LocalPatternError, match=rf"{LOCAL_PATTERNS_REL}:2:") as info:
            load_local_patterns(local)
        assert "zebra" not in str(info.value)
        assert info.value.__suppress_context__ and info.value.__cause__ is None

    def test_a_pattern_past_its_budget_is_named_by_label_only(self, tmp_path):
        (tmp_path / "notes.md").write_text("a\nb\n", encoding="utf-8")
        with pytest.raises(LocalPatternError, match="L#7") as info:
            _scan(tmp_path, ["notes.md"], (("zebra", "L#7"),), budget_s=-1.0)
        assert "zebra" not in str(info.value)

    def test_offenders_keep_tracked_then_line_then_pattern_order(self, tmp_path):
        """The per-pattern loop must not reorder the report."""
        (tmp_path / "b.md").write_text("quokka\nzebra\n", encoding="utf-8")
        (tmp_path / "a.md").write_text("zebra quokka\n", encoding="utf-8")
        got = _scan(tmp_path, ["b.md", "a.md"], (("zebra", "Z"), ("quokka", "Q")))
        assert got == [("b.md", 1, "Q"), ("b.md", 2, "Z"), ("a.md", 1, "Z"), ("a.md", 1, "Q")]

    def test_the_arm_catches_a_planted_term_only_through_the_local_read(self, tmp_path):
        """Earn the red on both arms of the mutation the pack names: with the
        local read a planted term is reported, labelled by line and never by
        the term; with the local read removed (the tracked list alone) the same
        tree is green. A loader that silently returns ``()`` fails the first
        assertion."""
        (tmp_path / LOCAL_PATTERNS_REL).write_text("# local\nzebra-\\d{3}\n", encoding="utf-8")
        (tmp_path / "notes.md").write_text("see zebra-123 for context\nno hit here\n", encoding="utf-8")

        with_arm = _scan(tmp_path, ["notes.md"], _all_patterns(tmp_path))
        assert with_arm == [("notes.md", 1, f"{LOCAL_PATTERNS_REL}#2")]
        assert "zebra" not in with_arm[0][2]

        tracked_only = tuple((p, p) for p in FORBIDDEN_PATTERNS)
        assert _scan(tmp_path, ["notes.md"], tracked_only) == []

    def test_the_local_file_is_gitignored_here(self):
        """Asks git, index first: a force-added copy reads "not ignored"
        however many rules match it, which is exactly the failure this pins —
        the arm silently becoming tracked."""
        from tests._git_oracle import GitAnswerUnavailable, require_is_gitignored

        try:
            ignored = require_is_gitignored(REPO_ROOT, LOCAL_PATTERNS_REL)
        except GitAnswerUnavailable as exc:  # pragma: no cover - not a git checkout
            pytest.skip(f"git cannot answer for this tree: {exc}")
        assert ignored, (
            f"{LOCAL_PATTERNS_REL} is not gitignored: the local arm's terms would "
            "be one `git add -A` from a tracked file"
        )

    def test_the_local_file_classifies_local_only(self):
        """The walker twin of the gitignore row: the archive builder's no-index
        fallback walks the tree, and this entry is what keeps the file out."""
        from espalier.surface_contract import classify_release_path

        assert classify_release_path(LOCAL_PATTERNS_REL) == "local_only"


class TestExcludedPaths:
    """Both arms of the derived exclusion — what is skipped AND what is scanned.

    Mutation: restore the pre-DEF-708 literal row ``^task-packs/Scrapped/``
    in place of the derivation and the Done/ and Merged/ rows red.
    """

    @pytest.mark.parametrize("path,excluded", [
        # records outside the ship set -- skipped
        ("task-packs/Done/TP-1-x.md", True),
        ("task-packs/Merged/TP-1-x.md", True),
        ("task-packs/Scrapped/TP-1-x.md", True),
        ("task-packs/Deferred/old/TP-1-x.md", True),
        ("task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md", True),
        ("task-packs/TP-9-probe-findings.json", True),
        ("task-packs/notes.txt", True),
        ("docs/session-archive.md", True),
        ("cc/blueprints/latest.json", True),
        ("tests/test_no_internal_codenames.py", True),
        # the ship set -- public, scanned
        ("task-packs/TP-452-the-ledger-ships.md", False),
        ("task-packs/Deferred/TP-1-x.md", False),
        ("task-packs/FORWARD_LEDGER.md", False),
        ("task-packs/LEDGER_PROBES.json", False),
        ("task-packs/CLAUDE.md", False),
        # not self-excluded on purpose (module docstring)
        (".local-codenames.txt", False),
        ("README.md", False),
        ("docs/SHARP_EDGES.md", False),
    ])
    def test_is_excluded(self, path, excluded):
        assert _is_excluded(path) is excluded


# ── TP-99 B-bonus: TP-NN pack IDs in common-tier adopter surfaces ────────────


# Scoped surfaces: the first pages an OSS adopter reads. TP-NN refs are
# session-internal vocabulary; an outside reader has no decoding key. Wider
# surfaces (SHARP_EDGES, MEMORY) intentionally keep TP-NN refs as accurate
# historical record and are NOT included here. (CHANGELOG.md was formerly in
# that set but its public dated history was de-provenanced for the OSS launch
# and is now gated by espalier.provenance_census.) Harness-dev tier
# assets are likewise out of scope — they deploy only when the operator opts
# into the harness-dev tier. (TP-210 promoted the task-pack command/skill
# bodies to common and de-provenanced implement-pack.md's checklist-version
# label, so no common-tier asset carries a TP-NN ref — enforced by
# tests/test_init_tier_split.py::TestCommonTierAssetHygiene.)
ADOPTER_FACING_SURFACES: tuple[str, ...] = (
    "README.md",
    "docs/QUICKSTART.md",
)

# Generic pack ID pattern. Matches TP-12, TP-RELEASE-14, TP-OSS-01, etc.
_TP_ID_RE = re.compile(r"\bTP-(?:[A-Z]+-)?\d+[a-z]?\b")


class TestNoPackIdsInAdopterSurfaces:
    """Adopter-facing top-of-funnel docs must not leak TP-NN pack IDs.

    TP-87/93 scrubbed common-tier asset bodies (codename + TP-NN refs).
    TP-99 B-bonus closes the same gap on the OSS first-read surfaces:
    README and QUICKSTART are where a stranger lands before any other
    context, and TP-NN refs there read as undecodable jargon.
    """

    @pytest.mark.parametrize("rel_path", ADOPTER_FACING_SURFACES)
    def test_no_pack_ids(self, rel_path: str):
        target = REPO_ROOT / rel_path
        assert target.exists(), f"adopter-facing surface missing: {rel_path}"
        offenders: list[tuple[int, str, str]] = []
        for lineno, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in _TP_ID_RE.finditer(line):
                offenders.append((lineno, match.group(), line.strip()))
        assert not offenders, (
            f"TP-NN pack IDs found in adopter-facing surface {rel_path}:\n"
            + "\n".join(
                f"  - line {lineno}: {pid!r}  in {text!r}"
                for lineno, pid, text in offenders
            )
            + "\nAdopter-facing surfaces must not reference internal pack IDs. "
            "Rephrase to describe the policy / decision in plain language."
        )


# ── TP-168 168-E: TP-NN pack IDs in tools/cc/ runtime-INJECTED strings ────────


def _hook_injected_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, text) for string literals that reach a user-visible runtime
    sink in a hook module — the two confirmed injection carriers:

      1. elements of a module-level ``*_WITNESSES`` tuple/list (rendered into
         ``hookSpecificOutput.additionalContext`` via ``_reinject._bullets``); and
      2. any string flowing into a ``print(...)`` call (operator-visible stderr/stdout).

    Deliberately NOT scanned: ``#`` comments and docstrings. Those are historical
    record (the codebase references TP-NN throughout) and never reach the adopter
    at runtime; scanning them would drown the real leaks in false positives. The
    adopter-facing surfaces (README/QUICKSTART) are covered separately above.
    """
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(n.endswith("_WITNESSES") for n in names):
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        out.append((sub.lineno, sub.value))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            for sub in ast.walk(node):  # descends into f-string (JoinedStr) literal parts
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append((sub.lineno, sub.value))
    return out


class TestNoPackIdsInHookRuntimeStrings:
    """Hook runtime output the adopter sees must not leak TP-NN pack IDs.

    TP-168 168-E: ``_reinject._HOOK_COUNT_WITNESSES`` injected
    ``"docs/QUICKSTART.md (stale since TP-163)"`` and ``session_start`` printed a
    ``(TP-146)`` warning — both reach an adopter who never has the decoding key.
    This scans the two injection sinks (witness tuples + ``print`` args) via AST so
    comment/docstring TP-NN refs (acceptable historical record) are not flagged.
    """

    HOOK_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

    def test_no_pack_ids_in_injected_runtime_strings(self):
        offenders: list[tuple[str, int, str, str]] = []
        for py in sorted(self.HOOK_DIR.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for lineno, text in _hook_injected_strings(tree):
                for match in _TP_ID_RE.finditer(text):
                    offenders.append((py.name, lineno, match.group(), text.strip()[:80]))
        assert not offenders, (
            "TP-NN pack ID(s) found in hook runtime-injected strings (adopter-visible):\n"
            + "\n".join(
                f"  - {name}:{lineno}  {pid!r} in {text!r}"
                for name, lineno, pid, text in offenders
            )
            + "\nThese reach the adopter via additionalContext / print. Rephrase in "
            "plain language. (Comments and docstrings are exempt — historical record.)"
        )

    def test_scan_detects_a_planted_pack_id(self):
        """Earn the gate: the scan must go RED on a planted TP-999 in either sink, so
        it cannot silently no-op the next time a pack ID lands in injected output.
        The comment + the plain (non-sink) assignment must stay exempt."""
        source = (
            "_X_WITNESSES = ('see TP-999 for context',)\n"   # witness sink -> flagged
            "print('regenerated per TP-999')\n"              # print sink -> flagged
            "# historical: TP-163 added this -- a COMMENT\n"  # comment -> exempt
            "X = 'TP-164 internal label'\n"                  # non-sink assign -> exempt
        )
        tree = ast.parse(source)
        found = {
            pid
            for _ln, text in _hook_injected_strings(tree)
            for pid in _TP_ID_RE.findall(text)
        }
        assert "TP-999" in found        # both the witness + the print are caught
        assert "TP-163" not in found    # comment is exempt
        assert "TP-164" not in found    # plain assignment (not a sink) is exempt
