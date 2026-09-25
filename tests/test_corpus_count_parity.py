"""Pin `espalier.doctor` and `scripts.release_check` to the same
definition of "bypass class count" on the live corpus.

Prevents the dual-truth coherence drift where both tools assert the
same conceptual claim (bypass-class count for `README.md` /
`bench/RESULTS.md`) via independent glob patterns that disagree:
one counts `*.json` (49, all corpus files including BC-OOS-NNN),
the other counts `BC-[0-9]*.json` (45, in-scope numeric only).
Without this contract, doctor reports "states 45 but bench/corpus/
contains 49" and the operator chases stale-doc fixes that fight the
release_check truth.

Guards: extraction-by-regex pins both call sites to the same glob
string; canonical-pattern test ensures neither drifts away from
`BC-[0-9]*.json`; live-corpus equality test catches filesystem
divergence on identical patterns (case-insensitive FS oddities,
gitignore filtering surprises).
"""

import pathlib
import re

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestDoctorReleaseCheckCorpusCountParity:
    """The corpus-count assertions in `espalier/doctor.py` (the
    `--check-doc-drift` flow) and `scripts/release_check.py` (the
    `check_docs_count_claims` flow) must use the same glob pattern
    against `bench/corpus/`. Both should match `BC-[0-9]*.json`
    (in-scope numeric bypass classes), excluding the `BC-OOS-NNN`
    out-of-scope namespace.

    Drift here means README's claim about bypass-class count agrees
    with one tool but not the other — operator following one ends up
    fighting the other (the pre-fix instance: doctor reported "states
    45 but bench/corpus/ contains 49" while release_check counted 45).
    """

    _GLOB_RE = re.compile(r'corpus_dir\.glob\(\s*"([^"]+)"\s*\)')
    #: Any spelling of an in-scope corpus count -- ``corpus_dir.glob(...)``,
    #: ``d.glob(...)``, ``(ROOT / "bench" / "corpus").glob(...)`` -- so the
    #: site list is derived from the tree, never retyped (a third and fourth
    #: caller had appeared with spellings the two-file regex above cannot see).
    _IN_SCOPE_GLOB_RE = re.compile(r'\.glob\(\s*"(BC-\[0-9\][^"]*)"\s*\)')
    _SITE_ROOTS = ("espalier", "scripts", "tests")
    _CANONICAL = "BC-[0-9]*.json"

    def _in_scope_glob_sites(self) -> dict[str, list[str]]:
        sites: dict[str, list[str]] = {}
        for root in self._SITE_ROOTS:
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                if "_vendor" in path.parts or "__pycache__" in path.parts:
                    continue
                found = self._IN_SCOPE_GLOB_RE.findall(path.read_text(encoding="utf-8"))
                if found:
                    sites[str(path.relative_to(REPO_ROOT)).replace("\\", "/")] = found
        return sites

    def test_every_in_scope_count_site_uses_the_canonical_glob(self) -> None:
        sites = self._in_scope_glob_sites()
        assert {"espalier/doctor.py", "scripts/release_check.py"} <= set(sites), (
            f"the two pinned tools no longer glob the in-scope corpus: {sorted(sites)}"
        )
        off = {f: g for f, g in sites.items() if any(x != self._CANONICAL for x in g)}
        assert not off, (
            f"in-scope corpus-count sites that do not use {self._CANONICAL!r}: {off}. "
            "Every site that counts in-scope bypass classes must spell the same glob."
        )

    def _extract_glob(self, file_rel: str) -> str:
        path = REPO_ROOT / file_rel
        text = path.read_text(encoding="utf-8")
        match = self._GLOB_RE.search(text)
        if match is None:
            pytest.fail(
                f"could not locate a `corpus_dir.glob(...)` call in "
                f"{file_rel}; the parity contract assumes both files "
                "glob the corpus dir"
            )
        return match.group(1)

    def test_doctor_and_release_check_use_same_corpus_glob(self) -> None:
        doctor_glob = self._extract_glob("espalier/doctor.py")
        release_check_glob = self._extract_glob("scripts/release_check.py")
        assert doctor_glob == release_check_glob, (
            f"corpus-count glob drift: "
            f"espalier/doctor.py uses {doctor_glob!r}; "
            f"scripts/release_check.py uses {release_check_glob!r}. "
            "Both must match `BC-[0-9]*.json`. If one needs to change, "
            "change both — or extract the pattern into a shared helper "
            "(deferred until a third caller exists)."
        )

    def test_glob_matches_canonical_in_scope_pattern(self) -> None:
        doctor_glob = self._extract_glob("espalier/doctor.py")
        assert doctor_glob == "BC-[0-9]*.json", (
            f"corpus glob is {doctor_glob!r}; expected `BC-[0-9]*.json` "
            "(in-scope numeric bypass classes, excluding BC-OOS-NNN). "
            "If both tools drifted to a different pattern, this catches "
            "it; if the in-scope definition changed, update the corpus "
            "naming convention first (it's load-bearing — see "
            "tests/test_documented_claims.py BC-028 / BC-OOS-004 block)."
        )

    def test_counts_agree_on_live_corpus(self) -> None:
        """Tautological — both sides called ``corpus_dir.glob("BC-[0-9]*.json")``
        on the same path; the test passed by construction. The
        extraction-by-regex contract
        (``test_doctor_and_release_check_use_same_corpus_glob``) carries the
        load by AST-extracting each producer's pattern string and comparing.
        Retained for archeology; the skip preserves the historical rationale.
        TP-12 / TP-74 / TP-136 / TP-137 §B convergence-theater pattern — see
        ``docs/CONVENTIONS.md`` SoT-vs-witness contract section.
        """
        pytest.skip("TP-137 §B — tautological; load carried by upstream regex test")


class TestCorpusIdsAreUnique:
    """A corpus id is hand-numbered, and two unrelated classes shared `055`
    for a day (2026-09-14: the CI approval row and the remove/relocate row)
    -- nothing pinned uniqueness, because the count contracts pin globs. The
    `<n>b` suffix is the one sanctioned collision (`027`/`027b`, `028`/`028b`:
    a second shape filed beside the first, in its own class or the same)."""

    def test_numeric_prefixes_are_unique_except_the_b_variant(self):
        import json
        import re

        rows: dict[str, list[tuple[str, str]]] = {}
        for path in sorted((REPO_ROOT / "bench" / "corpus").glob("BC-[0-9]*.json")):
            m = re.match(r"BC-(\d+)([a-z]?)-", path.name)
            assert m, path.name
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.setdefault(m.group(1), []).append((m.group(2), data.get("class_name", "")))
        collisions = {
            n: members for n, members in rows.items()
            if len(members) > 1 and sorted(s for s, _ in members) != ["", "b"]
        }
        assert collisions == {}, (
            f"corpus ids collide: {collisions}. Renumber to the next free id; only "
            f"a `<n>b` sibling may share a number."
        )
