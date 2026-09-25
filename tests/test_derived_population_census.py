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

    @pytest.mark.parametrize(
        "name", ["ADJUDICATED_FILE_COUNT", "ADJUDICATED_ROW_COUNT"]
    )
    def test_the_counts_are_integer_literals(self, name):
        value = self._script_assignments()[name]
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            f"{name} must be a hand-typed integer. Written as `len(ADJUDICATED)` "
            f"or `sum(...)` it agrees with the map by construction and stops "
            f"being a tripwire -- it is precisely what should RED when someone "
            f"regenerates the map, which is why it is not derived."
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

    def test_the_counts_agree_with_the_map(self):
        assert len(census.ADJUDICATED) == census.ADJUDICATED_FILE_COUNT, (
            "ADJUDICATED_FILE_COUNT disagrees with the map. Both move in the "
            "same edit -- that is the point of the literal."
        )
        assert (
            sum(entry[0] for entry in census.ADJUDICATED.values())
            == census.ADJUDICATED_ROW_COUNT
        ), "ADJUDICATED_ROW_COUNT disagrees with the per-file row counts."

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


@pytest.mark.timeout(300)
class TestSegmentHelper:
    """``_segment`` stands in for ``ast.get_source_segment`` (DEF-762).

    The stdlib call re-splits the WHOLE file on every call, and on Python
    3.10 that split is a per-character loop: the census made 31,098 calls
    over 1.85 GB of re-split text, about 186 s on the 3.10 CI cell against a
    60 s per-test timeout, while 3.14 finished the same walk in 19 s. The
    helper splits once per file and slices by the parser's byte offsets.
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

    def test_the_census_never_calls_the_stdlib_segment_per_node(self) -> None:
        """The stdlib call may not return: one call per node is the 3.10 red."""
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        name = "get_source_segment"
        # Every spelling: `ast.get_source_segment(...)`, a bare name after
        # `from ast import get_source_segment`, and the import itself.
        calls = sorted(
            n.lineno
            for n in ast.walk(tree)
            if (isinstance(n, ast.Attribute) and n.attr == name)
            or (isinstance(n, ast.Name) and n.id == name)
            or (
                isinstance(n, ast.ImportFrom)
                and n.module == "ast"
                and any(alias.name == name for alias in n.names)
            )
        )
        assert calls == [], (
            f"ast.get_source_segment reaches the census at lines {calls}: it "
            "re-splits the whole file on every call, and on Python 3.10 that split "
            "is a per-character loop -- DEF-762: 31,098 calls took ~186 s on the "
            "3.10 CI cell against a 60 s per-test timeout. Use _segment over "
            "_source_lines, split once per file."
        )
