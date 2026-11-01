"""The three shipped review workflows say which lanes did not run, and the fan-out
audit refuses an args value it cannot use.

Under the Workflow API a skipped agent, or one that dies on a terminal error,
resolves to ``null``, and ``parallel()`` and ``pipeline()`` turn a thrown lane into
``null``. The scaffolds once folded every such lane into an empty result, so a dead
lane read the same as a lane that found nothing, and the convergence template could
append a ``converged`` row to its ledger after a scope-breaker never ran. And the
fan-out audit turned any args value it could not read (a plain pack path, a JSON
non-object, a misspelled key) into its widest run, a whole-tree landing audit.

The oracle is behaviour, never a text match: each workflow body runs under node as
the async function Claude Code runs it, with ``agent``, ``parallel``, ``pipeline``,
``phase`` and ``log`` stubbed, and the test reads what it launched and returned. The
stub's ``parallel`` and ``pipeline`` follow the documented semantics (a thrown thunk
or stage resolves to ``null`` at its index; a pipeline item that throws skips its
remaining stages). Skipped when node is absent off CI; on CI an absent node fails.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".claude" / "workflows"
FANOUT = "_fanout_audit.js"
LAYERED = "_layered_review.js"
CONVERGENCE = "_convergence_review_template.js"

# slow-exempt: each case is one `node -e` child running a workflow body against
# in-process stubs (no agent, no network, no file write), well under a second.

# The driver: the workflow body as an async function over stubbed hooks. A scenario
# names the args (absent means undefined) and, per agent label (a regex, first match
# wins), whether the agent resolves null, undefined, a value, or throws; any other
# agent returns the empty result its schema asks for.
_DRIVER = r"""
const fs = require('fs')
const sc = JSON.parse(process.argv[2])
const src = fs.readFileSync(process.argv[1], 'utf8').replace(/^export /mg, '')
const calls = [], logs = [], phases = []
const rules = (sc.behaviours || []).map(b => ({ re: new RegExp(b.match), b }))
function emptyFor(o) {
  const props = ((o && o.schema) || {}).properties || {}
  if (o && o.label === 'persist:corpus') {
    return { total: 0, appended: 0, corpus_path: 'reports/stub.md', survivors_slim: [],
             by_refutation_outcome: {}, by_category: {} }
  }
  if (props.paths) return { paths: sc.discovered || [] }
  if (props.findings) return { findings: [] }
  if (props.gaps) return { gaps: [] }
  if (props.refutation_outcome) return { refutation_outcome: 'survived', refutation_reason: 'stub', externally_verified: false }
  if (props.round_appended) return { round_appended: true, convergence_read: 'stub read', converged_word_used: false, coverage_gaps: [] }
  return null
}
async function agent(prompt, o) {
  const label = (o && o.label) || ''
  calls.push({ label, phase: (o && o.phase) || null, prompt })
  const rule = rules.find(r => r.re.test(label))
  const b = rule ? rule.b : { do: 'empty' }
  if (b.do === 'null') return null
  if (b.do === 'undefined') return undefined
  if (b.do === 'throw') throw new Error('stub lane threw')
  if (b.do === 'value') return JSON.parse(JSON.stringify(b.value))
  return emptyFor(o)
}
async function parallel(thunks) {
  return Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
}
async function pipeline(items, ...stages) {
  return Promise.all(items.map(async (item, i) => {
    let prev = item
    try { for (const st of stages) prev = await st(prev, item, i) } catch (e) { return null }
    return prev
  }))
}
const phase = (t) => { phases.push(t) }
const log = (m) => { logs.push(String(m)) }
const budget = { total: null, spent: () => 0, remaining: () => Infinity }
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const fn = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', src)
const out = (o) => process.stdout.write(JSON.stringify({ ...o, calls, logs, phases }))
fn(agent, parallel, pipeline, phase, log, Object.prototype.hasOwnProperty.call(sc, 'args') ? sc.args : undefined,
   budget, async () => { throw new Error('nested workflow not stubbed') })
  .then(result => out({ result: result === undefined ? null : result }), e => out({ threw: String((e && e.stack) || e) }))
"""


def _node() -> str:
    node = shutil.which("node")
    if node:
        return node
    if os.environ.get("CI"):
        pytest.fail("node is not on PATH on CI; these workflow drives must run there")
    pytest.skip("node not installed; the workflow bodies are driven under node")


def _drive(name: str, **scenario) -> dict:
    """Run one workflow body under the stubs; return its result, calls and logs."""
    r = subprocess.run(
        [_node(), "-e", _DRIVER, str(WORKFLOWS / name), json.dumps(scenario)],
        capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    assert r.returncode == 0, (name, r.stderr[-800:])
    return json.loads(r.stdout)


def _ran(out: dict) -> dict:
    """The workflow's result, after asserting it returned rather than threw."""
    assert out.get("threw") is None, out.get("threw", "")[:600]
    return out.get("result") or {}


def _labels(out: dict, phase: str | None = None) -> list[str]:
    return [c["label"] for c in out["calls"] if phase is None or c["phase"] == phase]


def _persisted(out: dict) -> list[dict]:
    """The findings the workflow handed its persist agent (the JSON in its prompt)."""
    prompt = next(c["prompt"] for c in out["calls"] if c["label"] == "persist:corpus")
    body = prompt.split("<<<FINDINGS_JSON\n", 1)[1].split("\nFINDINGS_JSON", 1)[0]
    return json.loads(body)["findings"]


def _finding(n: int, category: str = "correctness") -> dict:
    return {
        "id": f"T:{n}", "title": f"title {n}", "rule_or_scanner": "stub",
        "violated_invariant": "inv", "category": category, "location": f"src/m{n}.py:1",
        "claim": f"distinct claim number {n}", "minimal_repro": "true",
        "verification": {"positive": "p", "negative": "n"}, "confidence": "high",
        "proposed_fix": "fix", "severity": "minor", "blocks_release": False,
    }


def _value(match: str, value) -> dict:
    return {"match": match, "do": "value", "value": value}


def _does(match: str, what: str) -> dict:
    return {"match": match, "do": what}


_PACKS = [f"task-packs/TP-{n}.md" for n in (1, 2, 3)]


class TestFanoutAuditLanes:
    FINDERS = [{"id": f"F{n}", "label": f"find:F{n}", "prompt": f"finder {n}"} for n in range(1, 6)]

    def test_a_finder_that_returned_nothing_or_threw_is_named_not_counted_as_clean(self):
        out = _drive(FANOUT, args={"finders": self.FINDERS}, behaviours=[
            _does("^find:F1$", "null"), _does("^find:F2$", "throw"),
            _value("^find:F3$", {"findings": [_finding(3)]}), _does("^find:F5$", "undefined"),
        ])
        result = _ran(out)
        assert result.get("lanesNotRun") == {"Find": ["find:F1", "find:F2", "find:F5"]}, result
        assert result.get("findersRun") == 2, result
        assert result.get("findersLaunched") == 5, result

    def test_a_refuter_that_returned_nothing_leaves_its_finding_unattempted(self):
        out = _drive(FANOUT, args={"finders": self.FINDERS[:1]}, behaviours=[
            _value("^find:F1$", {"findings": [_finding(1)]}), _does("^refute:", "null"),
        ])
        result = _ran(out)
        assert [f.get("refutation_outcome") for f in _persisted(out)] == ["unattempted"]
        assert result.get("refutersNotRun") == ["refute:F1#0"], result

    def test_a_persist_lane_that_returned_nothing_is_a_persist_error_not_a_crash(self):
        out = _drive(FANOUT, args={"finders": self.FINDERS[:1]}, behaviours=[
            _value("^find:F1$", {"findings": [_finding(1)]}), _does("^persist:corpus$", "null"),
        ])
        result = _ran(out)
        assert result.get("persistError"), result
        assert result.get("lanesNotRun") == {"Persist": ["persist:corpus"]}, result

    def test_no_finder_running_persists_no_round(self):
        out = _drive(FANOUT, args={"finders": self.FINDERS[:2]}, behaviours=[_does("^find:", "throw")])
        result = _ran(out)
        assert "persist:corpus" not in _labels(out), _labels(out)
        assert result.get("findersRun") == 0, result


class TestFanoutAuditArgsGate:
    @pytest.mark.parametrize("args", [
        "task-packs/TP-1.md",
        "{targets: [oops",
        ["task-packs/TP-1.md"],
        42,
        {"target": ["task-packs/TP-1.md"]},
        {"targets": []},
        {"finders": "find the bugs"},
        {"targets": ["task-packs/TP-1.md"], "maxFinders": 0},
    ], ids=["plain-path", "malformed-json", "array", "number", "misspelled-key",
            "empty-targets", "finders-not-a-list", "bad-cap"])
    def test_an_args_value_it_cannot_use_launches_no_agent_and_says_why(self, args):
        out = _drive(FANOUT, args=args, discovered=_PACKS)
        assert _labels(out) == [], _labels(out)
        assert (out.get("result") or {}).get("refused"), out.get("result") or out.get("threw", "")[:300]
        assert any("refused" in line for line in out["logs"]), out["logs"]

    @pytest.mark.parametrize("scenario", [{}, {"args": ""}, {"args": "  "}, {"args": {}},
                                          {"args": {"model": "sonnet"}}],
                             ids=["absent", "empty-string", "blank-string", "empty-object", "options-only"])
    def test_no_args_is_a_dry_run_that_counts_and_launches_no_finder(self, scenario):
        out = _drive(FANOUT, discovered=_PACKS, **scenario)
        result = _ran(out)
        assert _labels(out) == ["discover:packs"], _labels(out)
        assert result.get("dryRun") is True, result
        assert result.get("discovered") == 3, result
        assert any("3 pack(s)" in line for line in out["logs"]), out["logs"]

    def test_confirm_runs_the_landing_audit(self):
        out = _drive(FANOUT, args={"confirm": True}, discovered=_PACKS)
        _ran(out)
        assert _labels(out, "Find") == ["audit:TP-1", "audit:TP-2", "audit:TP-3"], _labels(out)
        assert "persist:corpus" in _labels(out)

    def test_the_finder_cap_refuses_a_wider_run(self):
        targets = [f"task-packs/TP-{n}.md" for n in range(1, 31)]
        out = _drive(FANOUT, args={"targets": targets})
        result = _ran(out)
        assert _labels(out) == [], _labels(out)
        assert "maxFinders" in (result.get("refused") or ""), result

    def test_the_cap_admits_a_run_at_its_bound_and_the_override_lifts_it(self):
        at_bound = _drive(FANOUT, args={"targets": [f"task-packs/TP-{n}.md" for n in range(1, 26)]})
        _ran(at_bound)
        assert len(_labels(at_bound, "Find")) == 25
        lifted = _drive(FANOUT, args={"targets": [f"task-packs/TP-{n}.md" for n in range(1, 31)], "maxFinders": 30})
        _ran(lifted)
        assert len(_labels(lifted, "Find")) == 30


class TestLayeredReviewLanes:
    FIND_LANES = ["find:correctness", "find:edge-cases", "find:failure-modes",
                  "find:layer-boundaries", "find:overclaim"]

    def test_finder_lanes_that_did_not_run_are_named(self):
        out = _drive(LAYERED, behaviours=[
            _does("^find:correctness$", "null"), _does("^find:edge-cases$", "throw"),
            _value("^find:failure-modes$", {"findings": [_finding(1, "failure-mode")]}),
        ])
        result = _ran(out)
        assert result.get("lanesNotRun") == {"Find": ["find:correctness", "find:edge-cases"]}, result
        assert result.get("findersRun") == 3, result
        assert result.get("findersLaunched") == 5, result

    def test_an_empty_round_still_reports_its_dead_lanes(self):
        out = _drive(LAYERED, behaviours=[_does("^find:", "null"), _does("^critic:completeness$", "null")])
        result = _ran(out)
        assert "persist:corpus" not in _labels(out), _labels(out)
        assert result.get("findersRun") == 0, result
        assert result.get("lanesNotRun") == {"Find": self.FIND_LANES, "Refute": ["critic:completeness"]}, result

    def test_a_critic_that_throws_is_named_not_a_crash(self):
        out = _drive(LAYERED, behaviours=[_does("^critic:completeness$", "throw")])
        result = _ran(out)
        assert result.get("lanesNotRun") == {"Refute": ["critic:completeness"]}, result

    def test_the_critic_is_told_which_finder_lanes_did_not_run(self):
        out = _drive(LAYERED, behaviours=[_does("^find:correctness$", "null")])
        _ran(out)
        critic = next(c["prompt"] for c in out["calls"] if c["label"] == "critic:completeness")
        assert "did NOT run" in critic and "find:correctness" in critic, critic[-400:]

    def test_an_object_arg_binds_its_scope(self):
        # The row's layered-review half: an object arg is read for its scope (refuted at HEAD).
        out = _drive(LAYERED, args={"scope": "src/only"})
        _ran(out)
        find = [c["prompt"] for c in out["calls"] if c["phase"] == "Find"]
        assert find and all("REVIEW SCOPE: src/only." in p for p in find)


class TestConvergenceTemplateLanes:
    ARGS = {"finders": [{"id": "D1", "category": "correctness", "title": "t", "body": "b"}],
            "ledgerPath": "scratch/convergence-ledger.md"}
    SEED = _value("^find:D1$", {"findings": [_finding(1)]})

    @pytest.mark.parametrize("lane,behaviours", [
        ("find:corpus-blind", [_does("^find:corpus-blind$", "null")]),
        ("penumbra:D1#0", [_does("^penumbra:", "null")]),
        ("actionable-critic", [_does("^actionable-critic$", "throw")]),
        ("find2:0", [_value("^actionable-critic$", {"gaps": [{"surface": "s", "why": "w", "oracle": "o"}]}),
                     _does("^find2:", "null")]),
        ("delta-attacker", [_does("^delta-attacker$", "null")]),
    ], ids=["corpus-blind", "penumbra", "actionable-critic", "second-wave", "delta-attacker"])
    def test_a_scope_breaker_that_did_not_run_holds_the_ledger_row(self, lane, behaviours):
        out = _drive(CONVERGENCE, args=self.ARGS, behaviours=[self.SEED, *behaviours])
        result = _ran(out)
        assert "convergence-critic" not in _labels(out), _labels(out)
        convergence = result.get("convergence") or {}
        assert convergence.get("rowAppended") is False, convergence
        assert "converged" not in (convergence.get("read") or "converged").lower(), convergence
        named = [x for lanes in (result.get("lanesNotRun") or {}).values() for x in lanes]
        assert lane in named, result.get("lanesNotRun")

    def test_a_complete_round_feeds_the_critic_the_corpus_blind_status(self):
        out = _drive(CONVERGENCE, args=self.ARGS, behaviours=[self.SEED])
        result = _ran(out)
        critic = next(c["prompt"] for c in out["calls"] if c["label"] == "convergence-critic")
        summary = json.loads(critic.split("THIS ROUND:\n", 1)[1].split("\n\nReturn", 1)[0])
        assert summary.get("corpus_blind") == {"ran": True, "candidates": 0, "survivors": 0}, summary
        assert result.get("lanesNotRun") == {}, result

    def test_the_smoke_lens_appends_no_row_unless_a_ledger_path_is_named(self):
        out = _drive(CONVERGENCE)
        result = _ran(out)
        assert "convergence-critic" not in _labels(out), _labels(out)
        assert (result.get("convergence") or {}).get("rowAppended") is False, result

    def test_the_smoke_lens_with_a_named_ledger_runs_the_critic(self):
        out = _drive(CONVERGENCE, args={"smoke": True, "ledgerPath": "scratch/convergence-ledger.md"})
        _ran(out)
        assert "convergence-critic" in _labels(out)

    def test_args_that_do_not_parse_fall_to_the_smoke_lens_without_a_ledger_row(self):
        out = _drive(CONVERGENCE, args="find the bugs in src/")
        result = _ran(out)
        assert "convergence-critic" not in _labels(out), _labels(out)
        assert result.get("argsUnparsed") is True, result

    def test_a_persist_lane_that_returned_nothing_holds_the_critic(self):
        out = _drive(CONVERGENCE, args=self.ARGS, behaviours=[self.SEED, _does("^persist:corpus$", "null")])
        result = _ran(out)
        assert result.get("persistError"), result
        assert "convergence-critic" not in _labels(out), _labels(out)

    def test_a_critic_that_returned_nothing_is_named_not_a_crash(self):
        out = _drive(CONVERGENCE, args=self.ARGS, behaviours=[self.SEED, _does("^convergence-critic$", "null")])
        result = _ran(out)
        assert result.get("lanesNotRun") == {"Convergence-critic": ["convergence-critic"]}, result
        assert (result.get("convergence") or {}).get("rowAppended") is False, result
