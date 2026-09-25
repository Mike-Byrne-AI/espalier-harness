"""Parity locks for FORCED concept-duplications.

A "forced" duplication is one whose copies span a no-import boundary
(``tools/cc/`` <-> ``espalier/``, a stdlib-only scanner <-> the engine, or the
``espalier/_vendor/cc`` mirror). They cannot be collapsed to one canon without
breaking an isolation invariant, so each is pinned instead: an equality assertion
that reds the moment one copy drifts from the other.

Each test compares the live copies *to each other* (not to a frozen literal), so
identical intentional edits to every copy stay green while a divergent edit to one
copy reds. The one exception is 2-A, which pins the hook-side declaration to the
engine SoT (``surface_contract``), the canonical source it must mirror.

tools/cc modules are loaded by file path (``importlib``) so this test does not drag
them into an import graph that would violate their zero-espalier-import contract;
the loader adds the hook dir to ``sys.path`` only while a module executes, because
several hook modules do sibling imports (``import _hook_utils``) at load time.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = TOOLS_CC / "hooks"


@contextlib.contextmanager
def _syspath(*dirs: str):
    added = [d for d in dirs if d not in sys.path]
    for d in added:
        sys.path.insert(0, d)
    try:
        yield
    finally:
        for d in added:
            with contextlib.suppress(ValueError):
                sys.path.remove(d)


def _load(path: Path, alias: str):
    """Load a tools/cc module by file path, siblings resolvable during exec."""
    with _syspath(str(HOOKS_DIR), str(TOOLS_CC)):
        spec = importlib.util.spec_from_file_location(alias, str(path))
        assert spec is not None and spec.loader is not None, f"cannot load {path}"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[alias] = mod
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 2-A  write_guard protected-prefix declaration == engine mutation-prefix SoT
# ---------------------------------------------------------------------------
class TestProtectedPrefixDeclarationParity:
    """The hook-side ``_protected_zones.PROTECTED_PREFIXES`` is a test-/audit-facing
    declaration; the runtime deny uses ``_hook_utils.harness_protected_prefixes``
    (self-host-aware). Pin the declaration to the engine SoT so the two cannot
    silently disagree about what the full engine protects."""

    def test_declaration_equals_surface_contract(self):
        from espalier import surface_contract

        pz = _load(HOOKS_DIR / "_protected_zones.py", "_pz_parity")
        assert set(pz.PROTECTED_PREFIXES) == set(
            surface_contract.get_protected_mutation_prefixes()
        )


# ---------------------------------------------------------------------------
# 2-B  .claude discovery dirs: espalier reflect_protocol == tools/cc twin
# ---------------------------------------------------------------------------
class TestDiscoveryDirsParity:
    def test_reflect_discovery_dirs_match(self):
        from espalier import reflect_protocol as e_reflect

        tcc_reflect = _load(TOOLS_CC / "reflect_protocol.py", "_tcc_reflect_parity")
        assert set(e_reflect.DISCOVERY_DIRS) == set(tcc_reflect.DISCOVERY_DIRS)


# ---------------------------------------------------------------------------
# 2-C  scanner DEFAULT_EXCLUDE across the five stdlib-only scanners
# ---------------------------------------------------------------------------
class TestScannerDefaultExcludeParity:
    """The five walk-based scanners cannot share a ``_common`` (stdlib-only
    isolation forbids even an intra-package import — TestScannersStdlibOnly), so
    their DEFAULT_EXCLUDE sets are pinned equal instead."""

    def test_five_scanners_share_default_exclude(self):
        from espalier.scanners import (
            exceptions,
            godfiles,
            perf_smells,
            prints,
            test_loosening,
        )

        canon = godfiles.DEFAULT_EXCLUDE
        assert prints.DEFAULT_EXCLUDE == canon
        assert exceptions.DEFAULT_EXCLUDE == canon
        assert perf_smells.DEFAULT_EXCLUDE == canon
        assert test_loosening.DEFAULT_EXCLUDE == canon


# ---------------------------------------------------------------------------
# 2-D  settings-file candidate list across the three kill-switch scanners
# ---------------------------------------------------------------------------
class TestSettingsCandidatesParity:
    """Binds the third name (``ci_guard._SETTINGS_FILES_FOR_KILL_SWITCH``) that
    nothing currently tests, to the two that are (the integrity hook + selfcheck)."""

    def test_three_settings_candidate_lists_agree(self):
        from espalier import selfcheck

        integrity = _load(HOOKS_DIR / "_integrity.py", "_intg_parity")
        ci_guard = _load(TOOLS_CC / "ci_guard.py", "_ci_settings_parity")

        integrity_posix = {p.as_posix() for p in integrity._SETTINGS_CANDIDATES}
        assert integrity_posix == set(selfcheck._SETTINGS_CANDIDATES)
        assert integrity_posix == set(ci_guard._SETTINGS_FILES_FOR_KILL_SWITCH)


# ---------------------------------------------------------------------------
# 2-E  mutating-tool matcher list across surface_contract / ci_guard / speedbump
# ---------------------------------------------------------------------------
class TestMutationMatcherToolsParity:
    def test_three_mutation_matcher_lists_agree(self):
        from espalier import surface_contract

        ci_guard = _load(TOOLS_CC / "ci_guard.py", "_ci_mut_parity")
        speedbump = _load(HOOKS_DIR / "_speedbump.py", "_sb_parity")

        canon = tuple(surface_contract._MUTATION_MATCHER_TOOLS)
        assert tuple(ci_guard._CI_MUTATION_MATCHER_TOOLS) == canon
        assert tuple(speedbump._MUTATING_TOOLS) == canon


# ---------------------------------------------------------------------------
# 2-F  action-justification hash regex: espalier vs tools/cc cognitive_blueprint
# ---------------------------------------------------------------------------
class TestActionJustificationFieldCapParity:
    """``execution_plan`` clamps to a cap the validator owns; they must agree.

    The planner cannot import the validator (tools/cc runs standalone and
    subprocesses to the sibling CLI), so the cap is a forced copy. If the two
    drift, the clamp either cuts prose the validator would have accepted or
    lets through prose it refuses -- and the refusal path costs the step its
    justification entirely, which is the failure the clamp exists to prevent.
    """

    def test_planner_cap_equals_validator_cap(self):
        from espalier import cognitive_blueprint as e_cb

        tcc_cb = _load(TOOLS_CC / "cognitive_blueprint.py", "_tcc_cb_cap")
        planner = _load(TOOLS_CC / "execution_plan.py", "_planner_cap")
        assert (
            planner._AJ_MAX_FIELD_CHARS
            == tcc_cb._AJ_MAX_FIELD_CHARS
            == e_cb._AJ_MAX_FIELD_CHARS
        ), (
            "action-justification field cap disagrees across the forced copies: "
            f"planner={planner._AJ_MAX_FIELD_CHARS}, "
            f"hook={tcc_cb._AJ_MAX_FIELD_CHARS}, "
            f"library={e_cb._AJ_MAX_FIELD_CHARS}"
        )

    def test_planner_refusal_code_equals_the_validators(self):
        """The planner branches on this number to decide whether to DELETE a record.

        If the two drift, the planner either keeps a refused justification (the
        fail-open this contract's subject was written to close) or deletes an
        accepted one because an unrelated failure came back wearing the refusal
        code. Both are silent.
        """
        tcc_cb = _load(TOOLS_CC / "cognitive_blueprint.py", "_tcc_cb_rc")
        planner = _load(TOOLS_CC / "execution_plan.py", "_planner_rc")
        assert (
            planner._EXIT_JUSTIFICATION_REFUSED
            == tcc_cb._EXIT_JUSTIFICATION_REFUSED
        ), (
            "refusal exit code disagrees: "
            f"planner={planner._EXIT_JUSTIFICATION_REFUSED}, "
            f"validator={tcc_cb._EXIT_JUSTIFICATION_REFUSED}"
        )
        assert (
            tcc_cb._EXIT_NO_ACTIVE_SESSION != tcc_cb._EXIT_JUSTIFICATION_REFUSED
        ), (
            "the no-session and refusal exits collapsed back to one code, so a "
            "caller cannot tell 'your payload is bad' from 'there was nowhere to "
            "write it' -- the distinction an accepted justification depends on"
        )


class TestActionJustificationHashRegexParity:
    def test_aj_hash_re_pattern_matches(self):
        from espalier import cognitive_blueprint as e_cb

        tcc_cb = _load(TOOLS_CC / "cognitive_blueprint.py", "_tcc_cb_parity")
        assert e_cb._AJ_HASH_RE.pattern == tcc_cb._AJ_HASH_RE.pattern


class TestActionJustificationRejectionMessageParity:
    """The twins are pinned on DECISIONS; this pins what they SAY.

    ``test_hook_and_library_agree`` walks an accept/reject matrix, so two
    validators can agree perfectly on every verdict while giving a caller
    different explanations -- and a one-sided message improvement stays green,
    which is how the two bodies drift apart in the first place. The message is
    the whole product here: a rejection a caller cannot act on costs a cycle
    every time it fires.
    """

    # One row per `raise ValueError` in the validator. A single hand-picked case
    # left three of the four raise sites unpinned under a class name promising all
    # of them -- and the `exceeds N chars` message is the likeliest next one to be
    # improved on one side only, since it is what an operator meets when the
    # planner's clamp is bypassed.
    _CASES = {
        "empty prose": dict(goal="", step_rationale="R", expected_outcome="E",
                            not_doing="ND", tool="Bash",
                            content_hash="sha256:" + "a" * 64),
        "over cap": dict(goal="G" * 5000, step_rationale="R", expected_outcome="E",
                         not_doing="ND", tool="Bash",
                         content_hash="sha256:" + "a" * 64),
        "unknown tool": dict(goal="G", step_rationale="R", expected_outcome="E",
                             not_doing="ND", tool="Telepathy",
                             content_hash="sha256:" + "a" * 64),
        # bare hex: the obvious wrong guess, since it is what `shasum` prints
        "bad hash": dict(goal="G", step_rationale="R", expected_outcome="E",
                         not_doing="ND", tool="Bash", content_hash="a" * 64),
    }

    @staticmethod
    def _reject(mod, kwargs):
        import pytest as _pytest

        with _pytest.raises(ValueError) as excinfo:
            mod._validate_action_justification(**kwargs)
        return str(excinfo.value)

    def test_both_twins_explain_every_rejection_identically(self):
        from espalier import cognitive_blueprint as e_cb

        tcc_cb = _load(TOOLS_CC / "cognitive_blueprint.py", "_tcc_cb_msg")
        drifted = {
            label: (self._reject(e_cb, kw), self._reject(tcc_cb, kw))
            for label, kw in self._CASES.items()
            if self._reject(e_cb, kw) != self._reject(tcc_cb, kw)
        }
        assert not drifted, (
            "the two action-justification validators reject the same input with "
            f"different explanations: {drifted}. A caller meeting one of them gets "
            "advice the other does not give."
        )

    def test_the_case_table_covers_every_raise_site(self):
        """Derived floor: a fifth rejection reason must not stay unpinned."""
        body = (TOOLS_CC / "cognitive_blueprint.py").read_text(encoding="utf-8")
        start = body.index("def _validate_action_justification")
        end = body.index("\ndef ", start + 1)
        raises = body[start:end].count("raise ValueError")
        assert len(self._CASES) == raises, (
            f"the validator has {raises} rejection paths but this table pins "
            f"{len(self._CASES)}. An unpinned message can be improved on one side "
            "only, which is exactly how the twins drift."
        )

    def test_the_message_names_the_shape_and_the_flag(self):
        from espalier import cognitive_blueprint as e_cb

        message = self._reject(e_cb, self._CASES["bad hash"])
        assert "sha256:" in message, (
            "the rejection does not state the expected prefix, so the caller "
            "is left to guess at the format"
        )
        assert "--from-tool-input-file" in message, (
            "the CLI already computes this hash from a file, and the error "
            "that fires when someone builds it by hand is the one place that "
            "affordance would actually be read"
        )


# ---------------------------------------------------------------------------
# 2-G  ESPALIER_MEMORY.md date-row regex: cli (hoisted) vs session_start hook
# ---------------------------------------------------------------------------
class TestMemoryDateRegexParity:
    """Both consumers of ``_MEMORY_DATE_RE`` must treat the DATE as recency.

    Pattern-equality alone was not enough, and the proof is historical:
    ``cmd_memory_prune`` was fixed on 2026-05-25 after position-as-recency
    archived the NEWEST rows twice, and five weeks later ``_memory_toc`` was
    written against the same artifact with the same defect -- it served the
    three OLDEST rows under the heading "recent sessions" for ~10 days. This
    class coupled the two sites the whole time and pinned only ``.pattern``,
    so it could not see a second consumer keying on position.
    """

    def test_memory_date_re_pattern_matches(self):
        from espalier import cli

        session_start = _load(HOOKS_DIR / "session_start.py", "_ss_parity")
        assert cli._MEMORY_DATE_RE.pattern == session_start._MEMORY_DATE_RE.pattern

    def test_both_consumers_agree_which_row_is_newest(self, tmp_path):
        """Drive both on ONE fixture whose file order contradicts its dates.

        The hook must surface the date-max row and the cli must archive the
        date-min row, from the same bytes. A consumer that reads position gets
        exactly one of these backwards, which is the whole failure history.

        The two sites key differently ON PURPOSE, and the fixture carries a
        same-date pair at BOTH ends so that difference is actually exercised --
        an earlier version of this test explained the tie semantics at length
        over four distinct dates and zero ties, i.e. asserted none of it.

        Under prepend, within one date the topmost row is the newest:
          * the hook sorts DESCENDING on the date ALONE, so the topmost of a
            tied group leads the digest. A ``(date, index)`` tuple would be
            wrong here -- ``reverse=True`` reverses the index too.
          * the cli sorts ASCENDING with a NEGATED index, so the bottom-most of
            a tied group is the oldest and is archived first. A plain index
            would archive the row the operator just wrote.
        Opposite spellings, one meaning. Copying either site's key into the
        other is the plausible-looking regression, and both directions are
        asserted below.
        """
        from espalier.cli import cmd_memory_prune

        # FOUR rows, deliberately: with exactly `_MEMORY_DIGEST_ROWS` the digest
        # contains every row and "the oldest is excluded" cannot be asserted at
        # all -- the same vacuity that made the original digest fixture useless.
        # The hook renders only the SECOND cell, so the date-max/date-min markers
        # live there; the cli leaves whole rows in the file, so its markers are
        # the third cell.
        # Position and date disagree in both directions ON PURPOSE: a min-date
        # row sits inside the first three positions, so a plain `rows[:N]`
        # head-slice drags it into the digest and fails. Every fixture in this
        # change was originally authored in clean descending order, which left
        # the head-slice mutation green across the entire 8000-test suite.
        rows = [
            "2026-03-05 | NEWESTTOP | notes-newest-top",       # max date, topmost of its day
            "2026-02-01 | OLDA | notes-old-a",                 # min date, but position 2
            "2026-03-05 | NEWESTSECOND | notes-newest-second",  # max date, below NEWESTTOP
            "2026-03-01 | MIDDLEROW | notes-middle",
            "2026-02-01 | OLDB | notes-old-b",                 # min date, BOTTOM-most
        ]
        memory = tmp_path / "ESPALIER_MEMORY.md"
        memory.write_text(
            "# M\n\n## Session Log\n\n"
            "| Date | What Happened | Notes |\n"
            "|------|--------------|-------|\n"
            + "\n".join(f"| {r} |" for r in rows)
            + "\n",
            encoding="utf-8",
        )

        session_start = _load(HOOKS_DIR / "session_start.py", "_ss_parity_drive")
        digest = session_start._memory_toc(tmp_path)
        assert "NEWESTTOP" in digest, f"hook did not surface the date-max row: {digest}"
        assert "OLDA" not in digest and "OLDB" not in digest, (
            f"hook surfaced a date-min row in a 'recent sessions' digest -- a "
            f"positional slice from either end does this: {digest}"
        )
        assert digest.index("NEWESTTOP") < digest.index("NEWESTSECOND"), (
            "within one date the TOPMOST row is the newest under prepend; a "
            "`(date, index)` key under reverse=True inverts this"
        )

        rc = cmd_memory_prune(
            argparse.Namespace(root=str(tmp_path), rows=1, archive=None)
        )
        assert rc == 0
        remaining = memory.read_text(encoding="utf-8")
        assert "notes-old-b" not in remaining, (
            "cli must archive the BOTTOM-most row of the oldest date -- a plain "
            "(not negated) index tie-break archives the top one instead, which "
            "under prepend is the more recently written session"
        )
        assert "notes-old-a" in remaining, "cli archived the wrong row of the tied oldest date"
        assert "notes-newest-top" in remaining, "cli archived the date-max row -- the 2026-05-25 bug"


# ---------------------------------------------------------------------------
# 2-H  runtime-marker set: repo_mode vs session_resume (order-insensitive)
# ---------------------------------------------------------------------------
class TestRuntimeMarkersParity:
    def test_runtime_marker_sets_match(self):
        from espalier import repo_mode

        session_resume = _load(TOOLS_CC / "session_resume.py", "_sr_parity")
        assert set(repo_mode._RUNTIME_MARKERS) == set(session_resume._RUNTIME_MARKERS)


# ---------------------------------------------------------------------------
# 2-I  placeholder-token list: post_write_check hook vs proofs
# ---------------------------------------------------------------------------
class TestPlaceholdersParity:
    def test_placeholder_lists_match(self):
        from espalier import proofs

        pwc = _load(HOOKS_DIR / "post_write_check.py", "_pwc_parity")
        assert pwc.PLACEHOLDERS == proofs.PLACEHOLDERS


# ---------------------------------------------------------------------------
# 2-J  scanner report filenames are a subset of the contract's output suffixes
# ---------------------------------------------------------------------------
class TestReportFilenameSuperset:
    """The forced ``filesystem_contracts`` scanner keeps a superset of report
    filenames (it also lists non-scan outputs); pin that it never DROPS a
    scan_composition report filename."""

    def test_report_files_are_output_suffix_subset(self):
        from espalier import scan_composition
        from espalier.scanners import filesystem_contracts

        report_suffixes = {f"/{name}" for name in scan_composition.REPORT_FILES}
        assert report_suffixes <= set(filesystem_contracts.OUTPUT_FILENAME_SUFFIXES)


# ---------------------------------------------------------------------------
# plan_guard exempt-prefix declaration == _hook_utils universal canon
# ---------------------------------------------------------------------------
class TestExemptUniversalPrefixesParity:
    """plan_guard.EXEMPT_PREFIXES is a doc-pinned literal (AST-walked by
    test_contracts); the operative source is _hook_utils.EXEMPT_UNIVERSAL_PREFIXES,
    which harness_exempt_prefixes derives from. Pin them equal so they cannot drift."""

    def test_plan_guard_literal_equals_hook_utils_canon(self):
        plan_guard = _load(HOOKS_DIR / "plan_guard.py", "_pg_exempt_parity")
        hook_utils = _load(HOOKS_DIR / "_hook_utils.py", "_hu_exempt_parity")
        assert set(plan_guard.EXEMPT_PREFIXES) == set(
            hook_utils.EXEMPT_UNIVERSAL_PREFIXES
        )


# ---------------------------------------------------------------------------
# cli scanner-report writes cover every scan_composition.REPORT_FILES filename
# ---------------------------------------------------------------------------
class TestCliReportFilenamesCoverCanon:
    """cli writes each scanner report to a distinct filename inline (each wired to a
    distinct producer, so it is deliberately not a loop over REPORT_FILES). Guard
    that the inline write-set covers every canonical scan_composition.REPORT_FILES
    name — a scanner added to the canon but not wired into cli would silently drop
    its report file."""

    def test_cli_writes_every_canonical_report_file(self):
        from espalier import scan_composition

        cli_src = (REPO_ROOT / "espalier" / "cli.py").read_text(encoding="utf-8")
        written = set(re.findall(r'reports_dir / "([^"]+\.json)"', cli_src))
        missing = set(scan_composition.REPORT_FILES) - written
        assert not missing, (
            f"cli.py does not write these canonical report files: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# plan_guard root plan-gate covers the full source-language core
# ---------------------------------------------------------------------------
class TestPlanGateCoversSourceLanguages:
    """plan_guard's root plan-gate must require a plan for EVERY source language
    reflect tracks — else a flat-layout adopter's root ``app.rb`` (or .php/.cs/
    .swift/.kt/.scala) is reflect-tracked but escapes plan discipline (the pre-fix
    under-gating bug). Polyglot magnitude is UNVERIFIED-ON-HOST: the Python
    self-host repo has no root .rb/.swift to exercise the miss, so this
    contract-locks the ⊇ invariant instead of demonstrating the runtime effect."""

    def test_plan_required_superset_of_source_languages(self):
        plan_guard = _load(HOOKS_DIR / "plan_guard.py", "_pg_srclang")
        hook_utils = _load(HOOKS_DIR / "_hook_utils.py", "_hu_srclang")
        assert (
            hook_utils.SOURCE_LANGUAGE_EXTENSIONS
            <= plan_guard.PLAN_REQUIRED_ROOT_EXTENSIONS
        )
