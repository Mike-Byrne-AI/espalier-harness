"""Schema parity between the library and hook-side cognitive_blueprint.

Espalier-Harness has two cognitive_blueprint implementations:

- ``espalier/cognitive_blueprint.py`` (library) — used by ``espalier
  blueprint`` and the proofs pipeline. Reads/writes via the
  ``CognitiveBlueprint`` dataclass from ``espalier.models``.
- ``tools/cc/cognitive_blueprint.py`` (hook-side standalone CLI) — invoked
  by ``/handoff``, ``/implement-task``, ``/reflect``. Reads/writes plain
  dicts (no espalier imports — isolation rule).

Both write to ``cc/blueprints/{session_id}.json`` so they share an
on-disk schema. The docstring in the hook-side file says "Bug fixes that
affect both concerns must be applied to both files. There is no parity
test because the files measure different things." That covered the
*input/output shape* (dataclass vs dict, library functions vs CLI
subcommands) — but the storage schema must match across the boundary.

Pre-fix: hook-side ``cmd_start`` wrote 13 top-level keys; library
``CognitiveBlueprint`` declared 15 (added ``agents`` + ``commands``).
A hookside→library round trip silently dropped those two fields
because library ``from_dict()`` defaulted them to ``[]``. This test
pins the storage schema as a contract between the two implementations.

Architecture-analyst flagged this as TENSION 3 in the post-Sprint-6
review.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SIDE_SCRIPT = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"


def _load_hookside_module():
    """Load the hook-side script as a module so we can introspect it."""
    spec = importlib.util.spec_from_file_location(
        "hookside_cognitive_blueprint", HOOK_SIDE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["hookside_cognitive_blueprint"] = module
    spec.loader.exec_module(module)
    return module


def _make_marker_repo(tmp_path: Path) -> Path:
    """Build a minimal tree with the markers ``_repo_root`` looks for."""
    repo = tmp_path / "repo"
    (repo / "tools" / "cc").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'fake'\nversion = '0.0.0'\n", encoding="utf-8",
    )
    reports = repo / "reports"
    reports.mkdir()
    (reports / "repo_fingerprint.json").write_text(
        '{"repo_name": "fake"}', encoding="utf-8",
    )
    (reports / "harness_config.json").write_text("{}", encoding="utf-8")
    (reports / "cc_surface_gate.json").write_text(
        '{"status": "pass"}', encoding="utf-8",
    )
    return repo


class TestCognitiveBlueprintSchemaParity:
    """Hook-side and library implementations must agree on the on-disk schema."""

    def test_hookside_writes_same_top_level_keys_as_library_declares(self, tmp_path):
        """The dict hook-side ``cmd_start`` writes must contain every field
        the library dataclass declares (modulo dataclass-only metadata).

        Failure mode this guards against: a contributor adds a new field to
        ``CognitiveBlueprint`` (library) but forgets to mirror it in
        ``tools/cc/cognitive_blueprint.py:cmd_start`` — hookside-started
        sessions then silently lose that field on every library round trip.
        """
        # Library schema — top-level dataclass fields
        from espalier.models import CognitiveBlueprint
        library_fields = {f.name for f in fields(CognitiveBlueprint)}

        # Hook-side schema — invoke `start` in a tmp marker repo and read
        # the resulting JSON
        repo = _make_marker_repo(tmp_path)
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        result = subprocess.run(
            [sys.executable, str(HOOK_SIDE_SCRIPT), "start"],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, (
            f"hook-side start failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        latest = repo / "cc" / "blueprints" / "latest.json"
        assert latest.exists(), f"hook-side did not write blueprint to {latest}"
        hookside_data = json.loads(latest.read_text(encoding="utf-8"))
        hookside_keys = set(hookside_data.keys())

        missing_in_hookside = library_fields - hookside_keys
        assert not missing_in_hookside, (
            f"Hook-side cmd_start writes a blueprint missing fields the library "
            f"dataclass declares: {sorted(missing_in_hookside)}. Add the fields "
            f"to the bp dict in tools/cc/cognitive_blueprint.py::cmd_start with "
            f"sensible defaults (typically [] or '' to match the library)."
        )

    def test_library_round_trip_through_hookside_blueprint_preserves_all_fields(self, tmp_path):
        """A blueprint hook-side wrote must load via library ``from_dict()``
        without silently defaulting any field.

        End-to-end version of the schema-parity check: catches not just key
        presence but also type/shape compatibility (e.g., if hook-side wrote
        ``agents`` as a string instead of a list, library ``from_dict()``
        would crash or silently mis-interpret).
        """
        from espalier.cognitive_blueprint import load_latest_blueprint

        repo = _make_marker_repo(tmp_path)
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        result = subprocess.run(
            [sys.executable, str(HOOK_SIDE_SCRIPT), "start"],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr

        bp = load_latest_blueprint(repo)
        assert bp is not None, "library failed to load hook-side-written blueprint"
        assert bp.session_id, "session_id missing or empty after round trip"
        assert bp.repo_name == "fake"
        # Default-initialized lists should be empty lists, not None
        assert bp.agents == []
        assert bp.commands == []
        assert bp.reasoning_entries == []
        assert bp.reflect_passes == []


class TestReflectFieldSetParity:
    """TP-151 C-3: the hook-side reflect field-set literals — used by
    ``cmd_record_reflect`` to project report dicts onto the known shape at
    the WRITER (defense in depth with the library reader-side ``_only()``
    filter) — must match the library ``ReflectPass`` / ``ReflectFinding``
    dataclass fields exactly.

    The hook cannot import ``espalier.models`` (``tools/cc/`` isolation
    rule), so the key sets are hardcoded in the hook. This is the parity
    contract that keeps them honest: it introspects the hook module's
    literals directly (no hook-side espalier import) and compares against
    the library fields read via import. Without it, a new ``ReflectPass``
    field would silently fall outside the hook's projection and be dropped
    on every reflect-pass write.
    """

    def test_reflect_pass_field_set_matches_library(self):
        from espalier.models import ReflectPass

        module = _load_hookside_module()
        assert set(module._REFLECT_PASS_FIELDS) == {
            f.name for f in fields(ReflectPass)
        }, (
            "hook-side _REFLECT_PASS_FIELDS drifted from "
            "espalier.models.ReflectPass; update the literal in "
            "tools/cc/cognitive_blueprint.py"
        )

    def test_reflect_finding_field_set_matches_library(self):
        from espalier.models import ReflectFinding

        module = _load_hookside_module()
        assert set(module._REFLECT_FINDING_FIELDS) == {
            f.name for f in fields(ReflectFinding)
        }, (
            "hook-side _REFLECT_FINDING_FIELDS drifted from "
            "espalier.models.ReflectFinding; update the literal in "
            "tools/cc/cognitive_blueprint.py"
        )


class TestReasoningEntryFieldSetParity:
    """TP-241: the hook-side ``cmd_record`` written reasoning-entry keys must
    match the library ``ReasoningEntry`` dataclass fields exactly. The
    top-level-keys parity test (above) checks ``CognitiveBlueprint`` fields, not
    nested entry fields -- so without THIS gate, adding a field (e.g.
    ``carry_forward``) to ``ReasoningEntry`` but not to ``cmd_record`` (or vice
    versa) silently drops it on round-trips. Behavioral: record via the hook CLI
    and compare the written keys to ``fields(ReasoningEntry)``.
    """

    SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "cc" / "cognitive_blueprint.py"

    def test_cmd_record_keys_match_library_reasoning_entry(self, tmp_path):
        from espalier.models import ReasoningEntry

        repo = tmp_path / "repo"
        (repo / "tools" / "cc").mkdir(parents=True)
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        subprocess.run(
            [sys.executable, str(self.SCRIPT), "start"],
            cwd=str(repo), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(self.SCRIPT), "record", "--kind", "decision",
             "--description", "x"],
            cwd=str(repo), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        latest = json.loads((repo / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        entry = latest["reasoning_entries"][-1]
        assert set(entry.keys()) == {f.name for f in fields(ReasoningEntry)}, (
            "hook cmd_record's reasoning-entry keys drifted from "
            "espalier.models.ReasoningEntry; update tools/cc/cognitive_blueprint.py"
        )


class TestPinnedFragmentParity:
    """The carry_forward pin must reach continuation_fragments on BOTH sides.

    For six consecutive sessions a handoff recorded pins that went nowhere. Both
    implementations derived their fragments from ``decisions[-3:]`` +
    ``patterns[-2:]`` and never read ``carry_forward`` -- so ``--carry-forward``
    and ``pin <i>`` were inert in the one function that builds what the NEXT
    session reads, and an ``alternative_rejected`` entry was dropped outright
    because no branch collected that kind. The reinjection selection in the same
    files DID honour pins, which is why the defect read as "pinning sort of
    works" for so long.
    """

    SCRIPT = HOOK_SIDE_SCRIPT

    def test_label_map_and_cap_agree_across_the_boundary(self):
        """A forced copy across the no-import boundary, pinned rather than hoped.

        ``tools/cc/`` cannot import espalier, so the label vocabulary exists
        twice by necessity. That is exactly the shape this repo pins instead of
        trusting.
        """
        from espalier.cognitive_blueprint import (
            _ACTIVITY_LOG_PREFIX,
            FRAGMENT_LABELS,
            MAX_PINNED_FRAGMENTS,
        )

        hook = _load_hookside_module()
        assert hook._FRAGMENT_LABELS == FRAGMENT_LABELS
        assert hook._MAX_PINNED_FRAGMENTS == MAX_PINNED_FRAGMENTS
        # The activity-log prefix joined this set when the filter it keys was
        # hoisted into a predicate. Its two neighbours above were pinned here and
        # it was not -- which would have left a THIRD forced copy free to drift,
        # inside the very change that fixed a drift of the same shape. The
        # predicates themselves are deliberately NOT compared: the engine side
        # accepts dataclass entries as well as dicts, so only the VALUE is common.
        assert hook._ACTIVITY_LOG_PREFIX == _ACTIVITY_LOG_PREFIX

    def test_library_side_pins_reach_fragments(self):
        from espalier.cognitive_blueprint import auto_continuation_fragments
        from espalier.models import CognitiveBlueprint, ReasoningEntry

        bp = CognitiveBlueprint(session_id="s", repo_name="r", timestamp="t")
        bp.reasoning_entries.append(ReasoningEntry(
            kind="alternative_rejected", description="PINNED-ALT", carry_forward=True))
        bp.reasoning_entries.append(ReasoningEntry(
            kind="decision", description="plain-decision"))
        bp.reasoning_entries.append(ReasoningEntry(
            kind="decision", description="held-decision", carry_forward=True))
        frags = auto_continuation_fragments(bp)

        assert any("PINNED-ALT" in f for f in frags), (
            "a pinned alternative_rejected entry never reaches the next session"
        )
        assert frags[0].endswith("held-decision") or frags[0].endswith("PINNED-ALT"), (
            "pinned entries must lead -- importance over recency"
        )
        assert sum("held-decision" in f for f in frags) == 1, (
            "a pinned decision must not also be emitted by the recency backfill"
        )
        assert any("plain-decision" in f for f in frags), (
            "pinning must not displace the ordinary recency backfill"
        )

    def test_hook_side_pins_reach_fragments(self, tmp_path):
        """Driven through the real CLI, not the internals -- the defect lived in
        the command, and only an end-to-end run proves the command is fixed."""
        repo = tmp_path / "repo"
        (repo / "tools" / "cc").mkdir(parents=True)
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)

        def run(*args):
            return subprocess.run(
                [sys.executable, str(self.SCRIPT), *args],
                cwd=str(repo), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
            )

        run("start")
        run("record", "--kind", "alternative_rejected", "--carry-forward",
            "--description", "PINNED-ALT")
        run("record", "--kind", "decision", "--description", "plain-decision")
        run("finalize")

        latest = json.loads((repo / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        frags = latest["continuation_fragments"]
        assert any("PINNED-ALT" in f for f in frags), (
            f"pinned entry absent from continuation_fragments: {frags}"
        )
        assert any("plain-decision" in f for f in frags), frags
        assert len(frags) == len(set(frags)), f"duplicate fragments: {frags}"


class TestAgentReportBoundParity:
    """DEF-586: the agent-report fragment bound joins the forced-copy set the
    activity-log prefix is already pinned in. Two twins, one value, pinned
    rather than hoped -- the predicates themselves are not compared (the engine
    side accepts dataclass entries as well as dicts)."""

    def test_agent_report_bound_agrees_across_the_boundary(self):
        from espalier.cognitive_blueprint import MAX_AGENT_FRAGMENTS

        hook = _load_hookside_module()
        assert hook._MAX_AGENT_FRAGMENTS == MAX_AGENT_FRAGMENTS
        assert MAX_AGENT_FRAGMENTS == 2, (
            "two matches the repo's own two-reviewer dispatch; a larger bound "
            "spends the 6 KB blueprint banner share on agent leads"
        )
