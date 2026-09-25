"""289-F: schema/self-consistency contract over every bench/corpus/BC-*.json.

The corpus is the benchmark's source of truth and a public shipping surface.
Its self-consistency was previously only manually reviewed; a malformed row
(missing key, id/filename drift, an ``expected_outcome`` typo, an ``in_scope``
flag that disagrees with the ``BC-OOS-*`` naming convention) could ship and
silently skew the scored counts. This mechanizes the check.

Calibrated against the live corpus (53 files, 168 attempts): every file carries
all six required keys, ``id`` always equals the filename stem, ``in_scope`` is
exactly ``"OOS" not in stem``, and every attempt's ``expected_outcome`` is one of
``{blocked, allowed, not_blocked_documented_oos}`` — so this contract is 0-FP on
HEAD. The validator is factored out so a malformed input can be rejected in a
unit test without polluting the real corpus (the earn-the-red).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "bench" / "corpus"

_REQUIRED_TOP_KEYS = frozenset({
    "id", "class_name", "description", "in_scope", "documented_in",
    "canonical_attempts",
})
_OUTCOMES = frozenset({"blocked", "allowed", "not_blocked_documented_oos"})
_CORPUS_FILES = sorted(CORPUS_DIR.glob("BC-*.json"))


def _validate(obj: dict, stem: str) -> None:
    """Raise AssertionError on any corpus self-consistency violation."""
    missing = _REQUIRED_TOP_KEYS - set(obj)
    assert not missing, f"{stem}: missing required top-level keys {sorted(missing)}"
    assert obj["id"] == stem, f"{stem}: id {obj['id']!r} != filename stem {stem!r}"
    assert obj["in_scope"] == ("OOS" not in stem), (
        f"{stem}: in_scope={obj['in_scope']!r} disagrees with BC-OOS-* naming "
        f"(OOS files must be in_scope=false, in-scope files true)"
    )
    attempts = obj["canonical_attempts"]
    assert isinstance(attempts, list) and attempts, (
        f"{stem}: canonical_attempts must be a non-empty list"
    )
    for a in attempts:
        aid = a.get("attempt_id")
        assert aid, f"{stem}: an attempt is missing attempt_id"
        assert a.get("expected_outcome") in _OUTCOMES, (
            f"{stem}: attempt {aid!r} expected_outcome="
            f"{a.get('expected_outcome')!r} not in {sorted(_OUTCOMES)}"
        )


class TestBenchCorpusSchema:
    def test_the_readme_class_count_is_the_corpus(self) -> None:
        """README's class-count sentence states the number of in-scope and
        out-of-scope classes; both are DERIVED here from the directory, and
        this test IS the check. Hand-kept until 2026-09-15, and stale twice in
        two lanes (52 against 53 files after BC-057 landed; the same miss a
        lane earlier), with `espalier doctor`'s doc-drift check opt-in and the
        freshness fragment verify-on-touch over a directory an untracked file
        never touches -- so nothing on the default path said so. That
        fragment was retired on 2026-09-19 (its pin had fallen two classes
        behind the sentence): a manual re-pin beside a derived check only
        adds a step that can lag."""
        import json
        import re

        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        m = re.search(
            r"Tested against (\d+) in-scope bypass classes "
            r"\(plus (\d+) documented\s+out-of-scope cases",
            text,
        )
        assert m, "README lost its bypass-class-count sentence"
        in_scope = sum(
            1 for p in _CORPUS_FILES
            if json.loads(p.read_text(encoding="utf-8")).get("in_scope") is True
        )
        oos = sum(1 for p in _CORPUS_FILES if p.name.startswith("BC-OOS-"))
        assert (int(m.group(1)), int(m.group(2))) == (in_scope, oos), (
            f"README says {m.group(1)} in-scope / {m.group(2)} out-of-scope; "
            f"bench/corpus/ holds {in_scope} / {oos} -- fix the sentence"
        )

    @pytest.mark.parametrize("corpus_path", _CORPUS_FILES, ids=lambda p: p.name)
    def test_corpus_file_is_wellformed(self, corpus_path: Path) -> None:
        if not _CORPUS_FILES:
            pytest.skip("no BC-*.json in corpus — not a dev tree / fresh clone")
        obj = json.loads(corpus_path.read_text(encoding="utf-8"))
        _validate(obj, corpus_path.stem)

    def test_ids_and_attempt_ids_are_unique(self) -> None:
        if not _CORPUS_FILES:
            pytest.skip("no BC-*.json in corpus — not a dev tree / fresh clone")
        ids: list[str] = []
        attempt_ids: list[str] = []
        for p in _CORPUS_FILES:
            obj = json.loads(p.read_text(encoding="utf-8"))
            ids.append(obj["id"])
            attempt_ids += [a.get("attempt_id") for a in obj["canonical_attempts"]]
        dup_ids = sorted({x for x in ids if ids.count(x) > 1})
        assert not dup_ids, f"duplicate corpus id(s): {dup_ids}"
        dup_attempts = sorted({x for x in attempt_ids if attempt_ids.count(x) > 1})
        assert not dup_attempts, f"duplicate attempt_id(s): {dup_attempts}"

    def test_validator_rejects_malformed_corpus(self) -> None:
        """Earn-the-red: the validator has teeth. A well-formed object passes;
        each distinct malformation raises."""
        good = {
            "id": "BC-999-synthetic",
            "class_name": "Synthetic",
            "description": "x",
            "in_scope": True,
            "documented_in": "tests/test_x.py::TestX",
            "canonical_attempts": [
                {"attempt_id": "BC-999-a1", "expected_outcome": "blocked"},
            ],
        }
        _validate(good, "BC-999-synthetic")  # no raise

        with pytest.raises(AssertionError):  # bad expected_outcome
            bad = json.loads(json.dumps(good))
            bad["canonical_attempts"][0]["expected_outcome"] = "nonsense"
            _validate(bad, "BC-999-synthetic")

        with pytest.raises(AssertionError):  # missing required key
            bad = {k: v for k, v in good.items() if k != "documented_in"}
            _validate(bad, "BC-999-synthetic")

        with pytest.raises(AssertionError):  # id != stem
            _validate(good, "BC-998-wrong-stem")

        with pytest.raises(AssertionError):  # in_scope disagrees with OOS naming
            oos = json.loads(json.dumps(good))
            oos["id"] = "BC-OOS-999-synthetic"
            _validate(oos, "BC-OOS-999-synthetic")  # in_scope True but OOS name
