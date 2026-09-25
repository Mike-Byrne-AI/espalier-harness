"""TP-188: the /reflect memory-promotion candidate detector (hook-side).

Pins ``tools/cc/reflect_protocol.memory_candidates`` — the mechanical half of
the push side of the recall engine. The detector filters a session's blueprint
reasoning entries to durable-shaped ones and attaches the nearest existing
``memory/`` note (via the ``_recall`` ranker) as advisory context. The skill
body + operator make the promote-vs-append-vs-skip call; the detector writes
nothing (propose-not-write).

Earn-the-red is the §6 replay: a genuine pattern surfaces as a candidate while
a pure session-history line is suppressed. The two filters that bite are the
durability PRE-FILTER (eligible kind + not-session-history) — NOT the recall
floor, which (measured against the live 134-doc corpus, deviation TP-188-A) is a
relatedness oracle, not a duplicate oracle: both a real insight and pure history
clear it by matching a tangentially-related note. This contract is what keeps a
refactor from quietly turning the candidate pass into alert-fatigue (everything
surfaces) or a no-op (nothing surfaces).

Note: this is the HOOK-SIDE reflect_protocol (``tools/cc/reflect_protocol.py``),
a different file from the library ``espalier.reflect_protocol`` pinned by
``tests/test_reflect_protocol.py``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK_SIDE = REPO_ROOT / "tools" / "cc" / "reflect_protocol.py"
_REFLECT_SKILL_SOT = REPO_ROOT / ".claude" / "skills" / "reflect" / "SKILL.md"


def _load_hookside():
    spec = importlib.util.spec_from_file_location("_tp188_reflect_protocol", _HOOK_SIDE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rp = _load_hookside()


def _entry(kind, description):
    return {"kind": kind, "description": description, "evidence": [],
            "session_id": "s", "timestamp": "t"}


# The two §6 earn-the-red inputs.
_RENDER_PARSE = _entry(
    "pattern_discovered",
    "render→parse dedup: write and key must use the same render path",
)
_SESSION_HISTORY = _entry(
    "decision",
    "TP-186 executed, suite 5396 passed and committed to main",
)
# The one machine-generated noise shape (subagent_stop.py auto-records these).
_SUBAGENT_LOG = _entry(
    "pattern_discovered",
    "[subagent:code-reviewer] completed; output captured in parent stream",
)


def _make_corpus(root: Path, notes: dict[str, str]) -> None:
    """Write a controlled memory/ corpus under ``root`` (no SHARP_EDGES, no
    exemplars — ``root`` is not the self-host repo, so _recall loads only these)."""
    mem = root / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    for name, body in notes.items():
        (mem / name).write_text(body, encoding="utf-8")


# ── The durability pre-filter is the real suppressor ──────────────────────────

class TestDurabilityPreFilter:
    def test_eligible_kinds_are_exactly_the_three(self):
        assert rp._ELIGIBLE_KINDS == frozenset(
            {"decision", "pattern_discovered", "alternative_rejected"}
        )

    def test_reflect_insight_kind_is_excluded(self, tmp_path):
        # reflect_insight excluded so /reflect can't recurse on its own findings.
        entries = [_entry("reflect_insight",
                          "the matrix builder should unify the orphan and gap walks")]
        assert rp.memory_candidates(tmp_path, entries) == []

    def test_alternative_rejected_is_included_D2(self, tmp_path):
        # D2 (operator): widened past the pack's recommendation to include this.
        entries = [_entry("alternative_rejected",
                          "rejected a deny-hook forcing the schema: over-fires and kills novel shapes")]
        out = rp.memory_candidates(tmp_path, entries)
        assert len(out) == 1
        assert out[0]["kind"] == "alternative_rejected"

    def test_too_short_entry_is_dropped(self, tmp_path):
        entries = [_entry("decision", "did a thing")]
        assert rp.memory_candidates(tmp_path, entries) == []

    def test_within_session_dedup(self, tmp_path):
        entries = [
            _entry("pattern_discovered", "the same insight stated once and then again"),
            _entry("decision", "The same insight stated once and then  again "),
        ]
        assert len(rp.memory_candidates(tmp_path, entries)) == 1

    def test_no_eligible_entries_yields_empty(self, tmp_path):
        # Suppress-on-no-match at the level that actually works.
        entries = [_entry("reflect_insight", "x" * 40), _entry("decision", "short")]
        assert rp.memory_candidates(tmp_path, entries) == []

    def test_non_dict_entries_are_skipped(self, tmp_path):
        entries = ["not a dict", None, 42, _entry("decision",
                   "a genuinely durable decision worth keeping around")]
        out = rp.memory_candidates(tmp_path, entries)
        assert len(out) == 1


# ── The session-history suppressor (_HISTORY_RE) ──────────────────────────────

class TestNoRegexHistorySuppression:
    """Deviation TP-188-B (operator-decided): there is NO regex history
    suppressor. The live dogfood proved this repo embeds pack-ids and "suite
    NNNN" counts inside genuinely durable decisions, so any id/tally heuristic
    false-positives real insights — and dropping a durable insight is
    asymmetrically worse than leaking one skippable terse-history row. So:
    durable pack-lessons AND count-quoting insights AND terse history all
    SURFACE; the durability call is the skill body's + operator's."""

    def test_history_regex_symbol_is_gone(self):
        assert not hasattr(rp, "_HISTORY_RE")

    @pytest.mark.parametrize("text", [
        # Adversarial review #3 repros — durable lessons reasoning ABOUT a
        # landed/committed pack must NOT be dropped.
        "After TP-180 landed, non-git host refusal must precede init or rollback breaks",
        "the rollback pattern we shipped in TP-180 should be reused for the fuse path",
        "when TP-169 was committed we still saw the ReDoS class in two unbound surfaces",
        # The live-dogfood false-positive: a durable insight quoting a suite count.
        "recall is a relatedness oracle; both probes cleared the floor in the suite 5396 era",
    ])
    def test_durable_text_with_ids_or_counts_surfaces(self, tmp_path, text):
        assert len(rp.memory_candidates(tmp_path, [_entry("decision", text)])) == 1

    def test_terse_history_now_surfaces_for_operator_skip(self, tmp_path):
        # Reframed §6-b: a terse "TP-186 executed, suite 5396" decision is no
        # longer mechanically suppressed — it surfaces as one skippable candidate
        # (kind=decision, not [subagent:], len>=25); the operator marks 'skip'.
        out = rp.memory_candidates(tmp_path, [_SESSION_HISTORY])
        assert len(out) == 1
        assert "5396" in out[0]["text"]


class TestActivityLogSuppressor:
    """Adversarial review #1 (theater-noise): subagent_stop.py auto-records every
    subagent completion as a `pattern_discovered` "[subagent:<type>] ..." entry —
    the single largest source of pattern_discovered rows. They must not flood the
    candidate list."""

    def test_subagent_activity_log_is_dropped(self, tmp_path):
        entries = [_entry("pattern_discovered",
                   "[subagent:code-reviewer] completed; output captured in parent stream")]
        assert rp.memory_candidates(tmp_path, entries) == []

    def test_subagent_prefix_drop_is_exact(self, tmp_path):
        # A genuine insight that merely mentions the word subagent is NOT dropped.
        entries = [_entry("pattern_discovered",
                   "subagent reasoning should append to the active blueprint, never block")]
        assert len(rp.memory_candidates(tmp_path, entries)) == 1

    def test_constant_marker_value(self):
        assert rp._ACTIVITY_LOG_PREFIX == "[subagent:"


# ── recall as a RELATEDNESS oracle, not a duplicate oracle (deviation TP-188-A) ─

class TestRecallNearestNote:
    def test_related_candidate_surfaces_nearest_note(self, tmp_path):
        _make_corpus(tmp_path, {
            "hook-exit-codes.md": (
                "# Hook exit codes\n\n**Status:** active\n\n"
                "Hook exit codes follow the channel-XOR protocol: exit 0 with JSON "
                "on stdout OR exit 2 with plain stderr, never both.\n"
            ),
            "atomic-write.md": (
                "# Atomic write\n\n**Status:** active\n\n"
                "tempfile mkstemp then os.replace gives an atomic rename.\n"
            ),
        })
        entries = [_entry("pattern_discovered",
                   "hook exit codes channel xor: stdout json or stderr but never both")]
        out = rp.memory_candidates(tmp_path, entries)
        assert len(out) == 1
        assert out[0]["nearest_note"] == "memory/hook-exit-codes.md"
        assert out[0]["nearest_score"] > 0

    def test_unrelated_candidate_is_suppressed_to_no_nearest(self, tmp_path):
        # A genuinely-unrelated candidate finds nothing topical -> nearest None.
        # (Shows the floor still suppresses NON-related text; it just can't
        # distinguish a novel insight from history among RELATED text.)
        _make_corpus(tmp_path, {
            "hook-exit-codes.md": "# Hook exit codes\n\n**Status:** active\n\n"
                                  "channel xor protocol stdout stderr exit codes\n",
        })
        entries = [_entry("pattern_discovered",
                   "marsupial gestation differs sharply from placental mammal gestation")]
        out = rp.memory_candidates(tmp_path, entries)
        assert len(out) == 1
        assert out[0]["nearest_note"] is None
        assert out[0]["nearest_score"] == 0.0


# ── Earn-the-red: replay against the LIVE corpus (§6) ─────────────────────────

class TestEarnTheRedLiveReplay:
    def test_render_parse_surfaces_subagent_log_suppressed(self):
        # (a) the durable pattern surfaces; the [subagent:] activity log — the
        # measured-dominant noise and the ONE mechanical drop — is suppressed.
        entries = [_RENDER_PARSE, _SUBAGENT_LOG]
        out = rp.memory_candidates(REPO_ROOT, entries)
        texts = [c["text"] for c in out]
        assert any("render" in t for t in texts), out
        assert all("[subagent:" not in t for t in texts), out

    def test_render_parse_nearest_note_is_advisory_context(self):
        # recall surfaces a related memory/ note (measured: fan-out-finding-schema.md
        # @ 12.2). Assert the robust structural fact, not the brittle exact score.
        out = rp.memory_candidates(REPO_ROOT, [_RENDER_PARSE])
        assert len(out) == 1
        assert out[0]["nearest_note"] is not None
        assert out[0]["nearest_note"].startswith("memory/")


# ── propose-not-write + import safety ─────────────────────────────────────────

class TestSideEffects:
    def test_detector_writes_nothing(self, tmp_path):
        _make_corpus(tmp_path, {"n.md": "# N\n\n**Status:** active\n\nhook exit codes\n"})
        before = set(p for p in tmp_path.rglob("*"))
        rp.memory_candidates(tmp_path, [_entry("decision", "hook exit codes are channel xor here")])
        after = set(p for p in tmp_path.rglob("*"))
        assert before == after
        assert not (tmp_path / ".espalier" / "memory_candidate_log.jsonl").exists()

    def test_recall_import_is_available(self):
        # _load_recall imports the _recall sibling side-effect-free.
        assert rp._load_recall() is not None


# ── Chain aggregation: robust to mid-session blueprint rotation ───────────────

class TestChainAggregation:
    """A SessionStart (compact/resume) rotates the blueprint, scattering one work
    session's reasoning across several per-session files. _load_session_entries
    must walk the parent_session_id lineage (gap-bounded on stable creation
    timestamps), not just read the newest file — else a /reflect after any
    rotation surfaces nothing (the live failure that prompted this)."""

    @staticmethod
    def _bp(session_id, parent_id, entries, dt):
        return json.dumps({
            "session_id": session_id, "parent_session_id": parent_id,
            "timestamp": dt.isoformat(), "reasoning_entries": entries,
        })

    def _base(self):
        from datetime import datetime, timezone
        return datetime(2026, 6, 15, 6, 0, 0, tzinfo=timezone.utc)

    def test_walks_lineage_within_gap_excludes_prior_session(self, tmp_path, monkeypatch):
        from datetime import timedelta
        base = self._base()
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        # This work session lineage: s1 (oldest) -> s2 -> s3 (current).
        bp_dir.joinpath("s1.json").write_text(self._bp("s1", "s0",
            [{"kind": "pattern_discovered", "description": "render parse dedup write and key same render path"}],
            base), encoding="utf-8")
        bp_dir.joinpath("s2.json").write_text(self._bp("s2", "s1",
            [{"kind": "decision", "description": "durable insight B about the recall ranker design"}],
            base + timedelta(minutes=12)), encoding="utf-8")
        # Prior session: >60 min before s1 (the gap boundary).
        bp_dir.joinpath("s0.json").write_text(self._bp("s0", "",
            [{"kind": "decision", "description": "prior session reasoning that must be excluded entirely"}],
            base - timedelta(minutes=90)), encoding="utf-8")
        # The current blueprint (latest.json) is the empty post-rotation slice.
        bp_dir.joinpath("latest.json").write_text(self._bp("s3", "s2", [],
            base + timedelta(minutes=20)), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        descs = [e["description"] for e in rp._load_session_entries(tmp_path)]
        # Earn-the-red: render->parse lives in an OLDER lineage file; the current
        # latest.json is empty, so reading only it returns [] — the walk surfaces it.
        assert any("render parse dedup" in d for d in descs), descs
        assert any("durable insight B" in d for d in descs), descs
        # The >60-min-older prior session is gap-excluded.
        assert all("prior session" not in d for d in descs), descs
        # Chronological: s1 (oldest this-session) precedes s2.
        assert (descs.index("render parse dedup write and key same render path")
                < descs.index("durable insight B about the recall ranker design"))

    def test_gap_to_parent_stops_the_walk(self, tmp_path, monkeypatch):
        from datetime import timedelta
        base = self._base()
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        bp_dir.joinpath("old.json").write_text(self._bp("old", "",
            [{"kind": "decision", "description": "ancient decision far beyond the session gap"}],
            base - timedelta(minutes=120)), encoding="utf-8")
        bp_dir.joinpath("latest.json").write_text(self._bp("now", "old",
            [{"kind": "decision", "description": "current session durable decision worth keeping"}],
            base), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        descs = [e["description"] for e in rp._load_session_entries(tmp_path)]
        assert descs == ["current session durable decision worth keeping"]

    def test_latest_only_no_parent_returns_its_entries(self, tmp_path, monkeypatch):
        base = self._base()
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        bp_dir.joinpath("latest.json").write_text(self._bp("x", "",
            [{"kind": "decision", "description": "the only entry in a single-blueprint session"}],
            base), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        descs = [e["description"] for e in rp._load_session_entries(tmp_path)]
        assert descs == ["the only entry in a single-blueprint session"]

    def test_missing_parent_file_stops_gracefully(self, tmp_path, monkeypatch):
        # Parent pruned: the walk stops at the broken link, no crash.
        base = self._base()
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        bp_dir.joinpath("latest.json").write_text(self._bp("now", "pruned-gone",
            [{"kind": "decision", "description": "current decision with a pruned parent link"}],
            base), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        descs = [e["description"] for e in rp._load_session_entries(tmp_path)]
        assert descs == ["current decision with a pruned parent link"]

    def test_no_blueprints_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert rp._load_session_entries(tmp_path) == []


# ── CLI: --candidates emits a suppress-on-empty report ────────────────────────

class TestCandidatesCli:
    def test_candidates_flag_prints_none_without_session(self, tmp_path):
        # No blueprint at this root -> no entries -> "MEMORY CANDIDATES: none".
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0
        assert "MEMORY CANDIDATES: none" in result.stdout
        assert "UNREADABLE LOG LINES" not in result.stdout

    def test_unreadable_log_lines_are_reported_on_both_paths(self, tmp_path):
        """DEF-764: a torn row is a decision the pass will re-propose as
        undecided; the operator is told before the candidates, and the JSON
        carries the count whether or not it is zero."""
        log = tmp_path / ".espalier" / "memory_candidate_log.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(
            json.dumps({"key": "abcdef012345", "disposition": "skipped"}) + "\n"
            + '{"key": "0123456789ab", "disposition": "skipped", "candidate": "torn\n'
            + 'across two lines"}\n',
            encoding="utf-8",
        )
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        text = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert text.returncode == 0, text.stderr
        assert "UNREADABLE LOG LINES: 2 not JSON" in text.stdout, text.stdout
        assert text.stdout.index("UNREADABLE") < text.stdout.index("MEMORY CANDIDATES"), text.stdout
        as_json = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates", "--json"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        payload = json.loads(as_json.stdout)
        assert payload["unreadable"] == 2 and payload["ignored"] == 0, payload

    def test_corpus_root_follows_env_not_cwd_from_subdir(self, tmp_path):
        # Adversarial review #2: from a subdirectory, the corpus root must resolve
        # via CLAUDE_PROJECT_DIR (like the blueprint), NOT cwd — else every nearest
        # note falsely renders "(none)". This is the empirical subdir repro.
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "pooling.md").write_text(
            "# Connection pooling\n\n**Status:** active\n\n"
            "Connection pool exhaustion under sustained load needs a bounded pool size.\n",
            encoding="utf-8",
        )
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "latest.json").write_text(json.dumps({
            "session_id": "s",
            "reasoning_entries": [{
                "kind": "decision",
                "description": "connection pool exhaustion under sustained load needs a bounded pool size",
            }],
        }), encoding="utf-8")
        subdir = tmp_path / "deep" / "nested"
        subdir.mkdir(parents=True)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates"],
            cwd=str(subdir), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        # The candidate surfaces AND its nearest note is found (not a false "(none)").
        assert "memory/pooling.md" in result.stdout, result.stdout
        assert "(none" not in result.stdout, result.stdout


class TestShipTier:
    """TP-257 W3: memory_candidates proposes a SHIP-TIER + target per candidate so
    an adopter-relevant insight routes to a shipping docs catalog instead of the
    non-shipping memory/ folder. Advisory heuristic; the operator/LLM layer confirms."""

    def test_adopter_shaped_text_proposes_ship_adopter(self):
        tier, target = rp._propose_ship_tier(
            "a hook-denied Bash call runs none of its commands; verify staging after every commit"
        )
        assert tier == "SHIP_ADOPTER"
        assert "docs/FAILURE_MODES.md" in target

    def test_ship_target_is_only_the_catalog_that_actually_ships(self):
        """SHARP_EDGES.md / CONVENTIONS.md are NOT adopter-reachable targets.

        Both are init-seeded from ``espalier/assets/seed/`` as near-empty STUBS for
        the host repo's own patterns -- "It is yours, refreshed on re-init only
        while you have not edited it".
        This repo's copies are contributor content an adopter never receives, so
        routing a SHIP_ADOPTER insight there reaches nobody. Only FAILURE_MODES.md
        is byte-mirrored into ``espalier/assets/docs/`` and deployed with content.

        The prior assertion was ``FAILURE_MODES in target or SHARP_EDGES in target``
        -- an OR that passes whichever one is named, so it could not tell the
        shipping catalog from the stub. That is the distinction this pins.
        """
        _tier, target = rp._propose_ship_tier(
            "a bounded connection pool prevents exhaustion under sustained load"
        )
        assert "SHARP_EDGES" not in target, (
            "SHIP_ADOPTER must not route to docs/SHARP_EDGES.md -- adopters receive "
            f"a blank stub there, not this catalog: {target!r}"
        )
        assert "CONVENTIONS" not in target, (
            "SHIP_ADOPTER must not route to docs/CONVENTIONS.md -- same stub shape: "
            f"{target!r}"
        )

    def test_selfhost_token_proposes_selfhost_dev(self):
        tier, target = rp._propose_ship_tier(
            "write_guard's first 200 bytes are the self-host signal; keep them byte-identical"
        )
        assert tier == "SELFHOST_DEV"
        assert target == "memory/"

    def test_operator_identity_proposes_operator_private(self):
        tier, _ = rp._propose_ship_tier("credit the co-author trailer as Claude on every commit")
        assert tier == "OPERATOR_PRIVATE"

    def test_operator_wins_over_selfhost_when_both_present(self):
        # ordered most-restrictive first: a private note that also names a
        # self-host token (espalier) stays private.
        tier, _ = rp._propose_ship_tier("my workflow: commit espalier changes and push")
        assert tier == "OPERATOR_PRIVATE"

    def test_candidate_dict_carries_ship_tier_and_target(self, tmp_path):
        out = rp.memory_candidates(
            tmp_path,
            [_entry("decision", "a bounded connection pool prevents exhaustion under sustained load")],
        )
        assert len(out) == 1
        assert out[0]["ship_tier"] == "SHIP_ADOPTER"
        assert "ship_target" in out[0]


class TestSkipRate:
    """The candidate pass now PRINTS the skip-rate, mechanizing the formerly
    hand-eyeballed anti-theater metric. ``memory_candidate_skip_rate`` tallies
    the disposition log; ``_print_candidates`` surfaces it. Advisory only — the
    tightening call stays operator judgment (the reader crashes nothing: a
    missing/torn/malformed log degrades to None)."""

    _LOG_REL = ".espalier/memory_candidate_log.jsonl"

    def _write_log(self, root: Path, dispositions) -> None:
        log = root / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "".join(json.dumps({"disposition": d}) + "\n" for d in dispositions),
            encoding="utf-8",
        )

    def test_absent_log_is_none(self, tmp_path):
        assert rp.memory_candidate_skip_rate(tmp_path) is None

    def test_empty_log_is_none(self, tmp_path):
        self._write_log(tmp_path, [])
        assert rp.memory_candidate_skip_rate(tmp_path) is None

    def test_all_time_tally_and_rate(self, tmp_path):
        self._write_log(tmp_path, ["promoted", "skipped", "skipped", "updated"])
        out = rp.memory_candidate_skip_rate(tmp_path)
        assert out["all_time"] == {"total": 4, "skipped": 2, "skip_rate": 0.5}

    def test_window_reflects_last_n(self, tmp_path):
        window = rp._SKIP_RATE_WINDOW
        # Oldest `window` are non-skip; newest `window` are all skips.
        self._write_log(tmp_path, ["promoted"] * window + ["skipped"] * window)
        out = rp.memory_candidate_skip_rate(tmp_path)
        assert out["window_size"] == window
        assert out["recent"] == {"total": window, "skipped": window, "skip_rate": 1.0}
        assert out["all_time"]["total"] == 2 * window

    def test_torn_and_nondict_lines_are_skipped(self, tmp_path):
        log = tmp_path / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            json.dumps({"disposition": "promoted"}) + "\n"
            + "{not valid json\n"                            # torn/partial append
            + json.dumps(["a", "list"]) + "\n"               # non-dict row
            + json.dumps({"no_disposition": 1}) + "\n"       # dict missing the key
            + json.dumps({"disposition": 7}) + "\n"          # non-str disposition
            + "\n"                                            # blank line
            + json.dumps({"disposition": "skipped"}) + "\n",
            encoding="utf-8",
        )
        out = rp.memory_candidate_skip_rate(tmp_path)
        assert out["all_time"] == {"total": 2, "skipped": 1, "skip_rate": 0.5}

    def test_the_report_counts_the_lines_the_read_dropped(self, tmp_path):
        """DEF-764: the skip stays (pinned above); the COUNT is new. One line
        is not JSON; three parse but carry no string disposition."""
        log = tmp_path / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            json.dumps({"disposition": "promoted"}) + "\n"
            + "{not valid json\n"
            + json.dumps(["a", "list"]) + "\n"
            + json.dumps({"no_disposition": 1}) + "\n"
            + json.dumps({"disposition": 7}) + "\n"
            + "\n"
            + json.dumps({"disposition": "skipped"}) + "\n",
            encoding="utf-8",
        )
        rows, unreadable, ignored = rp._read_disposition_log_report(tmp_path)
        assert len(rows) == 2 and unreadable == 1 and ignored == 3
        assert rp._read_disposition_log(tmp_path) == rows
        assert rp._read_disposition_log_report(tmp_path / "absent") == ([], 0, 0)

    def test_noisy_flag_trips_at_threshold(self, tmp_path):
        # recent skip_rate >= _SKIP_RATE_NOISE_THRESHOLD -> noisy True.
        n = 10
        skipped = int(rp._SKIP_RATE_NOISE_THRESHOLD * n) + 1
        self._write_log(tmp_path, ["skipped"] * skipped + ["promoted"] * (n - skipped))
        assert rp.memory_candidate_skip_rate(tmp_path)["noisy"] is True

    def test_low_rate_is_not_noisy(self, tmp_path):
        self._write_log(tmp_path, ["promoted"] * 9 + ["skipped"])
        assert rp.memory_candidate_skip_rate(tmp_path)["noisy"] is False

    def test_window_is_by_time_not_by_file_order(self, tmp_path):
        """The log has no Python writer, so nothing promises oldest-first; the
        live log's last-20 by file order and by time already differed on
        2026-09-08. The window is the time-latest rows, whatever the file order."""
        window = rp._SKIP_RATE_WINDOW
        newest = [{"disposition": "promoted",
                   "session_ts": f"2026-09-08T12:{i:02d}:00+00:00"} for i in range(window)]
        oldest = [{"disposition": "skipped",
                   "session_ts": f"2026-09-01T12:{i:02d}:00+00:00"} for i in range(window)]
        log = tmp_path / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        # Newest FIRST in the file: a file-order window reads the old skips.
        log.write_text("".join(json.dumps(r) + "\n" for r in newest + oldest), encoding="utf-8")
        out = rp.memory_candidate_skip_rate(tmp_path)
        assert out["all_time"]["skip_rate"] == 0.5
        assert out["recent"] == {"total": window, "skipped": 0, "skip_rate": 0.0}

    def test_every_live_timestamp_shape_parses_to_its_instant(self):
        """The six spellings the live log carried on 2026-09-08, plus the legacy
        `date` key on the rows that had no session_ts at all -- each to the
        exact instant, and each graded precise or coarse. Asserting only "it
        parsed" let a blueprint-id regex that drops the time stay green."""
        from datetime import datetime, timezone

        utc = timezone.utc
        cases = {
            "2026-08-03T12:40:00+00:00": (datetime(2026, 8, 3, 12, 40, tzinfo=utc), True),
            "2026-08-02T00:00:00Z": (datetime(2026, 8, 2, 0, 0, tzinfo=utc), True),
            "2026-07-18T00:40:08.423134+00:00":
                (datetime(2026, 7, 18, 0, 40, 8, 423134, tzinfo=utc), True),
            "20260731-035408-5945f5": (datetime(2026, 7, 31, 3, 54, 8, tzinfo=utc), True),
            "2026-06-15": (datetime(2026, 6, 15, tzinfo=utc), False),
            "2026-09-08T09:00:00": (datetime(2026, 9, 8, 9, 0, tzinfo=utc), False),
        }
        for raw, expected in cases.items():
            assert rp._disposition_clock({"session_ts": raw}) == expected, raw
        assert rp._disposition_clock({"date": "2026-07-27"}) == (datetime(2026, 7, 27, tzinfo=utc), False)
        assert rp._disposition_clock({"session_ts": "yesterday"}) == (None, False)
        assert rp._disposition_clock({"session_ts": 7}) == (None, False)
        assert rp._disposition_clock({}) == (None, False)

    def test_coarse_clocks_in_the_window_are_counted_and_hinted(self, tmp_path, capsys):
        """A bare date or a naive time PARSES but can be hours off; the count
        is the mechanical nudge the SKILL's prose cannot deliver."""
        rows = [{"disposition": "skipped", "session_ts": "2026-09-08T12:00:00+00:00"},
                {"disposition": "skipped", "session_ts": "2026-09-08"},
                {"disposition": "skipped", "session_ts": "2026-09-08T13:00:00"},
                {"disposition": "skipped"}]
        log = tmp_path / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        out = rp.memory_candidate_skip_rate(tmp_path)
        assert out["coarse_clock"] == 3
        rp._print_candidates([], as_json=False, skip_rate=out)
        text = capsys.readouterr().out
        assert "3 of the last-" in text and "coarse or missing clock" in text
        # A window with only precise clocks prints no such hint.
        out["coarse_clock"] = 0
        rp._print_candidates([], as_json=False, skip_rate=out)
        assert "coarse or missing clock" not in capsys.readouterr().out

    def test_a_date_only_decision_after_a_hold_still_retires_it(self, tmp_path):
        """Retirement stays in FILE order on purpose: a decision stamped with a
        bare date sorts to midnight, before a hold written that morning, so time
        order would re-propose the hold forever."""
        rows = [{"disposition": "held", "key": "abcdef123456", "candidate": "x",
                 "session_ts": "2026-09-08T07:16:00Z"},
                {"disposition": "skipped", "key": "abcdef123456", "session_ts": "2026-09-08"}]
        log = tmp_path / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        assert rp.held_candidates(tmp_path) == []

    def test_undated_rows_inherit_the_clock_of_the_row_above(self):
        """The live log's three clockless rows on 2026-09-08 were that day's
        newest decisions; file position is the only evidence of when an undated
        row was written, so it sorts with the dated row above it, and one before
        any dated row reads as the epoch."""
        rows = [{"disposition": "skipped", "n": 0},
                {"disposition": "skipped", "session_ts": "2026-09-02T00:00:00Z", "n": 1},
                {"disposition": "skipped", "n": 2},
                {"disposition": "skipped", "session_ts": "2026-09-01T00:00:00Z", "n": 3},
                {"disposition": "skipped", "n": 4}]
        assert [r["n"] for r in rp._sorted_by_time(rows)] == [0, 3, 4, 1, 2]

    def test_print_candidates_emits_skip_rate_line(self, capsys):
        skip_rate = {"all_time": {"total": 6, "skipped": 3, "skip_rate": 0.5},
                     "recent": {"total": 6, "skipped": 3, "skip_rate": 0.5},
                     "window_size": 20, "noisy": False}
        rp._print_candidates([], as_json=False, skip_rate=skip_rate)
        out = capsys.readouterr().out
        assert "SKIP-RATE:" in out
        assert "3/6" in out
        assert "hint:" not in out

    def test_print_candidates_noisy_prints_hint(self, capsys):
        skip_rate = {"all_time": {"total": 6, "skipped": 5, "skip_rate": 0.833},
                     "recent": {"total": 6, "skipped": 5, "skip_rate": 0.833},
                     "window_size": 20, "noisy": True}
        rp._print_candidates([], as_json=False, skip_rate=skip_rate)
        assert "hint:" in capsys.readouterr().out

    def test_print_candidates_json_carries_skip_rate(self, capsys):
        skip_rate = {"all_time": {"total": 1, "skipped": 0, "skip_rate": 0.0},
                     "recent": {"total": 1, "skipped": 0, "skip_rate": 0.0},
                     "window_size": 20, "noisy": False}
        rp._print_candidates([], as_json=True, skip_rate=skip_rate)
        payload = json.loads(capsys.readouterr().out)
        assert payload["skip_rate"] == skip_rate
        assert payload["memory_candidates"] == []

    def test_print_candidates_without_skip_rate_omits_line(self, capsys):
        rp._print_candidates([], as_json=False, skip_rate=None)
        assert "SKIP-RATE:" not in capsys.readouterr().out


# ── TP-347: the memory-candidate feedback loop (suppress re-proposal) ──────────

class TestFeedbackLoop:
    """A candidate the operator marked ``skipped`` in the disposition log is
    suppressed from future ``--candidates`` runs. Identity is a machine-computed
    stable key (a digest of the NORMALIZED RAW text) — printed beside each
    candidate and logged verbatim, never re-derived from the rendered display
    line (the render->key footgun). The loop is advisory + fail-open: an empty
    suppression set is a no-op; only the operator-invoked ``--candidates`` path
    applies it (the ``reflect_trigger`` ``--pass 1`` hook path never does)."""

    _LOG_REL = ".espalier/memory_candidate_log.jsonl"
    _HEX12 = re.compile(r"[0-9a-f]{12}")

    def _write_log(self, root: Path, rows) -> None:
        log = root / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def _seed_blueprint(self, root: Path, text: str) -> None:
        bp_dir = root / "cc" / "blueprints"
        bp_dir.mkdir(parents=True, exist_ok=True)
        (bp_dir / "latest.json").write_text(json.dumps({
            "session_id": "s",
            "reasoning_entries": [{"kind": "decision", "description": text}],
        }), encoding="utf-8")

    # --- 1-A: the stable dedup key --------------------------------------------

    def test_norm_is_the_within_session_dedup_definition(self):
        # _norm is the ONE definition of "same candidate" so the within-session
        # seen-set and the cross-session key cannot drift.
        assert rp._norm("Hook   Exit\ncodes X") == "hook exit codes x"

    def test_candidate_key_is_whitespace_and_case_invariant(self):
        # The render->key footgun killer: reflowed whitespace + case must not
        # change the identity.
        assert rp._candidate_key("Hook   Exit\ncodes X") == rp._candidate_key("hook exit codes x")

    def test_distinct_insights_get_distinct_keys(self):
        assert rp._candidate_key("hook exit codes are channel xor") != \
            rp._candidate_key("atomic write uses os.replace for the rename")

    def test_candidate_key_is_12_hex(self):
        assert self._HEX12.fullmatch(
            rp._candidate_key("a durable insight worth keeping around for later reuse"))

    def test_every_candidate_dict_carries_a_12hex_key(self, tmp_path):
        out = rp.memory_candidates(
            tmp_path,
            [_entry("decision", "a bounded connection pool prevents exhaustion under sustained load")],
        )
        assert len(out) == 1
        assert self._HEX12.fullmatch(out[0]["key"])

    # --- 1-B: suppression set + pure filter -----------------------------------

    def test_suppress_resolved_drops_matching_key(self):
        assert rp.suppress_resolved([{"key": "abc", "text": "x"}], {"abc"}) == []

    def test_suppress_resolved_empty_set_is_identity(self):
        cands = [{"key": "abc", "text": "x"}]
        assert rp.suppress_resolved(cands, set()) == cands

    def test_suppress_resolved_keeps_unmatched(self):
        cands = [{"key": "abc", "text": "x"}, {"key": "def", "text": "y"}]
        assert rp.suppress_resolved(cands, {"abc"}) == [{"key": "def", "text": "y"}]

    def test_resolved_candidate_keys_prefers_machine_key(self, tmp_path):
        self._write_log(tmp_path, [{"disposition": "skipped", "key": "abcdef012345"}])
        assert rp.resolved_candidate_keys(tmp_path) == {"abcdef012345"}

    def test_resolved_candidate_keys_legacy_row_derives_from_candidate(self, tmp_path):
        # A row written before the key field existed: re-derive from the
        # transcribed candidate text (best-effort back-compat).
        text = "a legacy skipped candidate logged before the machine key existed"
        self._write_log(tmp_path, [{"disposition": "skipped", "candidate": text}])
        assert rp.resolved_candidate_keys(tmp_path) == {rp._candidate_key(text)}

    def test_resolved_candidate_keys_covers_every_disposition(self, tmp_path):
        """`promoted` and `updated` mean "dealt with" exactly as `skipped` does.

        This previously asserted the opposite -- that only `skipped`
        suppressed. The consequence was that a PROMOTED insight was
        re-proposed on every later run, and the only two answers to a
        re-proposal are "skip it again", which inflates the skip-rate that
        then advises the durability bar is too low, or "promote a duplicate".
        The anti-theater metric degraded as a function of successful
        promotions. Measured on the live log: back-filling two promotions the
        operator had made but never logged moved the rate 75% -> 65%.
        """
        self._write_log(tmp_path, [
            {"disposition": "skipped", "key": "aaaaaaaaaaaa"},
            {"disposition": "promoted", "key": "bbbbbbbbbbbb"},
            {"disposition": "updated", "key": "cccccccccccc"},
        ])
        assert rp.resolved_candidate_keys(tmp_path) == {
            "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"
        }

    def test_resolved_candidate_keys_ignores_unknown_disposition(self, tmp_path):
        """The predicate is an ENUMERATION, not "any non-empty disposition".

        An unrecognized value is a typo or a future disposition whose
        semantics nobody has decided yet; suppressing on it would hide a
        candidate for a reason no one chose. Keeps the widened predicate from
        degenerating into "always suppress".
        """
        self._write_log(tmp_path, [
            {"disposition": "wontfix", "key": "dddddddddddd"},
            {"disposition": "", "key": "eeeeeeeeeeee"},
        ])
        assert rp.resolved_candidate_keys(tmp_path) == set()

    def test_resolved_candidate_keys_absent_log_is_empty(self, tmp_path):
        assert rp.resolved_candidate_keys(tmp_path) == set()

    def test_resolved_candidate_keys_ignores_torn_and_keyless_rows(self, tmp_path):
        log = tmp_path / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "{not valid json\n"                                          # torn append
            + json.dumps({"disposition": "skipped"}) + "\n"             # skipped, no key/candidate
            + json.dumps({"disposition": "skipped", "key": "keepme01234x"}) + "\n",
            encoding="utf-8",
        )
        assert rp.resolved_candidate_keys(tmp_path) == {"keepme01234x"}

    # --- 1-C: the loop end-to-end (headline earn-red) -------------------------

    def test_skipped_candidate_is_suppressed_end_to_end(self, tmp_path):
        # RED before main() is wired: the candidate is re-listed (MEMORY
        # CANDIDATES: 1). GREEN after: suppressed to none + a SUPPRESSED line.
        text = "a bounded connection pool prevents exhaustion under sustained load"
        self._seed_blueprint(tmp_path, text)
        self._write_log(tmp_path, [{"disposition": "skipped", "key": rp._candidate_key(text)}])
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "MEMORY CANDIDATES: none" in result.stdout, result.stdout
        assert "SUPPRESSED: 1" in result.stdout, result.stdout

    def test_unskipped_candidate_surfaces_with_key_and_no_suppressed_line(self, tmp_path):
        # Control: no skipped-log row -> the candidate surfaces, its key printed,
        # and no SUPPRESSED line (the count is exactly len(raw) - len(shown) = 0).
        text = "a bounded connection pool prevents exhaustion under sustained load"
        self._seed_blueprint(tmp_path, text)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "MEMORY CANDIDATES: 1" in result.stdout, result.stdout
        assert "key: " in result.stdout, result.stdout
        assert "SUPPRESSED:" not in result.stdout, result.stdout

    def test_json_shape_carries_key_and_suppressed(self, tmp_path):
        text = "a bounded connection pool prevents exhaustion under sustained load"
        self._seed_blueprint(tmp_path, text)
        self._write_log(tmp_path, [{"disposition": "skipped", "key": rp._candidate_key(text)}])
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates", "--json"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["suppressed"] == 1
        assert payload["memory_candidates"] == []

    def test_reflect_trigger_pass1_path_is_blind_to_the_suppression_set(self, tmp_path):
        # Real isolation pin. The reflect_trigger hook path (--pass 1 --json,
        # called every 10th write) must NOT run the candidate/suppression
        # machinery -- even when a skipped-log row matching a seeded candidate
        # exists. The candidate-pass-only json keys (`memory_candidates`,
        # `suppressed`) must be absent from the surface-report payload.
        #
        # (The prior assertion -- "SUPPRESSED:" absent from stdout -- was
        # vacuous: pass-1 emits no candidates, so suppressed_count is 0 and that
        # line never prints regardless of wiring; and in --json the key is the
        # lowercase "suppressed", so the uppercase check was doubly unsatisfiable.
        # A byte-identical stdout compare would flake on the report's timestamp.)
        text = "a durable decision the reflect-trigger hook path must never suppress"
        self._seed_blueprint(tmp_path, text)
        self._write_log(tmp_path, [{"disposition": "skipped", "key": rp._candidate_key(text)}])
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--pass", "1", "--json"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "suppressed" not in payload, payload
        assert "memory_candidates" not in payload, payload

    def test_skill_documents_the_live_disposition_log_path_and_key_field(self):
        # SKILL<->code parity: the reflect SKILL hard-codes the disposition-log
        # path it tells the operator to append to, and the row shape now includes
        # the `key` field. If _CANDIDATE_LOG_REL ever moves, the reader would read
        # the new path while the SKILL still names the old one -> suppression
        # silently never engages, and the code-side tests (which use the constant,
        # not the doc) stay green. Pin the doc to the code so drift reds here.
        skill_text = _REFLECT_SKILL_SOT.read_text(encoding="utf-8")
        assert rp._CANDIDATE_LOG_REL in skill_text
        assert "candidate, key," in skill_text  # the new key field, in the documented row shape


# ── held: the fourth disposition, and the only one the pass re-proposes ───────


class TestHeldDisposition:
    """DEF-685. A candidate the operator has read but not decided had no durable
    home: ``promoted``/``updated``/``skipped`` are decisions and suppress, and
    anything else was unread by the enumeration, while the lineage walk forgets
    a blueprint past the session gap. So a ``HOLD --`` row (written 2026-09-04)
    suppressed nothing, sat in the skip-rate, and was never re-proposed; and the
    next session's memory row cited five keys as "logged" that were in no log at
    all. ``held`` is a log row the pass re-proposes FROM THE LOG until a resolved
    row for the same key lands, and it leaves the skip-rate.
    """

    _LOG_REL = ".espalier/memory_candidate_log.jsonl"

    def _write_rows(self, root: Path, rows) -> None:
        log = root / self._LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    @staticmethod
    def _held(key="deadbeef0000",
              text="A held candidate that nobody has dispositioned yet, long enough to pass the durability floor",
              **extra):
        row = {"session_ts": "2026-09-04T00:00:00+00:00", "candidate": text, "key": key,
               "nearest_note": None, "disposition": "held", "kind": "decision"}
        row.update(extra)
        return row

    def test_a_held_row_is_reproposed_with_its_logged_key(self, tmp_path):
        self._write_rows(tmp_path, [self._held()])
        out = rp.held_candidates(tmp_path)
        assert [c["key"] for c in out] == ["deadbeef0000"]
        assert out[0]["held_since"] == "2026-09-04T00:00:00+00:00"
        assert out[0]["text"].startswith("A held candidate")
        assert out[0]["kind"] == "decision"

    def test_the_logged_key_is_authoritative_over_the_text(self, tmp_path):
        # The operator's `candidate` cell is a paraphrase in most live rows;
        # re-keying it would break the link a later resolved row uses to retire
        # the hold.
        self._write_rows(tmp_path, [self._held(text="a paraphrase, long enough to be a real candidate row")])
        out = rp.held_candidates(tmp_path)
        assert out[0]["key"] == "deadbeef0000"
        assert out[0]["key"] != rp._candidate_key(out[0]["text"])

    @pytest.mark.parametrize("final", sorted(rp.RESOLVED_DISPOSITIONS))
    def test_a_later_resolution_retires_the_hold(self, tmp_path, final):
        self._write_rows(tmp_path, [self._held(), {"disposition": final, "key": "deadbeef0000"}])
        assert rp.held_candidates(tmp_path) == []

    def test_a_hold_written_after_a_decision_is_live(self, tmp_path):
        # Retirement is ORDER-SENSITIVE: the operator skipped it, then changed
        # their mind and parked it. A whole-file resolved set would eat the hold.
        self._write_rows(tmp_path, [{"disposition": "skipped", "key": "deadbeef0000"}, self._held()])
        assert [c["key"] for c in rp.held_candidates(tmp_path)] == ["deadbeef0000"]

    def test_a_keyless_decision_retires_a_hold_only_through_its_text(self, tmp_path):
        # The legacy fallback: a resolution row without `key` re-keys from its
        # text, so it retires the hold only when the text is verbatim.
        text = "A held candidate that nobody has dispositioned yet, long enough to pass the durability floor"
        self._write_rows(tmp_path, [self._held(key=rp._candidate_key(text), text=text),
                                    {"disposition": "promoted", "candidate": text}])
        assert rp.held_candidates(tmp_path) == []
        self._write_rows(tmp_path, [self._held(key=rp._candidate_key(text), text=text),
                                    {"disposition": "promoted", "candidate": "a paraphrase of it"}])
        assert len(rp.held_candidates(tmp_path)) == 1

    def test_lineage_candidates_carry_the_held_fields_too(self, tmp_path):
        out = rp.memory_candidates(tmp_path, [_RENDER_PARSE])
        assert out and out[0]["held"] is False and out[0]["held_since"] is None

    def test_print_summarises_the_pile_and_gives_the_retirement_row(self, capsys):
        def held(i):
            return {"text": f"held {i}", "kind": "decision", "key": f"{i:012x}",
                    "nearest_note": None, "nearest_score": 0.0, "nearest_notes": [],
                    "ship_tier": None, "ship_target": None,
                    "held": True, "held_since": f"2026-0{i}-01T00:00:00+00:00"}
        rp._print_candidates([held(1)], as_json=False)
        out = capsys.readouterr().out
        assert "HELD: 1 awaiting a decision (first parked 2026-01-01T00:00:00+00:00)" in out
        assert 'to retire, append: {"key": "000000000001", "disposition": "skipped"}' in out
        assert "hint: more than" not in out
        rp._print_candidates([held(i) for i in range(1, rp._HELD_PILE_HINT + 2)], as_json=False)
        assert "hint: more than" in capsys.readouterr().out

    def test_an_unrecognised_disposition_is_not_held(self, tmp_path):
        # The legacy shape. Not suppressed, not proposed: the enumeration reads
        # neither, which is why those rows are migrated as data, not accommodated.
        self._write_rows(tmp_path, [self._held(disposition="HOLD -- proposed at handoff")])
        assert rp.held_candidates(tmp_path) == []

    def test_a_keyless_held_row_derives_its_key_from_its_text(self, tmp_path):
        row = self._held()
        del row["key"]
        self._write_rows(tmp_path, [row])
        out = rp.held_candidates(tmp_path)
        assert [c["key"] for c in out] == [rp._candidate_key(row["candidate"])]

    def test_a_held_row_without_a_session_ts_is_still_labelled_held(self, tmp_path, capsys):
        row = self._held()
        del row["session_ts"]
        self._write_rows(tmp_path, [row])
        out = rp.held_candidates(tmp_path)
        assert out[0]["held"] is True
        rp._print_candidates(out, as_json=False)
        text = capsys.readouterr().out
        assert "[held since an unrecorded session]" in text
        assert "log this verbatim" not in text

    def test_a_held_row_with_neither_key_nor_text_proposes_nothing(self, tmp_path):
        self._write_rows(tmp_path, [{"disposition": "held", "session_ts": "t"}])
        assert rp.held_candidates(tmp_path) == []

    def test_newest_held_row_per_key_wins(self, tmp_path):
        self._write_rows(tmp_path, [
            self._held(text="older text long enough to pass the floor easily"),
            self._held(text="newer text long enough to pass the floor easily",
                       session_ts="2026-09-05T00:00:00+00:00"),
        ])
        out = rp.held_candidates(tmp_path)
        assert len(out) == 1
        assert out[0]["text"].startswith("newer")
        assert out[0]["held_since"].startswith("2026-09-05")

    def test_held_and_unrecognised_rows_leave_the_skip_rate_denominator(self, tmp_path):
        # Measured 2026-09-05 on the live log: four `HOLD --` rows sat in the
        # denominator of the metric the SKILL tells the operator to watch.
        self._write_rows(tmp_path, [{"disposition": d} for d in
                                    ("skipped", "promoted", "held",
                                     "HOLD -- proposed at handoff", "updated")])
        out = rp.memory_candidate_skip_rate(tmp_path)
        assert out["all_time"] == {"total": 3, "skipped": 1, "skip_rate": 0.333}

    def test_a_log_of_only_held_rows_has_no_skip_rate(self, tmp_path):
        self._write_rows(tmp_path, [self._held()])
        assert rp.memory_candidate_skip_rate(tmp_path) is None

    def test_print_labels_a_held_candidate_and_names_the_log(self, capsys):
        cand = {"text": "held text", "kind": "decision", "key": "deadbeef0000",
                "nearest_note": None, "nearest_score": 0.0, "nearest_notes": [],
                "ship_tier": "SELFHOST_DEV", "ship_target": "memory/",
                "held": True, "held_since": "2026-09-04T00:00:00+00:00"}
        rp._print_candidates([cand], as_json=False)
        out = capsys.readouterr().out
        assert "[held since 2026-09-04T00:00:00+00:00]" in out
        assert "deadbeef0000" in out
        assert rp._CANDIDATE_LOG_REL in out

    def test_the_candidate_cli_proposes_a_held_row_from_a_bare_tree(self, tmp_path):
        # The DEF-685 probe, as a test: no blueprint entries at all, one held
        # row, and the pass must still propose it -- from the log.
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        (tmp_path / "cc" / "blueprints" / "latest.json").write_text(
            json.dumps({"session_id": "probe", "reasoning_entries": []}), encoding="utf-8")
        self._write_rows(tmp_path, [self._held()])
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates", "--json"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert [c["key"] for c in payload["memory_candidates"]] == ["deadbeef0000"]
        assert payload["memory_candidates"][0]["held_since"] == "2026-09-04T00:00:00+00:00"
        assert payload["suppressed"] == 0
        assert payload["skip_rate"] is None  # a held row is not a decision

    def test_a_held_key_the_lineage_also_reaches_is_shown_once_as_lineage(self, tmp_path):
        text = ("render->parse dedup: the write path and the key path must render "
                "through one function, or the disposition log re-opens the footgun")
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        (tmp_path / "cc" / "blueprints" / "latest.json").write_text(
            json.dumps({"session_id": "s", "reasoning_entries": [_entry("pattern_discovered", text)]}),
            encoding="utf-8")
        self._write_rows(tmp_path, [self._held(key=rp._candidate_key(text), text="a paraphrase of it, long enough")])
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(_HOOK_SIDE), "--candidates", "--json"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        cands = json.loads(result.stdout)["memory_candidates"]
        assert [c["key"] for c in cands] == [rp._candidate_key(text)]
        assert cands[0]["held"] is False  # the lineage copy won the collision
        assert cands[0]["held_since"] is None

    def test_the_skill_names_held_and_the_decisions_only_rate(self):
        # SKILL<->code parity for the fourth disposition: the enumeration the
        # operator is told to write must match the one the pass reads, and the
        # metric's denominator must be described as it is computed.
        skill_text = _REFLECT_SKILL_SOT.read_text(encoding="utf-8")
        assert f"`{rp.HELD_DISPOSITION}`" in skill_text
        assert "is one of `promoted`, `updated`, `skipped`, `held`" in skill_text
        assert "counts decisions only" in skill_text
        # Every enumeration in the file, not the file as a whole: the report
        # template, the act-on-each-candidate list, and the log schema.
        assert "skip / hold)" in skill_text
        assert "- **hold** — read, but not ready to decide" in skill_text
        assert "a mistyped *hold*" in skill_text
        for d in sorted(rp.RESOLVED_DISPOSITIONS):
            assert f"`{d}`" in skill_text

    def test_resolved_dispositions_are_exactly_the_three_decisions(self):
        # Literal sibling of the derived parametrize above: the parametrize
        # covers a member ADDED later without enrolment (the safe direction);
        # this line is what reds when a member is REMOVED, so the battery
        # cannot shrink silently. `held` is deliberately not a member.
        assert rp.RESOLVED_DISPOSITIONS == frozenset({"skipped", "promoted", "updated"})
        assert rp.HELD_DISPOSITION not in rp.RESOLVED_DISPOSITIONS


class TestAgentReportsAreNotMemoryCandidates:
    """DEF-586: `subagent_stop` now records the agent's final-message lead with
    the transcript as evidence. The drop here keys on the prefix, not on the
    old fixed sentence, so a report-bearing entry is still not a candidate: an
    agent's report is a claim (STANDING_PRINCIPLES 3), never a durable note by
    itself; the operator distils it."""

    def test_a_report_bearing_agent_entry_is_still_dropped(self, tmp_path):
        entry = _entry("pattern_discovered",
                       "[subagent:code-reviewer] REQUEST CHANGES: the cap is off by one, "
                       "and the write-time advisory fires on every stop")
        entry["evidence"] = ["/t/subagents/agent-1.jsonl"]
        assert rp.memory_candidates(tmp_path, [entry]) == []
