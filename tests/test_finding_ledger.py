"""Contract tests for the run-boundaried fan-out finding ledger (TP-203a A1).

The ledger is the structured, append-only, run-boundaried store the corpus
cannot be (the corpus is deduped on (location, claim) with no run boundary, so
it cannot express cross-run recurrence). These tests pin: the round-trip keeps
the fields the corpus drops; the writer is fail-open at element and I/O
granularity; the ledger path classifies local_only; and the offline writer
stays a stdlib leaf so the offline/in-loop split is physical.
"""
from __future__ import annotations

import ast
import re
import types
from pathlib import Path

from espalier import finding_ledger as fl
from espalier import surface_contract as sc
from espalier.fan_out_findings import FINDING_SCHEMA, aggregate_findings

REPO_ROOT = Path(__file__).resolve().parent.parent


def _code_lines(src: str) -> str:
    """Drop whole-line ``//`` JS comments so a substring check can't be
    satisfied by a commented-out call. Inline ``//`` (e.g. inside an
    ``https://`` literal) is left intact — only lines whose first non-space
    characters are ``//`` are removed."""
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("//")
    )


def _persists_anything(code: str) -> bool:
    """True when this workflow source calls EITHER persist hop.

    Keyed on the HARM, not on one of its two carriers. The population used to key
    on ``append_findings_to_corpus`` alone, which leaves a ledger-only scaffold —
    one that aggregates and calls ``append_summary`` with no corpus write, e.g. a
    smoke run or a re-persist repair script — outside both the standing-vs-dated
    classification and the private-tag contract, on precisely the hop a leaked
    private tag damages. Pass ``_code_lines`` output: a commented-out call is not
    a call.
    """
    return "append_findings_to_corpus(" in code or "append_summary(" in code


def _finding(i, *, category="bug", outcome="survived", finder=None, severity="major"):
    """A schema-valid fan-out finding (the 13 required fields)."""
    return {
        "id": f"TP-x:{i}",
        "title": f"title-{i}",
        "rule_or_scanner": finder if finder is not None else f"finder-{i % 2}",
        "violated_invariant": "some invariant",
        "category": category,
        "location": f"mod.py:{i}",
        "claim": f"claim {i}",
        "minimal_repro": "repro",
        "verification": {"positive": f"catches bad {i}", "negative": f"clears good {i}"},
        "confidence": "high",
        "proposed_fix": "fix it",
        "severity": severity,
        "blocks_release": False,
        "refutation_outcome": outcome,
    }


class TestAppendSummary:
    def test_round_trips_fields_the_corpus_drops(self, tmp_path):
        """survival_rate, by_category, and each finding's verification round-trip
        verbatim — the three the markdown corpus bullet throws away."""
        findings = [
            _finding(1, category="bug", outcome="survived"),
            _finding(2, category="bug", outcome="survived"),
            _finding(3, category="perf", outcome="refuted"),
        ]
        summ = aggregate_findings(findings, known_categories=["bug", "perf"])
        n = fl.append_summary(summ, run_id="run-A", ts="2026-01-01T00:00:00+00:00", root=tmp_path)
        assert n == 1
        (rec,) = fl.read_ledger(tmp_path)
        assert rec["run_id"] == "run-A"
        assert rec["ts"] == "2026-01-01T00:00:00+00:00"
        assert rec["summary"]["survival_rate"] == summ.survival_rate
        assert rec["summary"]["by_category"] == {"bug": 2, "perf": 1}
        assert rec["summary"]["total"] == 3
        # the corpus drops verification; the ledger must keep it verbatim
        verifications = [f["verification"] for f in rec["findings"]]
        assert {"positive": "catches bad 1", "negative": "clears good 1"} in verifications

    def test_finder_identities_from_rule_or_scanner(self, tmp_path):
        """finder_identities is the distinct producer (rule_or_scanner) axis."""
        findings = [
            _finding(1, finder="agent-a"),
            _finding(2, finder="agent-b"),
            _finding(3, finder="agent-a"),
        ]
        summ = aggregate_findings(findings, known_categories=["bug"])
        fl.append_summary(summ, run_id="r", ts="t", root=tmp_path)
        (rec,) = fl.read_ledger(tmp_path)
        assert sorted(rec["finder_identities"]) == ["agent-a", "agent-b"]

    def test_records_all_findings_not_only_survivors(self, tmp_path):
        """The ledger captures the WHOLE run (incl. refuted) for cross-run stats —
        unlike the corpus, which only persists survivors."""
        findings = [_finding(1, outcome="survived"), _finding(2, outcome="refuted")]
        summ = aggregate_findings(findings, known_categories=["bug"])
        fl.append_summary(summ, run_id="r", ts="t", root=tmp_path)
        (rec,) = fl.read_ledger(tmp_path)
        outcomes = {f["refutation_outcome"] for f in rec["findings"]}
        assert outcomes == {"survived", "refuted"}

    def test_one_run_one_line_and_additive(self, tmp_path):
        summ = aggregate_findings([_finding(1)], known_categories=["bug"])
        fl.append_summary(summ, run_id="r1", ts="t1", root=tmp_path)
        fl.append_summary(summ, run_id="r2", ts="t2", root=tmp_path)
        recs = fl.read_ledger(tmp_path)
        assert [r["run_id"] for r in recs] == ["r1", "r2"]

    def test_drops_malformed_finding_element_still_writes(self, tmp_path):
        """A non-dict or non-JSON-serialisable finding is dropped individually;
        the line still lands with the good ones; never raises (fail-open)."""
        summary = types.SimpleNamespace(
            total=4,
            by_category={"bug": 1},
            by_refutation_outcome={"survived": 1},
            survival_rate=1.0,
            corroborated=0,
            findings=[
                {"rule_or_scanner": "good", "category": "bug"},
                {"rule_or_scanner": "bad", "blob": {1, 2, 3}},  # set -> not JSON-serialisable
                42,            # not a dict
                "not a dict",  # not a dict
            ],
        )
        n = fl.append_summary(summary, run_id="r", ts="t", root=tmp_path)
        assert n == 1
        (rec,) = fl.read_ledger(tmp_path)
        assert len(rec["findings"]) == 1
        assert rec["findings"][0]["rule_or_scanner"] == "good"
        assert rec["finder_identities"] == ["good"]

    def test_null_category_does_not_drop_the_record(self, tmp_path):
        """A finding with category=None yields a None key in by_category; the
        record must STILL land. Regression: the writer serialized with
        sort_keys=True, which compares str vs None across the key set and raises
        TypeError — silently swallowed by the fail-open except, dropping the
        whole run. A null-category finding is the common case (an unbucketed
        finding), so this dropped most real runs. json coerces the None key to
        the string "null" (lossless), exactly as the _build_record docstring
        promises."""
        summary = types.SimpleNamespace(
            total=2,
            by_category={None: 1, "bug": 1},
            by_refutation_outcome={"survived": 2},
            survival_rate=1.0,
            corroborated=0,
            findings=[
                {"rule_or_scanner": "f", "category": None},
                {"rule_or_scanner": "f", "category": "bug"},
            ],
        )
        n = fl.append_summary(summary, run_id="r", ts="t", root=tmp_path)
        assert n == 1
        (rec,) = fl.read_ledger(tmp_path)
        assert rec["summary"]["by_category"] == {"null": 1, "bug": 1}

    def test_fail_open_on_write_error_returns_zero(self, tmp_path):
        """A write failure (cc/ is a file, so the dir cannot be created) returns 0
        and never raises — a logging error must never break a review."""
        (tmp_path / "cc").write_text("i am a file, not a dir", encoding="utf-8")
        summ = aggregate_findings([_finding(1)], known_categories=["bug"])
        assert fl.append_summary(summ, run_id="r", ts="t", root=tmp_path) == 0

    def test_auto_generates_run_id_and_ts(self, tmp_path):
        summ = aggregate_findings([_finding(1)], known_categories=["bug"])
        fl.append_summary(summ, root=tmp_path)
        fl.append_summary(summ, root=tmp_path)
        recs = fl.read_ledger(tmp_path)
        run_ids = [r["run_id"] for r in recs]
        assert all(run_ids) and run_ids[0] != run_ids[1]  # distinct, non-empty
        assert all(r["ts"] for r in recs)


class TestReadLedger:
    def test_absent_file_returns_empty(self, tmp_path):
        assert fl.read_ledger(tmp_path) == []

    def test_skips_malformed_line(self, tmp_path):
        """A partial-write tail or hand-edit must not poison the whole read."""
        summ = aggregate_findings([_finding(1)], known_categories=["bug"])
        fl.append_summary(summ, run_id="good-1", ts="t", root=tmp_path)
        with open(fl.ledger_path(tmp_path), "a", encoding="utf-8") as fh:
            fh.write("{not valid json\n")
            fh.write('{"run_id": "good-2", "ts": "t2"}\n')
        recs = fl.read_ledger(tmp_path)
        assert {r["run_id"] for r in recs} == {"good-1", "good-2"}


class TestLocalOnlyClassification:
    def test_ledger_classifies_local_only(self):
        rel = "cc/finding_ledger.jsonl"
        assert sc.is_local_only(rel) is True
        assert sc.classify_release_path(rel) == "local_only"

    def test_cc_public_surfaces_unaffected(self):
        """Guards against a stray cc/ prefix — cc/ carries committed public surfaces."""
        assert sc.classify_release_path("cc/COMMANDS.md") == "public"
        assert sc.classify_release_path("cc/LIVE_SURFACE.md") == "public"


class TestImportFirewall:
    def test_finding_ledger_imports_no_espalier_at_runtime(self):
        """The offline writer is a stdlib leaf: its only espalier import (the
        FindingsSummary type) sits under `if TYPE_CHECKING:`, so importing the
        module never pulls in the heavy fan_out_findings producer. Keeps the
        offline/in-loop split physical."""
        tree = ast.parse((REPO_ROOT / "espalier" / "finding_ledger.py").read_text(encoding="utf-8"))
        # Imports under an `if TYPE_CHECKING:` guard are annotation-only — allowed.
        type_checking_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test = node.test
                guarded = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                    isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
                )
                if guarded:
                    for sub in ast.walk(node):
                        if isinstance(sub, (ast.Import, ast.ImportFrom)):
                            type_checking_imports.add(sub)
        runtime_espalier = []
        for node in ast.walk(tree):
            if node in type_checking_imports:
                continue
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "espalier" or mod.startswith("espalier."):
                    runtime_espalier.append(mod)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "espalier" or alias.name.startswith("espalier."):
                        runtime_espalier.append(alias.name)
        assert runtime_espalier == [], (
            "espalier/finding_ledger.py imports espalier at RUNTIME "
            f"({runtime_espalier}); the offline writer must stay a stdlib leaf — "
            "only a TYPE_CHECKING import of FindingsSummary is allowed."
        )

    def test_tools_cc_import_of_ledger_is_caught_by_the_namespace_firewall(self, tmp_path):
        """The tools/cc→espalier firewall matches the whole `espalier.` namespace,
        so a tools/cc import of finding_ledger is caught automatically. This runs
        the REAL firewall scan (``test_contracts._scan_for_espalier_imports``)
        against a synthesized tools/cc-shaped file — NOT an inline copy of the
        predicate — so weakening the real firewall drops finding_ledger from the
        violations and REDs here, instead of a private copy staying green."""
        from tests.test_contracts import _scan_for_espalier_imports
        bad = tmp_path / "hooks" / "some_hook.py"
        bad.parent.mkdir(parents=True)
        bad.write_text(
            "from espalier.finding_ledger import append_summary\n", encoding="utf-8"
        )
        violations = _scan_for_espalier_imports(tmp_path)
        assert any("some_hook.py" in v and "espalier" in v for v in violations), violations


class TestStandingCallerLedgerWiring:
    """Pin the ledger wiring into the STANDING fan-out review workflows.

    The ledger only accrues signal if the *standing* (re-run-every-review)
    persisters call ``append_summary`` alongside the per-round report write
    (``append_findings_to_corpus`` on this round's ``reports/`` file). It was once wired into ``_fanout_audit.js``
    only, so the actively-run ``_layered_review.js`` produced zero ledger rows —
    a false-green (landed + green, but the enabling call sat in a rarely-run
    caller). Dated one-off review snapshots (``_deep_review_*``,
    ``_oss_convergence_round4``) are deliberately EXCLUDED: re-running a snapshot
    would double-count into the ledger. These tests fail if the wiring is
    dropped from a standing caller, or if a NEW persisting workflow is
    added without being classified standing-vs-dated (which would silently
    reintroduce the false-green the completeness critic flagged).
    """

    _WORKFLOWS = REPO_ROOT / ".claude" / "workflows"

    # STANDING = a run of this file SHOULD write a ledger row, so the wiring must
    # be present. DATED = its row is already written, so a re-run would write a
    # second row for the same round and double-count; the wiring must be absent.
    #
    # The discriminator is "would a run of this be a NEW round?", not "is it run
    # every review" — the older wording said the latter, which was never true of
    # anything but the template and _fanout_audit.js, and is not the property
    # either sibling test actually checks.
    STANDING_PERSISTERS = frozenset(
        {
            "_fanout_audit.js",
            "_layered_review.js",
            # TP-287: the scope-breaker-complete convergence scaffold — a reusable
            # start-here review runner (like _fanout_audit.js), so STANDING: it
            # calls both append_findings_to_corpus and append_summary.
            "_convergence_review_template.js",
            # Round 9 (2026-08-05). STANDING, not dated — classified on what the
            # files ARE, not on when they were written. `_oss_launch_review_…`
            # reads corpusPath / ledgerPath / finders / lens / baseRef / refute
            # from `args` exactly as the canonical template does; its 2026-08-05
            # names are DEFAULTS, so it is a runner with a filled-in DIMENSIONS
            # default, not a spent snapshot. `_goalie_unswept_…` hardcodes its
            # corpus path, as `_layered_review.js` does, and NEVER RAN — zero of
            # its 27 lane ids appear in the persisted round-9 payload and its
            # declared corpus was never written, so a run of it would be a first
            # round, not a replay. Both already call append_summary, so the
            # standing wiring holds with no edit.
            #
            # ⚠ BOTH CARRY FROZEN ROUND-9 STATE. Re-running either as-is is not
            # the same as running the canonical template, and the difference is
            # not visible from the classification:
            #   _goalie_unswept_…    BASE_REF is the literal '9159867' with no
            #                        args fallback — its delta-attacker diffs
            #                        against 2026-08-04 forever.
            #   _oss_launch_review_… its FRAME carries an "ALREADY MEASURED AT
            #                        HEAD — do NOT re-derive" list (ruff, audit,
            #                        provenance, freshness) pinned to 2026-08-05,
            #                        which would instruct every lane to skip four
            #                        checks on stale evidence.
            # Stated plainly, because the discriminator above does not say it:
            # DO NOT BARE-RE-RUN `_oss_launch_review_…`. Its baseRef and lens
            # default to round 9's, so an un-argumented run is a REPLAY of a
            # round already in the ledger — the double-count DATED_ONEOFFS
            # exists to prevent. It sits here rather than there because it is
            # shaped like a runner and because the ledger wiring it carries is
            # CORRECT for the parameterised run; the hazard is the defaults, not
            # the classification. Copy the canonical template for a new round;
            # reach for these only to re-run that specific lens, with baseRef and
            # lens overridden via args.
            "_oss_launch_review_2026_08_05.js",
            "_goalie_unswept_2026_08_05.js",
        }
    )
    # Dated one-off snapshots; excluded to avoid double-counting on re-run.
    DATED_ONEOFFS = frozenset(
        {
            "_oss_convergence_round4.js",
            "_deep_review_round7.js",
            "_deep_review_2026_06_18.js",
            "_convergence_2026_07_13.js",
        }
    )

    def _corpus_persisting_workflows(self):
        return {
            p.name
            for p in self._WORKFLOWS.glob("*.js")
            if _persists_anything(_code_lines(p.read_text(encoding="utf-8")))
        }

    def test_no_workflow_references_the_retired_shared_corpus(self):
        """The shared cross-round dedup corpus (``docs/known-findings.md``,
        ``DEFAULT_CORPUS_PATH``) was retired 2026-09-21: a survivor reaches the
        forward ledger only through a verify pass that files a row, a section-6
        do-not-rediscover entry, or nothing -- never by append. A scaffold that
        still names the constant fails at import time on its persist hop; one
        that still greps the file dedups against nothing. Both are pinned over
        EVERY scaffold, standing or dated, so a copy of an old round cannot
        reintroduce the hop.
        """
        paths = sorted(self._WORKFLOWS.glob("*.js"))
        assert len(paths) >= 10, (
            f"non-vacuity floor: {len(paths)} scaffold(s) under {self._WORKFLOWS} -- a "
            "moved or renamed directory would leave this pin green over nothing"
        )
        for path in paths:
            code = _code_lines(path.read_text(encoding="utf-8"))
            assert "DEFAULT_CORPUS_PATH" not in code, (
                f"{path.name} still imports or writes DEFAULT_CORPUS_PATH; the "
                "shared corpus is retired -- persist the per-round report and "
                "append_summary only"
            )
            assert "known-findings" not in code, (
                f"{path.name} still points a finder or refuter at the retired "
                "corpus; dedup against task-packs/FORWARD_LEDGER.md instead"
            )
            # The dedup source is gitignored. On a clean clone or a CI checkout
            # the grep returns nothing, and a lane told to drop-on-hit reads that
            # as "nothing known" and reports every survivor as new -- the exact
            # failure the shared corpus produced when it froze. Every DEDUP rule
            # must carry the absence clause, keyed by its token.
            if "DEDUP" in code and "FORWARD_LEDGER.md" in code:
                assert "ABSENT-LEDGER" in code, (
                    f"{path.name} dedups against the gitignored ledger without the "
                    "absence clause (ABSENT-LEDGER): on a clone the lane would read "
                    "an absent file as 'nothing known' and re-find everything"
                )

    def test_every_standing_persister_catches_a_persist_agent_throw(self):
        """The persist agent's own failure must not take the round down.

        Scoped to the PERSIST call deliberately. A bare ``".catch(" in source``
        check is vacuous here -- every one of these files already catches on its
        finder and refuter calls, so the token is present whether or not the
        persist call is guarded (measured, before the guard landed: it was not,
        in two of them). The contract is about one specific call, so the
        assertion has to find that call.
        """
        for name in sorted(self.STANDING_PERSISTERS):
            code = _code_lines((self._WORKFLOWS / name).read_text(encoding="utf-8"))
            start = code.find("agent(persistPrompt")
            assert start != -1, f"{name}: no agent(persistPrompt ...) call found"
            # The statement ends at the first line beginning with `})` -- the
            # close of the options object literal passed to agent().
            end = code.find("\n})", start)
            segment = code[start: end + 200] if end != -1 else code[start:start + 3000]
            assert ".catch(" in segment, (
                f"{name}'s persist agent call has no .catch(). A throw there "
                f"loses the whole round -- including the per-round report. Add a "
                f"fallback returning a persist_error, as the sibling persisters do."
            )
            # The fallback's only discriminator from "ran and appended nothing"
            # is persist_error: a literal appended: 0 with no error field is the
            # success-shaped zero the retired shared-write contract forbade.
            assert "persist_error" in segment, (
                f"{name}'s persist fallback carries no persist_error -- a failed "
                f"persist would read as a round that appended nothing"
            )

    def test_standing_persisters_surface_post_write_warnings(self):
        """Per-WRITE hazards that outlived the shared write (TP-436-C/E).

        ``append_findings_to_corpus`` still emits a RuntimeWarning through
        ``_warn_never_raise`` when an appended finding does not re-parse under
        its own key; only the persist hop's ``catch_warnings`` surfaces it, and
        only the printed ``warnings`` field carries it to the round's reader.
        Both were pinned by the retired shared-write dict; they are per-write,
        so they keep a pin over the standing set.
        """
        required = {
            "warnings.catch_warnings(record=True)": "post-write warnings need a reader",
            '"warnings"': "warnings must reach the printed JSON",
        }
        for name in sorted(self.STANDING_PERSISTERS):
            code = _code_lines((self._WORKFLOWS / name).read_text(encoding="utf-8"))
            for token, why in required.items():
                assert token in code, f"{name} is missing {token!r} -- {why}"

    def test_standing_persisters_also_call_append_summary(self):
        for name in self.STANDING_PERSISTERS:
            src = (self._WORKFLOWS / name).read_text(encoding="utf-8")
            # Require the CALL form in a non-comment line — a bare-substring
            # check passed even if the call was commented out (a false-green).
            code = _code_lines(src)
            assert "append_findings_to_corpus(" in code, (
                f"{name} is declared a standing persister but no longer "
                "CALLS append_findings_to_corpus (comment-out or removal)"
            )
            assert "append_summary(" in code, (
                f"{name} persists to the corpus but does NOT call "
                "append_summary — the ledger false-green has reopened "
                "(memory: trigger-gated-defect / TP-249 PR-4)"
            )

    def test_code_lines_drops_a_commented_out_call(self):
        # A call present only in a whole-line // comment must NOT satisfy the
        # hardened check, though the old bare-substring check would have.
        src = "// append_summary(x)\nconst a = 1"
        code = _code_lines(src)
        assert "append_summary(" not in code, "commented call leaked through"
        assert "append_summary" in src, (
            "regression guard: the old bare-substring check would have passed "
            "this commented-out call — that is exactly the false-green"
        )

    def test_code_lines_keeps_inline_comment_markers(self):
        # An inline // inside a string literal (e.g. https://) must survive so
        # the stripper can't mangle a real code line that carries a call.
        src = 'const url = "https://x"; append_summary(s)'
        code = _code_lines(src)
        assert "append_summary(" in code
        assert "https://" in code

    def test_hardened_check_rejects_a_commented_out_standing_call(self):
        # A standing persister whose ledger calls are commented out must fail
        # the hardened check — the false-green B-class hardening forecloses.
        commented = (
            "// append_findings_to_corpus(c)\n// append_summary(s)\nconst x = 1"
        )
        code = _code_lines(commented)
        assert "append_findings_to_corpus(" not in code
        assert "append_summary(" not in code

    # A private tag is stamped by spreading a finding into a new object literal
    # and adding an underscore-prefixed key: `{ ...f, _lane: d.id }`. Both halves
    # are DERIVED from the source rather than declared, because a hand-kept list
    # of key names is the enumeration-integrity class this repo has re-committed
    # for five rounds — and it failed here immediately: an earlier hand-kept
    # version listed `_finder`, but its value-shape alternation accepted `d.id`
    # and not `f.id`, so the `_finder` strip could be deleted from BOTH standing
    # workflows that use it and the contract stayed green.
    # An object literal that spreads something — the key may sit on EITHER side
    # of the spread token (`{ ...f, _lane: x }` and `{ _lane: x, ...f }` build
    # the same object), so the whole literal is scanned rather than the tail.
    _SPREAD_LITERAL_RE = re.compile(r"\{([^{}]*\.\.\.[^{}]*)\}")
    _PRIVATE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_$])(_[a-z][A-Za-z0-9_]*)\s*:")
    # ...and the same tag attached AFTER construction: `const r = {...f}; r._lane = x`.
    _POST_ASSIGN_RE = re.compile(r"\.(_[a-z][A-Za-z0-9_]*)\s*=(?!=)")
    _STRIP_DESTRUCTURE_RE = re.compile(r"map\(\(\{([^}]*)\}\s*\)\s*=>\s*rest\)")
    # ...and the GENERIC form, which names nothing and therefore cannot be read by
    # a name-collecting scan. Recognised by the ACT — build an object from the
    # entries whose key does NOT begin with `_` — because the whole point of the
    # form is that it enumerates no keys. The back-reference to the destructured
    # binding is load-bearing: it pins the predicate to the key being filtered, so
    # an INVERTED filter (`k.startsWith('_')`, which KEEPS the private fields) does
    # not read as a strip. Whitespace-tolerant and quote-agnostic; ``re.S`` because
    # the expression is conventionally wrapped across two lines.
    _GENERIC_STRIP_RE = re.compile(
        r"Object\.fromEntries\(\s*Object\.entries\([^()]*\)\s*\.filter\(\s*\(?\s*\[\s*"
        r"([A-Za-z_$][\w$]*)[^\]]*\]\s*\)?\s*=>\s*!\s*\1\s*\.\s*startsWith\(\s*['\"]_['\"]",
        re.S,
    )

    @classmethod
    def _stamped_keys(cls, src):
        """``{private key: offset of its LAST stamp}``, over non-comment source.

        Value-shape agnostic: the key is recognised by POSITION, never by what it
        is assigned to. ``_lane: d.id``, ``_lane: f.id``, ``_lanes: [f._lane]``,
        `` _lane: `penumbra:${x}` `` and ``_lane: someIdentifier`` all count — an
        earlier hand-written alternation over value shapes accepted ``d.id`` and
        not ``f.id``, which made the whole contract vacuous for the two standing
        workflows that stamp ``_finder: f.id``.

        TWO positions, because one was not enough either: inside a spreading
        object literal (either side of the ``...``), and assigned onto an object
        afterwards. Both are ordinary JS spellings of the same act, and a
        detector that knows only the first is the same fragility one syntactic
        door over from the hand-kept list it replaced. Measured: zero of the
        tracked workflows use the post-assign form today, so this costs nothing
        now and closes the refactor that would reopen the hole.
        """
        out = {}

        def _note(key, at):
            out[key] = max(out.get(key, -1), at)

        for spread in cls._SPREAD_LITERAL_RE.finditer(src):
            for m in cls._PRIVATE_KEY_RE.finditer(spread.group(1)):
                _note(m.group(1), spread.start(1) + m.start(1))
        for m in cls._POST_ASSIGN_RE.finditer(src):
            _note(m.group(1), m.start(1))
        return out

    @classmethod
    def _stripped_keys(cls, src):
        """``{private key: offset of its LAST strip}`` for NAMED strips only.

        A generic filter names no keys, so it cannot appear here — it is reported
        separately by :meth:`_generic_strip_offset` and combined in
        :meth:`_leaked_keys`. Keeping the two apart is deliberate: this map answers
        "where was THIS key named", which a nameless strip has no answer to.
        """
        out = {}
        for strip in cls._STRIP_DESTRUCTURE_RE.finditer(src):
            for m in re.finditer(r"_[a-z][A-Za-z0-9_]*", strip.group(1)):
                at = strip.start(1) + m.start()
                out[m.group()] = max(out.get(m.group(), -1), at)
        return out

    @classmethod
    def _generic_strip_offset(cls, src):
        """Offset of the LAST generic private-field strip, or ``-1`` if absent.

        A generic strip covers EVERY private key at once, so it needs no per-key
        entry — but it still needs a POSITION, because the same hoisting failure
        applies: a generic strip placed above the last stamp leaks exactly as a
        named one does.
        """
        return max((m.start() for m in cls._GENERIC_STRIP_RE.finditer(src)), default=-1)

    @classmethod
    def _leaked_keys(cls, src):
        """Private keys that reach the persist hop still attached.

        Two ways to leak, and the second is invisible to a set-membership check:
        the strip is ABSENT, or the strip runs BEFORE the last stamp. Hoisting
        the strip above the corroboration merge is a plausible tidy-up and
        reproduces the original defect exactly, so position is compared, not just
        presence. Comments are dropped from BOTH sides first, so a strip that
        exists only in a commented-out line does not count as a strip.

        TWO STRIP FORMS, and the second names nothing. A key counts as stripped if
        EITHER a named destructure named it, OR a generic ``_*`` filter covered it
        — whichever sits later in the source. The generic form is the one the
        workflows now ship; the named form is still recognised so a workflow that
        has not been converted is judged on what it actually does, not on which
        spelling the contract happens to prefer.
        """
        code = _code_lines(src)
        stamped, stripped = cls._stamped_keys(code), cls._stripped_keys(code)
        generic_at = cls._generic_strip_offset(code)
        return {
            k for k, at in stamped.items()
            if max(stripped.get(k, -1), generic_at) < at
        }

    def test_runnable_persisters_strip_every_private_lane_key(self):
        """A workflow that can still RUN must shed every private tag it stamps.

        Scope is the runnable set — everything under ``.claude/workflows/`` that
        is not a ``DATED_ONEOFFS`` member. That is the precise scope of the harm,
        not an allowlist around it: a dated snapshot has no ledger hop at all
        (``test_dated_oneoffs_do_not_accrete_to_the_ledger`` forbids the wiring),
        so it cannot under-report a ledger it never writes. Reclassifying a file
        standing therefore pulls it under this contract the same moment it gains
        the ability to break it.

        Round 9 is the case: the corroboration merge stamped ``_lanes`` and the
        pre-persist strip removed only ``_lane``, so 69 of 181 records were
        FINDING_SCHEMA-invalid and the round's structured row was a 61% sample
        read as a census.
        """
        checked = []
        for path in sorted(self._WORKFLOWS.glob("*.js")):
            if path.name in self.DATED_ONEOFFS:
                continue
            code = _code_lines(path.read_text(encoding="utf-8"))
            if not _persists_anything(code):
                continue
            checked.append(path.name)
            leaked = self._leaked_keys(code)
            assert not leaked, (
                f"{path.name} stamps {sorted(leaked)} and does not strip it "
                "before the schema-validated persist (absent strip, or a strip "
                "that runs before the last stamp) — FINDING_SCHEMA is "
                "additionalProperties:false, so every record carrying one is "
                "dropped from the structured ledger while the corpus persists "
                "fine, losing 69 of 181 records in the case that prompted this"
            )
        # Population pin: a narrowing that empties the scanned set must not read
        # as a pass. The canonical template is the copy source for every round,
        # so it is the one member named outright.
        assert "_convergence_review_template.js" in checked, (
            f"the runnable-persister population lost the canonical template: {checked}"
        )
        # And the derivation must actually be finding keys — a regex that silently
        # stops matching would empty every `stamped` set and pass over everything.
        found = set()
        for name in checked:
            found |= set(self._stamped_keys(_code_lines(
                (self._WORKFLOWS / name).read_text(encoding="utf-8")
            )))
        assert {"_lane", "_lanes", "_finder"} <= found, (
            f"the stamp derivation stopped recognising known private tags: {sorted(found)}"
        )

    # Every arm below is a mutation that a narrower version of this contract was
    # measured to pass. They are the contract's real specification.
    _STAMP = "else _byClaim.set(k, { ...f, _lanes: [f._lane] })\n"
    _STRIP = "findings = findings.map(({ _lane, _lanes, ...rest }) => rest)\n"

    def test_earn_the_red_absent_strip_is_caught(self):
        # The original defect: `_lanes` stamped by the merge, only `_lane`
        # destructured at the persist hop.
        broken = self._STAMP + "findings = findings.map(({ _lane, ...rest }) => rest)\n"
        assert self._leaked_keys(broken) == {"_lanes"}
        assert self._leaked_keys(self._STAMP + self._STRIP) == set()

    def test_earn_the_red_commented_out_strip_is_caught(self):
        # A strip disabled while debugging a lane and never restored. A raw
        # substring read counts it as present; _code_lines does not.
        assert self._leaked_keys(self._STAMP + "// " + self._STRIP) == {"_lanes"}

    def test_earn_the_red_strip_hoisted_above_the_stamp_is_caught(self):
        # Reordering the phases puts a real, uncommented strip in the file that
        # runs BEFORE the tag is attached. Set membership sees a strip and passes;
        # only comparing positions catches it.
        assert self._leaked_keys(self._STRIP + self._STAMP) == {"_lanes"}

    def test_earn_the_red_an_unforeseen_private_key_is_caught(self):
        # The point of deriving instead of declaring: a tag nobody listed.
        novel = "found.push({ ...f, _wave: 2 })\n" + self._STRIP
        assert self._leaked_keys(novel) == {"_wave"}

    def test_stamp_detection_is_value_shape_agnostic(self):
        # A hand-written alternation over value shapes accepted `d.id` and not
        # `f.id`, which made the contract vacuous for the two standing workflows
        # that stamp `_finder: f.id`. Position, not value, decides.
        for value in ("d.id", "f.id", "b.id", "[f._lane]", "'corpus-blind'", "laneId", "2"):
            src = "x = ({ ...f, _finder: %s })\n" % value
            assert "_finder" in self._stamped_keys(src), value

    # The GENERIC strip the workflows now ship: names no key, covers every one.
    _GENERIC_STRIP = (
        "findings = findings.map(f =>\n"
        "  Object.fromEntries(Object.entries(f).filter(([k]) => !k.startsWith('_'))))\n"
    )

    def test_generic_filter_strips_a_tag_no_hand_written_list_names(self):
        """The generic form's whole reason to exist: it covers tags nobody listed.

        The asymmetry against the old destructure IS the assertion. A two-name
        hand-written list passes a third tag straight through to a persist hop that
        is ``additionalProperties:false``, and the record is dropped silently.
        """
        stamps_novel = "found.push({ ...f, _wave: 2, _seed: 7 })\n"
        assert self._leaked_keys(stamps_novel + self._GENERIC_STRIP) == set()
        assert self._leaked_keys(stamps_novel + self._STRIP) == {"_wave", "_seed"}

    def test_finding_schema_declares_no_underscore_prefixed_property(self):
        # The filter's boundary is DERIVED from the schema, not asserted alongside
        # it: "drop what starts with _" is EXACTLY the schema boundary only while
        # the schema declares no such property. If one is ever added, this reds and
        # the strip must be reconsidered with it -- rather than silently deleting a
        # field the schema had started to accept.
        assert FINDING_SCHEMA.get("additionalProperties") is False
        assert [p for p in FINDING_SCHEMA["properties"] if p.startswith("_")] == []

    def test_earn_the_red_generic_strip_hoisted_above_the_stamp_is_caught(self):
        # Parity with the named form's hoisting arm. A generic strip covers every
        # key -- but only from where it SITS. Placed above the stamp it leaks
        # exactly as a named strip does, and a presence-only check would call it
        # covered. Position is compared for both forms or for neither.
        assert self._leaked_keys(self._GENERIC_STRIP + self._STAMP) == {"_lanes"}

    def test_an_inverted_generic_filter_does_not_read_as_a_strip(self):
        # `k.startsWith('_')` KEEPS the private fields -- the exact inverse of the
        # strip. A detector matching the SHAPE without the negation would read the
        # worst possible case as the fix, which is how a born-weak gate is made.
        inverted = (
            "findings = findings.map(f =>\n"
            "  Object.fromEntries(Object.entries(f).filter(([k]) => k.startsWith('_'))))\n"
        )
        assert self._leaked_keys(self._STAMP + inverted) == {"_lanes"}

    # A strip that covers `_lanes` only, so a leaked `_lane` is what the arms
    # below are actually measuring rather than the strip above swallowing it.
    _STRIP_LANES_ONLY = "findings = findings.map(({ _lanes, ...rest }) => rest)\n"

    def test_earn_the_red_key_written_before_the_spread_is_caught(self):
        # `{ _lane: d.id, ...f }` builds the same object as `{ ...f, _lane: d.id }`.
        # A detector anchored to the tail of the literal saw only one of them.
        before = "found.push({ _lane: d.id, ...f })\n" + self._STRIP_LANES_ONLY
        assert "_lane" in self._stamped_keys(before)
        assert self._leaked_keys(before) == {"_lane"}

    def test_earn_the_red_tag_attached_after_construction_is_caught(self):
        # `const r = { ...f }; r._lane = d.id` — no private key inside any literal
        # at all, so a literal-only detector sees nothing to strip.
        after = (
            "const r = { ...f }; r._lane = d.id; found.push(r)\n"
            + self._STRIP_LANES_ONLY
        )
        assert "_lane" in self._stamped_keys(after)
        assert self._leaked_keys(after) == {"_lane"}

    def test_leak_check_ignores_a_private_key_outside_a_spread(self):
        # Narrowness in the other direction: an underscore-prefixed key in an
        # ordinary object (not a finding being re-spread) is not a stamped tag,
        # and must not manufacture a finding.
        assert self._leaked_keys("const opts = { _timeout: 5 }\n") == set()

    def test_dated_oneoffs_do_not_accrete_to_the_ledger(self):
        for name in self.DATED_ONEOFFS:
            src = (self._WORKFLOWS / name).read_text(encoding="utf-8")
            assert "append_summary" not in src, (
                f"{name} is a dated one-off snapshot but calls append_summary "
                "— re-running it double-counts into the ledger; drop the wiring "
                "or reclassify it as standing"
            )

    def test_every_corpus_persister_is_classified(self):
        """A new corpus-persisting workflow must be explicitly added to one of
        the two sets above — otherwise it lands unclassified and this test
        fails, forcing the author to decide standing (wire the ledger) vs dated
        (leave it out). This is the guard against silently reintroducing the
        false-green via a fresh standing caller."""
        classified = self.STANDING_PERSISTERS | self.DATED_ONEOFFS
        found = self._corpus_persisting_workflows()
        unclassified = found - classified
        assert not unclassified, (
            "corpus-persisting workflow(s) not classified standing-vs-dated: "
            f"{sorted(unclassified)} — add each to STANDING_PERSISTERS (and wire "
            "append_summary) or DATED_ONEOFFS in TestStandingCallerLedgerWiring"
        )
        # And the declared standing/dated files must actually exist + persist
        # (guards against a rename leaving a dangling classification).
        assert classified <= found, (
            "classified workflow(s) missing or no longer corpus-persisting: "
            f"{sorted(classified - found)}"
        )
