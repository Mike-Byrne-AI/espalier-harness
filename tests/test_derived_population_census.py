"""The census oracle's own health checks must actually RUN.

``scripts/derived_population_census.py`` is the standing enumerator for the
``docs/FAILURE_MODES.md`` §18.4 class -- test populations derived from the source
they police. It carries four self-checks (the ``ADJUDICATED`` digest map, a
``SELF_CHECK_MUST_SEE`` roster, an unresolved-bindings detector and a
stale-exclusion arm), and until
this module existed **none of them ran**: no test, hook or CI job invoked the
script, so every one was inert until a human typed the command by hand.

That is the same shape as the class itself -- a guard that exists, reads as
enforcement, and fires for nobody. The script's own docstring called
``check_health`` "the cheapest mechanical form of that check"; it is mechanical
only once something calls it.

⚠ Loaded via ``importlib.spec_from_file_location`` per ``tests/CLAUDE.md`` --
``scripts/`` is not an importable package.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
from pathlib import Path

import pytest

from tests import _source_segment
from tests._git_oracle import require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "derived_population_census.py"


def _load_census():
    spec = importlib.util.spec_from_file_location("derived_population_census", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _load_census()


@functools.lru_cache(maxsize=1)
def _rows() -> tuple[dict, ...]:
    """The census, computed ONCE.

    ``census_derived_populations()`` AST-parses every ``tests/**/*.py`` on each
    call. Calling it per row took this module to ~88s on its own; the shape rows
    alone would run it five more times. Cached at module scope -- the tree does
    not change mid-session.
    """
    return tuple(census.census_derived_populations())


@pytest.mark.timeout(300)
class TestCensusHealth:
    """The oracle polices a class; these rows police the oracle.

    ⚠ Explicit timeout, well above ``pyproject.toml``'s global ``timeout = 60``.
    These rows AST-parse every ``tests/**/*.py`` — ~17 s on an idle machine,
    but measured at ~88 s under the parallel-agent load this repo's own review
    workflow generates, which blew the 60 s global and red on a CLEAN tree.
    A contract test that reds for load rather than for truth is one the reader
    learns to skip, and a skipped gate is worse than no gate: it still reads as
    enforcement. Raised rather than loosened — nothing about the assertions
    changed, only the wall-clock allowance for the walk.
    """

    def test_health_passes_on_the_live_tree(self) -> None:
        assert census.check_health(list(_rows())) == 0, (
            "the census reports itself unhealthy on the live tree. Run "
            "`python3 scripts/derived_population_census.py` for the reasons -- a "
            "shape handler has gone dark, a filed member is no longer visible, "
            "or a file's source bindings stopped resolving."
        )

    def test_health_fails_on_an_empty_census(self) -> None:
        """The negative twin. Without it, a check_health that always returned 0
        would satisfy the row above and prove nothing."""
        assert census.check_health([]) != 0, (
            "check_health returned OK for an EMPTY census. Every floor and every "
            "self-check is then vacuous, and the row above is theatre."
        )

    @pytest.mark.parametrize("shape", census.SHAPES)
    def test_every_declared_shape_is_actually_found(self, shape: str) -> None:
        """A shape in SHAPES that the walker never emits is a dead declaration.

        Parametrized from ``SHAPES`` deliberately: this is the CORRECT side of
        §18.4's discriminator (the property is "every declared shape is live",
        and dropping a shape from SHAPES legitimately drops its requirement).
        The ADJUDICATED digest map is what pins the population; this row only
        pins that each declared shape is still LIVE. ⚠ `found > 0` is itself a
        `>=` floor -- the shape §18.4 retracts -- and it is deliberately weak:
        it answers 'did this handler go dark', and the digest answers 'did it
        narrow'. Neither is a substitute for the other.
        """
        found = sum(1 for r in _rows() if r["shape"] == shape)
        assert found > 0, (
            f"shape {shape!r} is declared in SHAPES but the walker emits zero "
            f"rows for it. Either the handler is broken or the shape should be "
            f"removed from SHAPES."
        )

    def test_the_unresolved_residue_is_backed(self) -> None:
        """Every file the resolver cannot read is named WITH a reason.

        An unbacked exclusion list is the hand-list moved from the population to
        the subtraction -- the same class one level up.
        """
        for path, reason in census.UNRESOLVED_BY_DESIGN.items():
            assert reason.strip(), f"{path} is excluded with no written reason."
            assert (REPO_ROOT / path).exists(), (
                f"UNRESOLVED_BY_DESIGN names {path}, which does not exist. A "
                f"stale exclusion silently widens the blind spot."
            )

    def test_no_documented_impossibility_is_reintroduced(self) -> None:
        """``SELF_CHECK_CORRECTLY_ABSENT`` must stay empty.

        It once held a file on the reasoning that its zero rows proved the defect
        was closed. Measurement refuted that -- the zero was a RESOLVER result and
        held whether the defect was open or closed. §18.4: a documented
        impossibility forecloses its own fix more durably than a missing test,
        because it is why the next person does not look. Absence is proved by the
        unresolved-bindings check, never by prose.
        """
        assert census.SELF_CHECK_CORRECTLY_ABSENT == {}, (
            "SELF_CHECK_CORRECTLY_ABSENT is non-empty. Before adding an entry, "
            "prove the file's zero-row result is caused by the remedy and not by "
            "the resolver -- reopen the defect in a scratch copy and confirm the "
            "census then REPORTS it."
        )


class TestTheAdjudicatedMapIsALiteral:
    """The map that replaced the `>=` floors must not become a restatement of
    the census it checks.

    ⚠ THIS IS THE ROW THE WHOLE ARTEFACT RESTS ON, and it is not
    belt-and-braces. `check_health` compares `ADJUDICATED` against the live
    census; a future tidy that derives `ADJUDICATED` FROM
    `census_derived_populations()` keeps every count, every digest and every
    runtime value bit-identical, so **no assertion over values can see it** --
    the comparison simply becomes `x == x`. Only an AST-level check that the map
    is still a hand-written literal can. §18.4 records the measured
    counterfactual on the sibling instance: with this row absent, regenerating
    the roster AND deleting a member ran fully green with a real hole open.

    Precedent for the shape:
    `tests/test_write_guard_command_position.py::_module_level_assignments`, and
    `tests/test_release_denylist.py::TestNoSharedImports` before it.
    """

    @staticmethod
    def _script_assignments() -> dict[str, ast.expr]:
        # encoding pinned, same reason the precedent pins it: the census script
        # carries section signs and arrows, and on a runner with an unset locale
        # a bare read_text() resolves to US-ASCII and reds every row here on a
        # CORRECT tree. A false red in the row whose job is to be believed
        # teaches the reader to distrust it.
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        found: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    found[node.target.id] = node.value
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node.value
        return found

    def test_adjudicated_is_a_hand_written_dict_literal(self):
        value = self._script_assignments()["ADJUDICATED"]
        why = (
            "ADJUDICATED must stay a literal `dict` of string keys mapping to "
            "tuples of constants. Deriving it from census_derived_populations() "
            "makes check_health tautological with every value unchanged -- the "
            "one failure no value-level assertion in this module can see."
        )
        assert isinstance(value, ast.Dict), why
        for key, entry in zip(value.keys, value.values):
            assert isinstance(key, ast.Constant) and isinstance(key.value, str), why
            assert isinstance(entry, ast.Tuple), why
            assert len(entry.elts) == 4, f"{key.value}: entry must be a 4-tuple"
            for element in entry.elts:
                assert isinstance(element, ast.Constant), why

    def test_no_stored_total_sits_beside_the_map(self):
        """TP-479 Wave C, decision 2a (2026-10-10): the two hand-typed totals
        are gone. They were a tripwire for a wholesale regeneration and also
        one line every adjudicating lane rewrote (all 15 commits before their
        removal), a shared record storing what two lanes both recompute (Core
        Rule 15). **The guarantee given up, stated:** a regeneration that
        carries every verdict forward and keeps the map a literal is caught by
        nothing here now; this class's literal row still catches one that
        derives the map in code. Mutation seen red: a total put back."""
        stored = sorted(name for name, value in self._script_assignments().items()
                        if name.startswith("ADJUDICATED_") and isinstance(value, ast.Constant))
        assert not stored, (
            f"{stored}: a stored total beside ADJUDICATED is one line every lane that "
            f"adjudicates a file must rewrite, so two lanes conflict on it; derive it "
            f"(len / sum) where a reader needs it."
        )

    def test_nothing_in_the_script_writes_the_map_at_runtime(self):
        """No `--update-adjudicated` path may exist, now or later.

        An in-repo regeneration flag defeats every guard above by making the
        collapse a one-command operation instead of a deliberate edit. The
        script ships `--print-adjudicated-entry`, which PRINTS one line to
        stdout and writes nothing; that hand step IS the adjudication.
        """
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

        def _touches_map(sub: ast.AST) -> bool:
            # ⚠ Rebinding is the LEAST likely shape -- it needs a `global`.
            # In-place mutation needs nothing, so `ADJUDICATED[f] = ...` and
            # `ADJUDICATED.update({...})` are what someone adding an
            # `--update-adjudicated` flag actually writes. An earlier draft of
            # this row checked only `ast.Name` targets and caught 1 of the 3
            # shapes, while its docstring claimed to forbid all of them.
            if isinstance(sub, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                for tgt in targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "ADJUDICATED":
                        return True
                    if (
                        isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "ADJUDICATED"
                    ):
                        return True
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                owner = sub.func.value
                if (
                    isinstance(owner, ast.Name)
                    and owner.id == "ADJUDICATED"
                    and sub.func.attr in {
                        "update", "setdefault", "pop", "popitem", "clear",
                        "__setitem__", "__delitem__",
                    }
                ):
                    return True
            return False

        writers = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for sub in ast.walk(node)
            if _touches_map(sub)
        ]
        assert not writers, (
            f"function(s) {sorted(set(writers))} assign ADJUDICATED at runtime. "
            f"The map is authored by hand; a writer turns the regenerate-from-"
            f"the-subject collapse into one command."
        )


class TestTheAdjudicatedMapIsBacked:
    """Anti-rot, in the shape `tests/_contracts.py::NumericPopulation.exclusions`
    uses: an entry must still be backed by something live, or it is a permanent
    unexplained hole rather than a recorded judgement.
    """

    def test_every_adjudicated_file_still_exists(self):
        missing = sorted(
            path for path in census.ADJUDICATED
            if not (REPO_ROOT / path).is_file()
        )
        assert not missing, (
            f"ADJUDICATED names file(s) that no longer exist: {missing}. Drop the "
            f"entry and lower both counts in the same edit -- a stale entry "
            f"overstates what has been adjudicated."
        )

    def test_the_verdict_vocabulary_is_closed(self):
        """A free-text verdict field degrades into whatever the last editor typed.

        ⚠ `PRIOR_PASS_UNRECORDED` and `MIXED_WITH_PRIOR_PASS` are not filler.
        They mark the 34 files whose rows were adjudicated in the earlier
        parametrize/for-assert pass, which preserved only an aggregate and no
        per-row reason. They are the standing upgrade list, and they exist so
        that gap is legible instead of being papered over with an invented
        reason.
        """
        allowed = {
            "CORRECT_BY_REMEDY", "CORRECT_BY_PROPERTY", "CORRECT_BY_SHAPE",
            "NOT_A_MEMBER", "MIXED", "MIXED_WITH_PRIOR_PASS",
            "PRIOR_PASS_UNRECORDED", "UNRECORDED",
        }
        unknown = sorted(
            {entry[2] for entry in census.ADJUDICATED.values()} - allowed
        )
        assert not unknown, f"unknown verdict code(s): {unknown}"

    def test_every_entry_carries_a_written_reason(self):
        blank = sorted(
            path for path, entry in census.ADJUDICATED.items() if not entry[3].strip()
        )
        assert not blank, (
            f"entries with no written reason: {blank}. An unexplained entry is "
            f"indistinguishable from a rubber stamp."
        )


@pytest.mark.timeout(300)
class TestCheckHealthEarnsItsRed:
    """Every arm of `check_health` proved able to fail, driven in memory.

    ⚠ These share the module-level `_rows()` cache, so the whole battery costs
    ZERO extra tree walks -- the mutations are applied to a copied map or a
    filtered row list, never to the tree. That is what makes an exhaustive
    negative battery affordable next to a ~17 s (~88 s under load) walk.

    ⚠ Mutually load-bearing with `test_health_passes_on_the_live_tree`, but NOT
    for the reason an earlier draft of this docstring gave. It claimed "`return 2`
    satisfies every row here"; measured, a `return 2` stub fails ALL of these,
    because every one also asserts on the stderr text. The row `return 2` really
    does satisfy is `test_health_fails_on_an_empty_census`, which is why
    `test_health_passes_on_the_live_tree` is its mandatory twin. Recorded because
    the first reader to check the old claim would have found it false and
    discounted the warning -- which is how a real pairing gets simplified away.
    """

    def test_dropping_an_adjudicated_entry_reds(self, monkeypatch, capsys):
        trimmed = dict(census.ADJUDICATED)
        victim = sorted(trimmed)[0]
        del trimmed[victim]
        monkeypatch.setattr(census, "ADJUDICATED", trimmed)
        assert census.check_health(list(_rows())) != 0
        assert victim in capsys.readouterr().err

    def test_a_ghost_entry_reds(self, monkeypatch, capsys):
        haunted = dict(census.ADJUDICATED)
        haunted["tests/test_this_file_does_not_exist.py"] = (
            1, "0" * 64, "CORRECT_BY_PROPERTY", "fabricated",
        )
        monkeypatch.setattr(census, "ADJUDICATED", haunted)
        assert census.check_health(list(_rows())) != 0
        assert "test_this_file_does_not_exist.py" in capsys.readouterr().err

    def test_a_wrong_row_count_reds(self, monkeypatch, capsys):
        skewed = dict(census.ADJUDICATED)
        victim = sorted(skewed)[0]
        count, digest, verdict, reason = skewed[victim]
        skewed[victim] = (count + 1, digest, verdict, reason)
        monkeypatch.setattr(census, "ADJUDICATED", skewed)
        assert census.check_health(list(_rows())) != 0
        assert victim in capsys.readouterr().err

    def test_a_corrupted_digest_reds(self, monkeypatch, capsys):
        corrupted = dict(census.ADJUDICATED)
        victim = sorted(corrupted)[0]
        count, _, verdict, reason = corrupted[victim]
        corrupted[victim] = (count, "f" * 64, verdict, reason)
        monkeypatch.setattr(census, "ADJUDICATED", corrupted)
        assert census.check_health(list(_rows())) != 0
        assert victim in capsys.readouterr().err

    def test_deleting_ONE_row_of_a_multi_row_file_reds(self, capsys):
        """The 28% collapse a roster keyed on (file, shape, population) misses.

        `(file, shape, population)` is NOT unique here, so a roster keyed on
        it -- or any set comparison -- stays green while a duplicate row
        disappears. The digest is over a sorted LIST for exactly this row.

        ⚠ No count is quoted. An earlier draft carried "208 rows hold 149
        distinct triples ... 59 deletable", measured before the glob widening
        landed in the same change and stale within the hour. The property is
        asserted below instead (`assert dupes`), which cannot go stale.
        """
        counts: dict[str, int] = {}
        for row in _rows():
            counts[str(row["file"])] = counts.get(str(row["file"]), 0) + 1
        dupes = {
            str(r["file"])
            for r in _rows()
            if sum(
                1 for other in _rows()
                if other["file"] == r["file"]
                and other["shape"] == r["shape"]
                and other["population_full"] == r["population_full"]
            ) > 1
        }
        assert dupes, "no duplicate-triple file on this tree -- re-derive this row"
        victim_file = sorted(dupes)[0]
        dropped = False
        kept = []
        for row in _rows():
            if not dropped and str(row["file"]) == victim_file:
                dropped = True
                continue
            kept.append(row)
        assert census.check_health(kept) != 0, (
            "deleting one row of a file with duplicate (shape, population) "
            "triples went unnoticed -- the digest has stopped carrying "
            "multiplicity, and every duplicate row on this tree is now "
            "deletable in silence."
        )
        assert victim_file in capsys.readouterr().err

    def test_a_file_losing_every_row_reds_as_vanished(self, capsys):
        victim = sorted(census.ADJUDICATED)[0]
        kept = [r for r in _rows() if str(r["file"]) != victim]
        assert census.check_health(kept) != 0
        assert victim in capsys.readouterr().err

    def test_an_unadjudicated_new_file_reds(self, monkeypatch, capsys):
        """A NEW derived population must red on arrival, not accumulate.

        This is the arm that fixes the workflow harm: the previous design
        emitted 207 undifferentiated candidates on every run, so a newly-added
        population was indistinguishable from the 206 already judged correct.
        """
        trimmed = dict(census.ADJUDICATED)
        victim = sorted(trimmed)[0]
        del trimmed[victim]
        monkeypatch.setattr(census, "ADJUDICATED", trimmed)
        assert census.check_health(list(_rows())) != 0
        assert "no ADJUDICATED entry" in capsys.readouterr().err


class TestTheDigestSeesThroughIndirection:
    """A one-hop alias hid a 9-to-1 narrowing from the digest. Pinned so it cannot return.

    ⚠ FOUND BY THE ADVERSARIAL PASS OVER THIS FIX, at `DEF-598`'s own founding
    site. `file_digest` hashes `(shape, population_full, bound_via)`. When the
    iterated expression is an alias, `population_full` is just the alias NAME --
    the right-hand side that does the narrowing appears in no hashed field. So
    `_TEMPLATE_NAMES = list(<source>)[:1]` took five parametrized classes from 9
    templates to 1 with the digest BIT-IDENTICAL and `check_health` returning 0,
    and `SELF_CHECK_MUST_SEE` still passed because the NAME never moved.

    The fix put the indirection text into `bound_via`, which was already hashed.
    """

    def test_every_indirect_binding_carries_its_source_text(self):
        indirect = [
            r for r in _rows()
            if str(r["bound_via"]).startswith(("alias of", "source accessor fn"))
        ]
        assert indirect, "no alias/accessor-bound rows -- re-derive this row"
        naked = [
            f"{r['file']}:{r['line']} -> {r['bound_via']}"
            for r in indirect
            if " := " not in str(r["bound_via"])
        ]
        assert not naked, (
            f"binding(s) record only the resolution ROUTE and not the expression "
            f"behind it: {naked}. Narrowing that expression would then be "
            f"invisible to file_digest, which is the exact defect this class is."
        )

    def test_digest_moves_when_only_the_indirection_changes(self):
        """Hermetic: two row sets identical but for the alias RHS."""
        base = [{
            "file": "tests/test_x.py", "line": 1, "shape": "parametrize",
            "population": "_NAMES", "population_full": "_NAMES",
            "bound_via": "alias of mod := list(mod.CONST)", "verdict": None,
        }]
        narrowed = [dict(base[0], bound_via="alias of mod := list(mod.CONST)[:1]")]
        assert census.file_digest(base) != census.file_digest(narrowed), (
            "file_digest ignores the alias's right-hand side, so a narrowing "
            "that never touches the iterated expression stays invisible."
        )


class TestTheReasonExplainsTheVerdict:
    """A written reason is only a record if it describes the verdict it sits beside.

    ⚠ An earlier draft of the map applied one generic fallback string --
    "verdict rests on the property, not a remedy" -- to 20 entries, of which 10
    carried a DIFFERENT verdict. On a `NOT_A_MEMBER` entry it asserted a
    property-based CORRECT verdict, explaining nothing. Only non-emptiness was
    enforced, so prose carried the contract and prose does not fail.
    """

    def test_a_remedy_verdict_cites_a_locatable_pin(self):
        """CORRECT_BY_REMEDY means 'a pin exists elsewhere' -- so name it.

        This is §18.4's own instruction ("before grading a site, grep for a pin
        on the same constant elsewhere") turned into a check on the record.
        """
        import re

        pin = re.compile(r"\S+\.(?:py|md|toml):\d+")
        uncited = sorted(
            path for path, entry in census.ADJUDICATED.items()
            if entry[2] == "CORRECT_BY_REMEDY" and not pin.search(entry[3])
        )
        assert not uncited, (
            f"CORRECT_BY_REMEDY entries citing no `path:line`: {uncited}. An "
            f"uncited remedy is not a remedy -- it is an assertion that one "
            f"exists, which is the claim §18.4 says to verify, not to record."
        )

    def test_the_property_reason_is_not_used_under_another_verdict(self):
        marker = "everything present is safe"
        misapplied = sorted(
            path for path, entry in census.ADJUDICATED.items()
            if marker in entry[3] and entry[2] != "CORRECT_BY_PROPERTY"
        )
        assert not misapplied, (
            f"entries whose reason argues 'everything present is safe' while "
            f"recording a different verdict: {misapplied}."
        )


# Every line-end shape the shared helper must slice as the stdlib does: the form
# feed (which ``str.splitlines`` would split on and the parser does not), the lone
# CR, CRLF with a multi-byte character before the node (offsets are bytes), a tab
# with multi-byte text inside a multi-line node, wrapped concatenation, an
# f-string, no trailing newline, and the empty source.
_LINE_END_SHAPES = {
    "form-feed-before-a-multi-line-tuple": "a = 1\n\x0cb = (1,\n     2)\n",
    "lone-cr": "a = (1,\r     2)\rb = 3\r",
    "crlf-and-multibyte": "prefix = 'é'; x = (1,\r\n       2)\ny = 'ü' + 'v'\n",
    "tab-and-multibyte-in-a-multi-line-node": "if True:\n\tx = ('é',\n\t     'ü')\n",
    "wrapped-concatenation": "s = ('a'\n     'b')\n",
    "f-string": "s = f'{a!r:>{w}}' + 'b'\n",
    "no-trailing-newline": "x = (1,\n     2)",
    "empty": "",
}


@pytest.mark.timeout(300)
class TestSegmentHelper:
    """``_segment`` stands in for ``ast.get_source_segment`` (DEF-762).

    The stdlib call re-splits the WHOLE file on every call, and on Python
    3.10 that split is a per-character loop: the census made 31,098 calls
    over 1.85 GB of re-split text, about 186 s on the 3.10 CI cell against a
    60 s per-test timeout, while 3.14 finished the same walk in 19 s. The
    helper splits once per file and slices by the parser's byte offsets.

    ``tests/_source_segment.py`` loads the pair by path and is the one slicer
    every caller imports; the census below keeps the stdlib call out of every
    root it walks except as a reference pin or a declared exemption (DEF-3005).
    """

    def test_segment_matches_the_stdlib_on_the_census_itself(self) -> None:
        """Every positioned node of a 1,500-line module with non-ASCII comments."""
        text = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = census._source_lines(text)
        nodes = [n for n in ast.walk(tree) if hasattr(n, "lineno")]
        # A bounded, deterministic sample. The stdlib oracle IS the quadratic
        # call this helper replaces: over every node of this script it cost
        # 25 s on 3.10 (measured by review, 2026-09-13) and grows with the
        # script, so a fixed-size stride keeps the pin's cost flat while every
        # node kind the file contains still reaches it.
        stride = max(1, len(nodes) // 400)
        sample = nodes[::stride]
        for node in sample:
            assert census._segment(lines, node) == ast.get_source_segment(text, node), (
                node.lineno, type(node).__name__
            )
        assert len(sample) >= 300, "the parity walk saw almost nothing"

    def test_segment_slices_by_byte_offset_across_mixed_line_endings(self) -> None:
        """A multi-byte character before the node and a CRLF inside it."""
        text = "prefix = 'é'; x = (1,\r\n       2)\ny = 'ü' + 'v'\n"
        tree = ast.parse(text)
        lines = census._source_lines(text)
        tuple_node = next(n for n in ast.walk(tree) if isinstance(n, ast.Tuple))
        binop = next(n for n in ast.walk(tree) if isinstance(n, ast.BinOp))
        # The multi-byte 'é' sits before the tuple on its line: a character
        # slice would start one column early. The offsets are bytes.
        assert census._segment(lines, tuple_node) == "(1,\r\n       2)"
        assert census._segment(lines, binop) == "'ü' + 'v'"
        for node in ast.walk(tree):
            if hasattr(node, "lineno"):
                assert census._segment(lines, node) == ast.get_source_segment(text, node)

    @pytest.mark.parametrize("shape", sorted(_LINE_END_SHAPES))
    def test_the_shared_helper_matches_the_stdlib_on_every_line_end_shape(self, shape: str) -> None:
        """Through the helper's public API: every positioned node of each shape, and
        a node with no positions (compared with the stdlib, not with a literal)."""
        text = _LINE_END_SHAPES[shape]
        lines = _source_segment.source_lines(text)
        for node in ast.walk(ast.parse(text)):
            if hasattr(node, "lineno"):
                assert _source_segment.segment(lines, node) == ast.get_source_segment(text, node), (
                    shape, ast.dump(node)[:80]
                )
        bare = ast.Name(id="x", ctx=ast.Load())
        assert _source_segment.segment(lines, bare) == ast.get_source_segment(text, bare)

    @pytest.mark.parametrize(
        "split", [str, str.splitlines, lambda t: t.splitlines(keepends=True), lambda t: list(_source_segment.source_lines(t))],
        ids=["the-text", "splitlines", "splitlines-keepends", "a-list-copy"],
    )
    def test_the_shared_helper_refuses_anything_but_its_own_split(self, split) -> None:
        text = "a = 1\n\x0cb = (1,\n     2)\n"
        node = ast.parse(text).body[1]
        with pytest.raises(TypeError, match="source_lines"):
            _source_segment.segment(split(text), node)

    def test_the_split_is_cached_so_the_composed_form_splits_once(self) -> None:
        text = "x = (1,\n     2)\n" * 3
        first = _source_segment.source_lines(text)
        again = _source_segment.source_lines(text)
        assert again is first, "a second split of the same text built a new object"

    def test_no_stdlib_segment_reference_outside_a_reference_pin(self) -> None:
        """Every root the census walks is clear of the per-node re-split (DEF-3005)."""
        strays, _, _ = _segment_census(REPO_ROOT)
        assert strays == [], (
            "ast.get_source_segment is referenced outside a reference pin:\n"
            + "".join(
                f"  {rel}:{lineno} in {qual} ({form} reference)\n      fix: {_segment_remedy(rel)}\n"
                for rel, lineno, qual, form in strays
            )
            + "Each call re-splits the WHOLE source text, and on Python 3.10 and 3.11 that\n"
            "split is a per-character loop: one call per node over a large file crosses the\n"
            "60 s per-test ceiling on the required test (3.10) cell (DEF-762; the ledger\n"
            "reader census on #207; DEF-3005). Split once, then slice per node:\n"
            "    lines = source_lines(text)   # once per text (cached)\n"
            "    segment(lines, node)         # per node: the stdlib's answer\n"
            "The stdlib call is allowed only as a reference pin -- assert segment(...) ==\n"
            "ast.get_source_segment(...) -- in a file listed in _PIN_HOMES ("
            + ", ".join(sorted(_PIN_HOMES))
            + "); a pin moved to another file moves its _PIN_HOMES entry with it. A call\n"
            "that crosses no per-test ceiling may be a declared exemption with its reason\n"
            "(_SEGMENT_EXEMPT)."
        )

    def test_every_pin_home_and_exemption_holds_its_exact_count(self) -> None:
        """A pin turned vacuous, a new per-node pin, or an exemption that no longer
        binds each moves a count, and every count is exact."""
        _, pins, exempt = _segment_census(REPO_ROOT)
        assert pins == _PIN_HOMES, (
            f"reference pins by home: found {pins}, declared {_PIN_HOMES}. A pin whose "
            "stdlib side was rewritten to the slicer compares the slicer with itself and "
            "proves nothing; change a declared count only in the diff that deliberately "
            "adds or removes a pin."
        )
        declared = {key: count for key, (count, _reason) in _SEGMENT_EXEMPT.items()}
        assert exempt == declared, (
            f"stdlib calls in declared exemptions: found {exempt}, declared {declared}. "
            "Re-read the exemption's reason: a call gone retires the entry, and a second "
            "call is a new site, not the excused one."
        )
        dead = sorted(home for home, count in _PIN_HOMES.items() if count < 1) + sorted(
            str(key) for key, count in declared.items() if count < 1)
        assert not dead, (
            f"declared with a count of zero, so they hold or excuse nothing: {dead}. "
            "Remove the entry."
        )

    def test_every_tracked_python_file_is_under_a_root_or_a_declared_skip(self) -> None:
        """The root list is checked against the tracked population, so a new
        top-level home for Python cannot fall outside the census unseen."""
        tracked = require_tracked_paths(
            REPO_ROOT, "*.py", minimum=500, what="tracked Python files")
        roots = tuple(f"{root}/" for root in _SEGMENT_ROOTS)
        skips = tuple(_SEGMENT_SKIP)
        orphans = sorted(p for p in tracked if not p.startswith(roots + skips))
        assert orphans == [], (
            f"tracked Python files under no census root and no declared skip: {orphans}. "
            "Add the directory to _SEGMENT_ROOTS, or the path to _SEGMENT_SKIP with its "
            "reason (a root-level script, a generated file)."
        )
        unused = sorted(s for s in skips if not any(p.startswith(s) for p in tracked))
        assert unused == [], f"declared skips that match no tracked file: {unused}. Remove them."


# ---------------------------------------------------------------------------
# The split-once census (DEF-3005): no stdlib segment call outside a pin
# ---------------------------------------------------------------------------

_SEGMENT_NAME = "get_source_segment"

# The roots the census walks (air 3e6d42, widened by 46b603 after review). The
# class began in a scripts/ module a test drove (DEF-762), and tests drive
# tools/review_agent_audit.py and the examples/ goldens the same way, so every
# root that holds a tracked .py is walked; the completeness row reds a tracked
# .py under no root and no declared skip. The engine imports neither tests/ nor
# scripts/: a site that ever appears under espalier/ gets its own stdlib-pinned
# helper there, never an import, and today that root holds none.
_SEGMENT_ROOTS = ("tests", "scripts", "tools", "bench", "espalier", "examples")

# Paths the walk skips, each with its reason. A skip that matches no tracked file
# reds the completeness row.
_SEGMENT_SKIP = {
    "espalier/_vendor/": (
        "copies of walked sources: cc/ is a byte-mirror of tools/cc/ and "
        "selfcheck_tests/ a synced subset of tests/ (two files transformed); "
        "each source is walked as itself"
    ),
}

# Reference pins: an `assert` comparing the split-once slicer with the stdlib call
# by one `==`, either order. They are found by that shape, allowed only in these
# files, and each count is exact.
_PIN_HOMES = {
    "tests/test_derived_population_census.py": 4,
    "tests/test_maintenance_mode.py": 1,
}

# A declared exemption: a stdlib call that crosses no per-test ceiling, keyed by
# file and enclosing function, with the premise that excuses it. The count is
# exact, so a second call there, or the call gone, reds and the entry is re-read.
_SEGMENT_EXEMPT = {
    ("bench/run_benchmark.py", "invoke_deploy_iteration_invariant"): (
        1,
        "one call per verifier run, on the one FunctionDef the check reads, outside "
        "tests/ and under no per-test timeout; excused only while that holds",
    ),
}

_SLICER_NAMES = frozenset({"segment", "_segment"})


def _call_name(node: ast.AST) -> str | None:
    """The called name of a ``Call`` (``f(...)`` or ``x.f(...)``), else None."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
    return None


def stdlib_segment_references(source: str | bytes) -> list[tuple[int, str, str, bool]]:
    """Every reference to the stdlib segment call in ``source``, in source order.

    One ``(lineno, qualname, form, pin_shaped)`` per reference. ``qualname`` is
    the enclosing ``Class.function``, or ``<module>``. ``form`` is ``attribute``
    (through ``ast``, ``_ast`` or any alias: a call, an assignment, an argument
    to ``functools.partial`` or ``map``), ``name`` (bare, after a from-import),
    ``import`` (a from-import of the name, from any module) or ``getattr`` (the
    name as a literal second argument). ``pin_shaped`` is True only for the
    callee of one side of ``assert <slicer>(...) == <stdlib>(...)``: one ``==``,
    either order, the other side a call named ``segment`` or ``_segment``.
    Comments and string literals are never references.
    """
    tree = ast.parse(source)
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def qualname(node: ast.AST) -> str:
        names = []
        cur = parent.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(cur.name)
            cur = parent.get(cur)
        return ".".join(reversed(names)) or "<module>"

    def pin_shaped(ref: ast.AST) -> bool:
        call = parent.get(ref)
        if not (isinstance(call, ast.Call) and call.func is ref):
            return False
        compare = parent.get(call)
        if not (
            isinstance(compare, ast.Compare)
            and len(compare.ops) == 1
            and isinstance(compare.ops[0], ast.Eq)
        ):
            return False
        if compare.left is call:
            other = compare.comparators[0]
        elif compare.comparators[0] is call:
            other = compare.left
        else:
            return False
        stmt = parent.get(compare)
        return (
            isinstance(stmt, ast.Assert)
            and stmt.test is compare
            and _call_name(other) in _SLICER_NAMES
        )

    refs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == _SEGMENT_NAME:
            form = "attribute"
        elif isinstance(node, ast.Name) and node.id == _SEGMENT_NAME:
            form = "name"
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name == _SEGMENT_NAME for alias in node.names
        ):
            form = "import"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == _SEGMENT_NAME
        ):
            form = "getattr"
        else:
            continue
        pin = form in ("attribute", "name") and pin_shaped(node)
        refs.append((node.lineno, qualname(node), form, pin))
    return sorted(refs)


def _segment_census(
    root: Path,
) -> tuple[list[tuple[str, int, str, str]], dict[str, int], dict[tuple[str, str], int]]:
    """Walk ``_SEGMENT_ROOTS`` under ``root``: (strays, pins by home, calls by exemption).

    A file is parsed only when its bytes name the call, so a fixture that is not
    UTF-8 is never decoded; a file that names it and does not parse raises.
    """
    strays = []
    pins = dict.fromkeys(_PIN_HOMES, 0)
    exempt = dict.fromkeys(_SEGMENT_EXEMPT, 0)
    needle = _SEGMENT_NAME.encode()
    for top in _SEGMENT_ROOTS:
        for path in sorted((root / top).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(tuple(_SEGMENT_SKIP)):
                continue
            data = path.read_bytes()
            if needle not in data:
                continue
            for lineno, qual, form, pin in stdlib_segment_references(data):
                if pin and rel in _PIN_HOMES:
                    pins[rel] += 1
                elif (rel, qual) in _SEGMENT_EXEMPT:
                    exempt[(rel, qual)] += 1
                else:
                    strays.append((rel, lineno, qual, form))
    return strays, pins, exempt


def _segment_remedy(rel: str) -> str:
    """The fix the census names for a stray at ``rel``: only tests/ may import the
    shared slicer."""
    if rel.startswith("tests/"):
        return "from tests._source_segment import segment, source_lines"
    return (
        "this root may not import tests/ (tools/ and espalier/ ship standalone; "
        "scripts/, bench/ and examples/ run as programs): split once in the file "
        "with a local pair modelled on scripts/derived_population_census.py's "
        "_source_lines/_segment, pinned equal to the stdlib in a _PIN_HOMES file"
    )


class TestTheSegmentCensus:
    """The census's walk, driven on planted trees: each root, the skip, the homes,
    the exemption and a file that does not parse."""

    @pytest.mark.parametrize(
        ("rel", "says"),
        [
            ("tests/test_x.py", "from tests._source_segment import"),
            ("tools/cc/x.py", "may not import tests/"),
            ("espalier/x.py", "may not import tests/"),
            ("scripts/x.py", "may not import tests/"),
        ],
    )
    def test_the_fix_named_for_a_stray_fits_its_root(self, rel: str, says: str) -> None:
        assert says in _segment_remedy(rel)

    @pytest.mark.parametrize(
        "rel",
        [
            "tests/test_planted.py",
            "scripts/planted.py",
            "tools/cc/hooks/planted.py",
            "tools/review_agent_audit.py",
            "bench/planted.py",
            "espalier/planted.py",
            "examples/golden/planted.py",
        ],
    )
    def test_a_planted_reference_under_each_root_is_named(self, tmp_path: Path, rel: str) -> None:
        planted = tmp_path / rel
        planted.parent.mkdir(parents=True)
        planted.write_bytes(b"import ast\nseg = ast.get_source_segment\n")
        strays, pins, exempt = _segment_census(tmp_path)
        assert strays == [(rel, 2, "<module>", "attribute")]
        assert set(pins.values()) == {0} and set(exempt.values()) == {0}

    def test_the_vendored_mirror_is_not_walked(self, tmp_path: Path) -> None:
        planted = tmp_path / "espalier" / "_vendor" / "cc" / "planted.py"
        planted.parent.mkdir(parents=True)
        planted.write_bytes(b"import ast\nseg = ast.get_source_segment\n")
        assert _segment_census(tmp_path)[0] == []

    def test_a_pin_shaped_assert_outside_the_homes_is_a_stray(self, tmp_path: Path) -> None:
        planted = tmp_path / "tests" / "test_planted.py"
        planted.parent.mkdir(parents=True)
        planted.write_bytes(
            b"import ast\n"
            b"def test_x(lines, text, node):\n"
            b"    assert segment(lines, node) == ast.get_source_segment(text, node)\n"
        )
        assert _segment_census(tmp_path)[0] == [("tests/test_planted.py", 3, "test_x", "attribute")]

    def test_a_pin_in_a_home_counts_and_a_per_node_call_there_is_a_stray(self, tmp_path: Path) -> None:
        home = tmp_path / "tests" / "test_maintenance_mode.py"
        home.parent.mkdir(parents=True)
        home.write_bytes(
            b"import ast\n"
            b"class TestPin:\n"
            b"    def test_pin(self, lines, text, node):\n"
            b"        assert segment(lines, node) == ast.get_source_segment(text, node)\n"
            b"    def test_walk(self, text, tree):\n"
            b"        return [ast.get_source_segment(text, n) for n in ast.walk(tree)]\n"
        )
        strays, pins, _ = _segment_census(tmp_path)
        assert strays == [("tests/test_maintenance_mode.py", 6, "TestPin.test_walk", "attribute")]
        assert pins["tests/test_maintenance_mode.py"] == 1

    def test_an_exemption_counts_its_own_function_only(self, tmp_path: Path) -> None:
        bench = tmp_path / "bench" / "run_benchmark.py"
        bench.parent.mkdir(parents=True)
        bench.write_bytes(
            b"import ast\n"
            b"def invoke_deploy_iteration_invariant(src, node):\n"
            b"    return ast.get_source_segment(src, node)\n"
            b"def other(src, node):\n"
            b"    return ast.get_source_segment(src, node)\n"
        )
        strays, _, exempt = _segment_census(tmp_path)
        assert strays == [("bench/run_benchmark.py", 5, "other", "attribute")]
        assert exempt == {("bench/run_benchmark.py", "invoke_deploy_iteration_invariant"): 1}

    def test_a_file_that_names_the_call_and_does_not_parse_is_loud(self, tmp_path: Path) -> None:
        planted = tmp_path / "tests" / "test_planted.py"
        planted.parent.mkdir(parents=True)
        planted.write_bytes(b"get_source_segment(\n")
        with pytest.raises(SyntaxError):
            _segment_census(tmp_path)


class TestStdlibSegmentReferenceDetector:
    """Each reference form, and each shape that is not one, as source text: the
    rows are string literals, so this file never becomes a site."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("for n in ast.walk(t):\n    s = ast.get_source_segment(src, n)\n", [("attribute", False)]),
            ("import ast as _ast\nx = _ast.get_source_segment(s, n)\n", [("attribute", False)]),
            ("from ast import get_source_segment\nx = get_source_segment(s, n)\n",
             [("import", False), ("name", False)]),
            ("from ast import get_source_segment as g\nx = g(s, n)\n", [("import", False)]),
            ("from mod import get_source_segment\n", [("import", False)]),
            ("seg = ast.get_source_segment\n", [("attribute", False)]),
            ("f = getattr(ast, 'get_source_segment')\n", [("getattr", False)]),
            ("f = functools.partial(ast.get_source_segment, src)\n", [("attribute", False)]),
            ("segs = list(map(ast.get_source_segment, [s] * 2, nodes))\n", [("attribute", False)]),
            ("def seg(s, n):\n    return ast.get_source_segment(s, n)\n", [("attribute", False)]),
            ("x = segment(l, n) == ast.get_source_segment(s, n)\n", [("attribute", False)]),
            ("assert segment(l, n) == ast.get_source_segment(s, n) == y\n", [("attribute", False)]),
            ("assert segment(l, n) != ast.get_source_segment(s, n)\n", [("attribute", False)]),
            ("assert other(l, n) == ast.get_source_segment(s, n)\n", [("attribute", False)]),
            ("assert segment(l, n) == wrap(ast.get_source_segment)\n", [("attribute", False)]),
            ("assert ok, segment(l, n) == ast.get_source_segment(s, n)\n", [("attribute", False)]),
            ("assert census._segment(lines, node) == ast.get_source_segment(text, node), (node.lineno,)\n",
             [("attribute", True)]),
            ("assert ast.get_source_segment(text, node) == segment(lines, node)\n", [("attribute", True)]),
            ("assert _segment(lines, node) == ast.get_source_segment(src, node), ast.dump(node)[:80]\n",
             [("attribute", True)]),
            ('"""ast.get_source_segment(s, n)"""\n# ast.get_source_segment(s, n)\nname = "get_source_segment"\n',
             []),
            ("y = ast.get_source_segment_x(s, n)\n", []),
        ],
        ids=[
            "per-node-call-in-a-walk",
            "module-alias",
            "from-import-then-bare-call",
            "from-import-under-an-alias",
            "from-import-from-any-module",
            "assignment-alias",
            "getattr-by-literal-name",
            "functools-partial",
            "map-over-nodes",
            "a-helper-that-delegates",
            "equality-outside-an-assert",
            "chained-equality",
            "inequality",
            "other-side-not-the-slicer",
            "stdlib-passed-as-an-argument",
            "comparison-in-the-assert-message",
            "pin-as-the-census-writes-it",
            "pin-stdlib-side-first",
            "pin-with-a-message",
            "comments-and-strings",
            "a-longer-attribute-name",
        ],
    )
    def test_each_form(self, source: str, expected: list[tuple[str, bool]]) -> None:
        found = [(form, pin) for _lineno, _qual, form, pin in stdlib_segment_references(source)]
        assert found == expected

    def test_the_enclosing_name_is_class_qualified(self) -> None:
        source = (
            "class TestX:\n"
            "    def test_y(self):\n"
            "        def inner():\n"
            "            return ast.get_source_segment(s, n)\n"
        )
        assert stdlib_segment_references(source) == [(4, "TestX.test_y.inner", "attribute", False)]

    def test_an_async_method_is_qualified_too(self) -> None:
        source = "class C:\n    async def f(self):\n        return ast.get_source_segment(s, n)\n"
        assert stdlib_segment_references(source) == [(3, "C.f", "attribute", False)]
