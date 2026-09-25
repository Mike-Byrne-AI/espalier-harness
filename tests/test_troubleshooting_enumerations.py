# pytest-marker: default-unit
"""``docs/TROUBLESHOOTING.md``'s two enumerations, pinned to their derivations.

Both blocks enumerate a population the code owns, and both had drifted:

- The *"doctor returns warn"* section said ``doctor`` runs **three** checks
  while the payload emits **six** -- and the three it named included ``audit``,
  which cannot produce ``warn`` at all (it only ever appends to ``failures``),
  while omitting ``reflect``, the one that actually warns on an ordinary
  adopter repo. It also described a byte-divergence check that does not exist.
- The *"uninstall everything"* section listed five categories of survivor.
  Driven end-to-end (``init`` -> ``install-ci`` -> ``clean-generated
  --execute``), **36 files survive and 27 match none of those five**, 20 of
  them seeded docs totalling ~467 KB. Its closing promise -- *"delete any of
  those by hand if you want a bare tree"* -- was falsified by execution.

**Why these are contracts and not generated regions.** The sibling members of
this class (``README.md``, ``docs/QUICKSTART.md``) are fixed by generation via
``scripts/generate_doc_regions.py``. This file cannot be: it is both an
``init`` seed doc *and* a mirror source, and
``espalier/cli.py::_seed_redeploy_decision`` returns ``"preserve"``
**permanently** once an adopter's post-stamp bytes stop hashing to the recorded
digest. A generated region here would freeze the first time they edited one
word, leaving them holding a block that says *do not hand-edit* which they have
no ``scripts/`` to regenerate. Hence the rule this suite exists under:

    Generate where the doc has no downstream copies; contract where it ships.

So the prose stays hand-written and adopter-ownable, and these assertions make
it impossible for it to go stale silently.

Both derivations are read from source rather than restated here -- the roster
by AST-walking the ``checks`` dict literal (the same technique
``TestScanSubmodesConsistent`` uses for ``/scan`` sub-modes), the survivor
directories from the live deploy inventories.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "TROUBLESHOOTING.md"


def _section(heading_fragment: str) -> str:
    """Return the body of the ``## "..."`` section whose heading contains
    ``heading_fragment``, up to the next ``##`` heading."""
    text = DOC.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    for part in parts:
        if heading_fragment in part.split("\n", 1)[0]:
            return part
    raise AssertionError(
        f"no section heading containing {heading_fragment!r} in {DOC.name} -- "
        "the heading was reworded; re-point this test rather than deleting it."
    )


def _flat(text: str) -> str:
    """Collapse whitespace and drop emphasis markers before a phrase match.

    Every phrase assertion below is about MEANING, and the prose is hard-wrapped
    at ~76 columns with ``**bold**`` runs -- so a raw substring test is decided
    by where a line happens to break. That cuts both ways, and the second way is
    the dangerous one: the absence checks would silently pass if a removed
    sentence came back wrapped differently than it left.
    """
    return re.sub(r"\s+", " ", text.replace("*", "")).lower()


def _doctor_check_names() -> set[str]:
    """The keys of ``run_doctor_check``'s ``checks`` dict, by AST.

    Derived, not declared: the roster moved from 3 to 6 without either the doc
    or any test noticing, which is the drift this closes.
    """
    tree = ast.parse((REPO_ROOT / "espalier" / "doctor.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "run_doctor_check"):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Dict):
                continue
            for key, value in zip(sub.keys, sub.values):
                if (isinstance(key, ast.Constant) and key.value == "checks"
                        and isinstance(value, ast.Dict)):
                    return {
                        k.value for k in value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    raise AssertionError(
        "could not locate run_doctor_check's `checks` dict literal in "
        "espalier/doctor.py -- if the payload is now built dynamically, this "
        "derivation needs rewriting, not deleting."
    )


class TestDoctorCheckRoster:
    def test_the_derivation_is_not_vacuous(self):
        """A derivation that returns nothing would make every arm below pass."""
        assert len(_doctor_check_names()) >= 5

    def test_every_check_is_named_in_the_doc(self):
        names = _doctor_check_names()
        body = _section("espalier doctor` returns warn")
        missing = sorted(n for n in names if f"`{n}`" not in body)
        assert not missing, (
            f"docs/TROUBLESHOOTING.md's doctor section does not name {missing}. "
            f"run_doctor_check emits {sorted(names)}; a reader whose warn came "
            "from an unnamed check finds no entry for what they are seeing."
        )

    def test_the_doc_does_not_understate_the_roster(self):
        """The original defect was a literal count -- 'runs three checks'.

        Any bare number in that sentence must match the live roster size, so
        the next check added cannot leave the prose quietly wrong.
        """
        # _flat() here too. Running this regex on the RAW body made a pure
        # reflow fail: wrapping so `runs` ends a line, or bolding the numeral
        # (`runs **six** checks`), stopped it matching -- and the assertion
        # below then reported the count as DELETED and suggested deleting the
        # arm. A guard whose red instruction is "remove the guard" converts a
        # cosmetic edit into lost coverage.
        body = _flat(_section("espalier doctor` returns warn"))
        words = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10}
        stated = [
            words[m.group(1)] for m in
            re.finditer(r"\bruns (\w+) checks\b", body) if m.group(1) in words
        ]
        assert stated, (
            "the doctor section no longer states how many checks run -- if that "
            "was deliberate, delete this arm and say why; a silently dropped "
            "count is how the last one went stale."
        )
        assert all(n == len(_doctor_check_names()) for n in stated), (
            f"doctor section states {stated} checks; the payload emits "
            f"{len(_doctor_check_names())}."
        )

    def test_the_absent_byte_divergence_check_is_not_reintroduced(self):
        """`doctor` never compares an adopter's file against the packaged one.

        The removed bullet claimed a hand-edited agent body reports as warn via
        byte-divergence. Driven: it warns once, via `diff` (fingerprint drift),
        then passes forever once the fingerprint is re-saved -- a different
        mechanism with a different remedy.
        """
        body = _section("espalier doctor` returns warn")
        assert "byte-divergence as warn" not in _flat(body)


class TestUninstallSurvivors:
    @staticmethod
    def _surviving_top_levels() -> set[str]:
        from espalier import managed_inventory

        survivors = (
            managed_inventory.get_seed_docs()
            + managed_inventory.get_install_ci_artifacts()
            + managed_inventory.local_runtime_rel_paths()
        )
        return {rel.split("/", 1)[0] for rel in survivors if "/" in rel}

    def test_the_derivation_is_not_vacuous(self):
        assert len(self._surviving_top_levels()) >= 4

    def test_every_surviving_top_level_is_named(self):
        """A new seed doc in a new directory must reach this prose.

        The measured failure: `memory/` and `task-packs/` were created by
        `init`, survived `clean-generated`, and appeared in neither the
        uninstall list nor any other adopter-facing enumeration.
        """
        body = _section("I want to uninstall everything Espalier wrote")
        missing = sorted(
            top for top in self._surviving_top_levels()
            if f"`{top}/" not in body and f"`{top}`" not in body
        )
        assert not missing, (
            f"the uninstall section does not name surviving location(s) {missing}. "
            "Every top-level directory that outlives `clean-generated --execute` "
            "has to appear, or the recipe cannot produce the tree it promises."
        )

    def test_the_falsified_bare_tree_promise_is_not_restored(self):
        """Driven, the recipe left 36 files; the old sentence promised none."""
        body = _section("I want to uninstall everything Espalier wrote")
        assert "by hand if you want a bare tree" not in _flat(body), (
            "the 'delete any of those by hand if you want a bare tree' promise "
            "is back. It was falsified by execution: following it literally "
            "leaves ~27 unnamed files, including this very doc."
        )

    def test_the_doc_names_itself_as_a_survivor(self):
        """It is on the seed list, so it survives its own uninstall recipe."""
        body = _section("I want to uninstall everything Espalier wrote")
        assert "this troubleshooting file is one of them" in _flat(body)

    def test_install_ci_artifacts_are_named(self):
        from espalier import managed_inventory

        body = _section("I want to uninstall everything Espalier wrote")
        # The `.new` twin is written only conditionally; the two unconditional
        # artifacts are what an adopter finds still on disk.
        for rel in managed_inventory.get_install_ci_artifacts():
            if rel.endswith(".new"):
                continue
            assert f"`{rel}`" in body, (
                f"{rel} survives `clean-generated` but the uninstall section "
                "does not name it."
            )


@pytest.mark.parametrize("heading", [
    "espalier doctor` returns warn",
    "I want to uninstall everything Espalier wrote",
])
def test_sections_are_locatable(heading: str) -> None:
    """Guard the locator itself: a reworded heading must fail loudly here
    rather than silently skipping every assertion above."""
    assert _section(heading).strip()


class TestTheDerivationCannotGoBlind:
    """The AST walk reads ONE `"checks": {...}` dict literal. Pin that premise.

    `_doctor_check_names` is the basis for every roster arm above, and it is a
    static read. A 7th check added by mutation instead --
    `report["checks"]["quarantine"] = ...` -- leaves it returning 6, the doc
    still saying "six", and `test_the_derivation_is_not_vacuous` (>= 5) still
    green: the exact drift this file exists to close, reproduced inside its own
    derivation. Flagged as PLAUSIBLE by a failure-mode pass.

    Asserted statically rather than by driving `doctor`, deliberately. The
    runtime probe was written first and **skipped** -- an uninitialized tmp repo
    emits no `checks` key at all, and building an initialized one costs a
    subprocess `init` (this module is not in `_SLOW_FILES`). A skipping arm
    proves nothing, and the failure mode is *lexical* anyway: it is the presence
    of a second write path, which source can answer exactly.
    """

    def test_the_checks_payload_is_not_mutated_after_construction(self):
        source = (REPO_ROOT / "espalier" / "doctor.py").read_text(encoding="utf-8")
        mutations = re.findall(r'\[\s*["\']checks["\']\s*\]\s*\[', source)
        assert not mutations, (
            "espalier/doctor.py assigns into the `checks` payload after it is "
            "built, so the single-dict-literal AST walk in _doctor_check_names "
            "can no longer see the whole roster. Every assertion in this file is "
            "then reading a stale set. Rewrite the derivation to cover both "
            "paths; do not delete it."
        )

    def test_exactly_one_checks_literal_inside_run_doctor_check(self):
        """Two literals in that function and the walk takes an arbitrary one.

        Scoped to `run_doctor_check`, matching `_doctor_check_names`. The first
        version of this arm searched the whole module and went red on arrival --
        correctly finding a SECOND `checks` literal in `_source_checkout_report`
        that the derivation never reaches. That one is pinned below rather than
        excluded, because it is the roster for a mode the doc also describes.
        """
        tree = ast.parse((REPO_ROOT / "espalier" / "doctor.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run_doctor_check")
        literals = [
            v for n in ast.walk(fn) if isinstance(n, ast.Dict)
            for k, v in zip(n.keys, n.values)
            if isinstance(k, ast.Constant) and k.value == "checks"
            and isinstance(v, ast.Dict)
        ]
        assert len(literals) == 1, (
            f"found {len(literals)} `checks` dict literals inside "
            "run_doctor_check; _doctor_check_names returns the first one walked, "
            "which is arbitrary. Make the derivation name its canonical source."
        )

    def test_the_source_checkout_roster_matches_the_doc(self):
        """The doc claims a `source_checkout` runs `presence` alone. Pin it.

        The roster is MODE-DEPENDENT (6 initialized / 1 source_checkout / 0
        uninitialized), which is why the doc cannot carry a bare count. This
        arm exists because the second `checks` literal -- surfaced by the arm
        above going red -- is exactly that mode's roster, and nothing related
        it to the prose.
        """
        tree = ast.parse((REPO_ROOT / "espalier" / "doctor.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_source_checkout_report")
        names = {
            c.value for n in ast.walk(fn) if isinstance(n, ast.Dict)
            for k, v in zip(n.keys, n.values)
            if isinstance(k, ast.Constant) and k.value == "checks"
            and isinstance(v, ast.Dict)
            for c in v.keys if isinstance(c, ast.Constant)
        }
        assert names == {"presence"}, (
            f"a source_checkout now runs {sorted(names)}, but "
            "docs/TROUBLESHOOTING.md says it 'runs `presence` alone'."
        )
        assert "runs `presence` alone" in _section("espalier doctor` returns warn")
