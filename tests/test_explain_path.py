"""TP-332 — `/status --explain <path>` per-path enforcement read-out.

The resolver ``tools/cc/hooks/_explain_path.py`` reports, for a repo-relative
path, what the path-conditioned hooks (plan_guard, write_guard) WOULD do — and
it must derive every verdict from the hooks' OWN predicates, never a
re-implementation. A read-out that computed protection/exemption differently
from what the hooks enforce would lie with authority (the canon-vs-claim class).

Earn-the-red: before ``_explain_path.py`` exists, every test here fails
(the loader raises on the missing module; the ``--explain`` submode is unwired).

Anti-drift is pinned three ways, strongest first:
  1. DELEGATION (``test_delegates_to_live_*``) — monkeypatch the live predicate
     object the resolver imported and assert the resolver's verdict follows. A
     copied-logic resolver ignores the patch and fails. This catches the copy on
     the FIRST commit, not only after a predicate later changes.
  2. VALUE CROSS-CHECK (``test_verdict_equals_live_predicate``) — the resolver's
     static verdict equals ``_protected_zones._is_protected``/``_is_allowed`` and
     ``plan_guard._is_exempt`` for a discriminating sample. Reds forever-after if
     a predicate changes and the resolver drifts.
  3. NO COPIED LOGIC (``test_no_copied_predicate_constants``) — an AST/grep check
     that the resolver holds no copied zone/exempt constant tables.

The cross-check pins to the LOW-LEVEL predicates, never ``check_write_edit`` —
that folds in the live ``ESPALIER_MAINTENANCE_MODE`` bypass + dangerous-bash
checks and would false-red under MAINTENANCE=on (the host may run that way). The
resolver reports maintenance mode + active-plan state as SEPARATE live notes.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

# Marker assignment lives in tests/conftest.py::_MARKER_RULES (security group);
# the subprocess submode test enrolls the file in _SLOW_FILES.


def _load_modules():
    """Load ``_explain_path`` by file path (no plain import — that would drag
    espalier into the hook's zero-import graph). Return the resolver together
    with the SAME ``_protected_zones`` / ``plan_guard`` instances it imported,
    so a test can monkeypatch the live predicate object the resolver delegates
    to (see the delegation tests)."""
    candidate = HOOKS_DIR / "_explain_path.py"
    assert candidate.exists(), f"resolver not yet implemented: {candidate}"
    spec = importlib.util.spec_from_file_location("_explain_path", candidate)
    if spec is None or spec.loader is None:  # pragma: no cover - loader always present
        raise FileNotFoundError(candidate)
    ep = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ep  # register before exec (importlib idiom; a 3.14 dataclass needs it)
    spec.loader.exec_module(ep)  # runs the module's own sys.path.insert -> siblings resolve
    return ep, sys.modules["_protected_zones"], sys.modules["plan_guard"]


# Paths whose classification is context-independent (hold on self-host AND on a
# fresh adopter repo): the sample discriminates BOTH outcomes for each predicate.
_SAMPLE_PATHS = (
    "tools/cc/hooks/write_guard.py",   # protected zone, plan-exempt (harness)
    "cc/blueprints/node.md",           # protected zone, plan-exempt
    "cc/GOAL.md",                      # protected zone BUT allowlisted -> not denied
    ".espalier/integrity.json",        # exact protected file, NOT plan-exempt
    "src/app.py",                      # unprotected, plan-REQUIRED (non-root source)
    "README.md",                       # unprotected, plan-REQUIRED (listed root doc)
    "NOTES.md",                        # unprotected, plan-exempt (root non-listed non-source)
)


class TestExplainPathResolver:
    """Known-answer correctness for representative paths."""

    def test_protected_zone_write_denied(self):
        ep, _, _ = _load_modules()
        exp = ep.explain("tools/cc/hooks/write_guard.py", REPO_ROOT)
        assert exp.protected is True
        assert exp.allowed is False
        assert exp.write_denied is True
        assert "tools/cc/" in exp.write_zone

    def test_allowlisted_within_protected_not_denied(self):
        ep, _, _ = _load_modules()
        exp = ep.explain("cc/GOAL.md", REPO_ROOT)
        assert exp.protected is True
        assert exp.allowed is True
        assert exp.write_denied is False

    def test_exact_protected_file_denied(self):
        ep, _, _ = _load_modules()
        exp = ep.explain(".espalier/integrity.json", REPO_ROOT)
        assert exp.write_denied is True

    def test_harness_zone_is_plan_exempt(self):
        ep, _, _ = _load_modules()
        exp = ep.explain("tools/cc/hooks/write_guard.py", REPO_ROOT)
        assert exp.plan_exempt is True
        assert exp.plan_required is False

    def test_non_root_source_requires_plan(self):
        ep, _, _ = _load_modules()
        exp = ep.explain("src/app.py", REPO_ROOT)
        assert exp.protected is False
        assert exp.write_denied is False
        assert exp.plan_exempt is False
        assert exp.plan_required is True

    def test_listed_root_doc_requires_plan(self):
        # README.md is in plan_guard.PLAN_REQUIRED_ROOT_FILES -> plan-required
        # (verified against the predicate, not assumed).
        ep, _, _ = _load_modules()
        assert ep.explain("README.md", REPO_ROOT).plan_required is True

    def test_root_non_listed_non_source_is_plan_exempt(self):
        ep, _, _ = _load_modules()
        exp = ep.explain("NOTES.md", REPO_ROOT)
        assert exp.plan_exempt is True

    def test_render_is_readable_text(self):
        ep, _, _ = _load_modules()
        text = ep.render(ep.explain("tools/cc/hooks/write_guard.py", REPO_ROOT))
        assert "tools/cc/hooks/write_guard.py" in text
        # net one-line verdict present
        assert "plan" in text.lower() and "write" in text.lower()


class TestExplainPathAntiDrift:
    """The read-out is PINNED to the hooks' own predicates, not a re-derivation."""

    def test_verdict_equals_live_predicate(self):
        ep, pz, pg = _load_modules()
        for path in _SAMPLE_PATHS:
            exp = ep.explain(path, REPO_ROOT)
            rel = exp.rel
            assert exp.protected == pz._is_protected(rel, REPO_ROOT), path
            assert exp.allowed == pz._is_allowed(rel), path
            assert exp.write_denied == (
                pz._is_protected(rel, REPO_ROOT) and not pz._is_allowed(rel)
            ), path
            assert exp.plan_exempt == pg._is_exempt(rel, REPO_ROOT), path
            assert exp.plan_required == (not pg._is_exempt(rel, REPO_ROOT)), path

    def test_sample_discriminates_both_outcomes(self):
        # A cross-check where every path lands the same way proves nothing; the
        # sample must exercise True AND False for each pinned predicate.
        ep, _, _ = _load_modules()
        results = [ep.explain(p, REPO_ROOT) for p in _SAMPLE_PATHS]
        assert {r.write_denied for r in results} == {True, False}
        assert {r.plan_required for r in results} == {True, False}
        assert {r.allowed for r in results} == {True, False}

    def test_rel_uses_shared_normalizer(self):
        # The resolver must normalize the raw path the SAME way the hooks do
        # (via _hook_utils.normalize_path) so its verdict lines up with theirs.
        ep, _, _ = _load_modules()
        hook_utils = sys.modules["_hook_utils"]
        for path in _SAMPLE_PATHS:
            exp = ep.explain(path, REPO_ROOT)
            assert exp.rel == hook_utils.normalize_path(path, REPO_ROOT), path

    def test_delegates_to_live_protected_predicate(self, monkeypatch):
        # Monkeypatch the live predicate object the resolver imported; a
        # delegating resolver's verdict follows the patch, a copied-logic one
        # does not. Proves reuse on the FIRST commit.
        ep, pz, _ = _load_modules()
        monkeypatch.setattr(pz, "_is_protected", lambda rel, root: True)
        monkeypatch.setattr(pz, "_is_allowed", lambda rel: False)
        exp = ep.explain("totally/unprotected/note.txt", REPO_ROOT)
        assert exp.protected is True
        assert exp.write_denied is True

    def test_delegates_to_live_exempt_predicate(self, monkeypatch):
        ep, _, pg = _load_modules()
        monkeypatch.setattr(pg, "_is_exempt", lambda rel, root: True)
        exp = ep.explain("src/definitely_gated.py", REPO_ROOT)
        assert exp.plan_exempt is True
        assert exp.plan_required is False

    def test_no_copied_predicate_constants(self):
        # Structural guard: the resolver must not hold its own copy of the zone
        # or exempt constant tables (a copy silently drifts from the SoT).
        src = (HOOKS_DIR / "_explain_path.py").read_text(encoding="utf-8")
        for forbidden in (
            "PROTECTED_PREFIXES =",
            "PROTECTED_FILES =",
            "ALLOWED_IN_PROTECTED =",
            "ALLOWED_PREFIXES_IN_PROTECTED =",
            "EXEMPT_UNIVERSAL_PREFIXES =",
            "EXEMPT_PREFIXES =",
            "PLAN_REQUIRED_ROOT_FILES =",
            "PLAN_REQUIRED_ROOT_EXTENSIONS =",
        ):
            assert forbidden not in src, (
                f"_explain_path.py appears to COPY {forbidden!r} — import the "
                "predicate siblings instead; a copied table drifts from the SoT."
            )
        # And it must actually CALL the predicates.
        assert "_is_protected" in src and "_is_allowed" in src
        assert "_is_exempt" in src


class TestPlanRuleLabels:
    """The plan_rule 'why' text mirrors ``_is_exempt``'s precedence and must not
    offer a remedy that cannot work — the reason-text analogue of the boolean
    pin. Both convergent reviews reproduced label bugs here; these pin them."""

    def test_listed_root_doc_label_is_not_exemptible(self):
        # README.md is in plan_guard.PLAN_REQUIRED_ROOT_FILES -> the `./` sentinel
        # can NEVER exempt it (that branch short-circuits first in _is_exempt).
        # The label must not dangle a `plan_exempt_prefixes` opt-out that fails.
        ep, _, _ = _load_modules()
        rule = ep.explain("README.md", REPO_ROOT).plan_rule
        assert rule.startswith("plan required")
        assert "not exemptible" in rule
        assert "opt out" not in rule.lower()

    def test_root_source_sentinel_exemption_labeled_as_source(self, tmp_path):
        # With plan_exempt_prefixes = ["./"], a root .py is exempt VIA the sentinel
        # and must be labeled source-opted-out, never "non-source file".
        (tmp_path / "espalier.toml").write_text(
            'plan_exempt_prefixes = ["./"]\n', encoding="utf-8"
        )
        ep, _, _ = _load_modules()
        exp = ep.explain("app.py", tmp_path)
        assert exp.plan_exempt is True  # boolean still pinned to _is_exempt
        assert "root-level source opted out" in exp.plan_rule
        assert "non-source" not in exp.plan_rule

    def test_plan_rule_direction_matches_boolean(self):
        # Whenever the label says "exempt", the boolean is exempt; whenever "plan
        # required", the boolean is required — pins the label's DIRECTION to the
        # predicate even though its wording re-derives the branch reason.
        ep, _, _ = _load_modules()
        for path in _SAMPLE_PATHS:
            exp = ep.explain(path, REPO_ROOT)
            if exp.plan_exempt:
                assert exp.plan_rule.startswith("exempt"), (path, exp.plan_rule)
            else:
                assert exp.plan_rule.startswith("plan required"), (path, exp.plan_rule)


class TestExplainSubmodeRobustness:
    """``session_resume.py --explain`` must never crash /status — the guard covers
    the render, not just the resolver import (a future FS-touching predicate could
    raise)."""

    def test_submode_degrades_when_resolver_raises(self, monkeypatch, tmp_path, capsys):
        import types

        from tools.cc.session_resume import _print_path_explanation

        def _boom(path, root):
            raise RuntimeError("boom")

        fake = types.ModuleType("_explain_path")
        fake.explain = _boom
        fake.render = lambda exp: str(exp)
        monkeypatch.setitem(sys.modules, "_explain_path", fake)

        rc = _print_path_explanation(tmp_path, "src/app.py")
        assert rc == 0  # never crashes /status
        assert "unavailable" in capsys.readouterr().err


class TestExplainPathLiveNotes:
    """Live session state is REPORTED (like maintenance mode), never folded into
    the anti-drift path pin."""

    def test_maintenance_mode_reflects_live_env(self, monkeypatch):
        ep, _, _ = _load_modules()
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
        assert ep.explain("tools/cc/hooks/write_guard.py", REPO_ROOT).maintenance_active is True
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)
        assert ep.explain("tools/cc/hooks/write_guard.py", REPO_ROOT).maintenance_active is False

    def test_maintenance_verdict_does_not_overclaim(self, monkeypatch):
        # Under maintenance mode write_guard STILL denies kill-switch +
        # dangerous-command; the verdict must not claim "nothing is denied".
        ep, _, _ = _load_modules()
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
        verdict = ep.explain("tools/cc/hooks/write_guard.py", REPO_ROOT).verdict
        assert "MAINTENANCE MODE active" in verdict
        assert "nothing is denied" not in verdict
        assert "kill-switch" in verdict


class TestStatusExplainSubmode:
    """``session_resume.py --explain <path>`` prints the read-out, read-only."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--explain", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            env=env, encoding="utf-8",
        )

    def test_explain_prints_verdict_for_protected_path(self):
        result = self._run("tools/cc/hooks/write_guard.py")
        assert result.returncode == 0, result.stderr
        out = result.stdout.lower()
        assert "tools/cc/hooks/write_guard.py" in result.stdout
        assert "protected" in out
        assert "plan" in out

    def test_explain_prints_verdict_for_source_path(self):
        result = self._run("src/app.py")
        assert result.returncode == 0, result.stderr
        assert "src/app.py" in result.stdout

    def test_explain_is_read_only_and_exits_zero(self):
        # No mutation, always exits 0 even for an unremarkable path.
        result = self._run("docs/whatever.md")
        assert result.returncode == 0, result.stderr


class TestNetVerdictPlanClause:
    """TP-353's skipped optional 1-D: the plan clause states BOTH outcomes.

    The read-out was already fail-safe in this direction — with a plan active it
    simply omitted the clause, so it never claimed an edit would be blocked when
    it would not — but silence reads as "unknown" rather than "satisfied".
    Cosmetic legibility, explicitly NOT a defect; the ceiling is pinned here so
    nobody promotes it later.
    """

    @staticmethod
    def _verdict(plan_active: bool) -> str:
        ep, _, _ = _load_modules()
        return ep._net_verdict(
            write_denied=False, allowed=True, protected=False, write_zone="",
            plan_required=True, plan_active=plan_active, maintenance_active=False,
        )

    # Assert on the SEPARATOR-anchored form: "none is active" literally contains
    # "one is active" as a substring, so a bare `not in` check can never
    # distinguish the branches and would pass vacuously in one direction.
    def test_active_plan_states_the_positive_case(self):
        verdict = self._verdict(True)
        assert "; one is active" in verdict, verdict
        assert "none is active" not in verdict, verdict

    def test_absent_plan_still_states_the_negative_case(self):
        verdict = self._verdict(False)
        assert "; none is active" in verdict, verdict
        assert "; one is active" not in verdict, verdict
