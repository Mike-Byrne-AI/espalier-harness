"""Asserts the two state-cache readers (espalier vs tools/cc)
return identical dicts on the same fixture manifest.

The two copies exist because ``tools/cc/`` must have zero
espalier imports per the architecture rule. This test prevents
the implementations from silently diverging.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


class TestCacheReaderParity:
    def test_espalier_and_tools_cc_readers_agree(
        self, tmp_path: Path
    ) -> None:
        from espalier.freshness import (
            read_state_cache_safe as espalier_reader,
            update_state_cache,
        )
        sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "cc"))
        try:
            from _freshness_cache import (  # type: ignore[import-not-found]
                _read_state_cache_safe as tools_cc_reader,
            )
        finally:
            sys.path.pop(0)

        repo = tmp_path / "repo"
        (repo / ".espalier").mkdir(parents=True)
        (repo / ".espalier" / "freshness.json").write_text(
            json.dumps({"schema_version": 1, "fragments": {}}),
            encoding="utf-8",
        )
        update_state_cache(
            repo,
            counts={"fresh": 3, "stale": 0, "critical": 0, "unpinned": 0},
            critical=[],
            stale=[],
            computed_at="2026-05-17T12:00:00Z",
            computed_at_sha="c" * 40,
        )
        assert espalier_reader(repo) == tools_cc_reader(repo)

    def test_readers_agree_on_non_dict_counts(self, tmp_path: Path) -> None:
        """TP-174a R62: both readers must coerce a present-but-non-dict 'counts'
        to {} identically — the verbatim-mirror invariant. Pre-fix the espalier
        reader returned the raw corrupted value while the tools/cc reader
        coerced it, so the two diverged on the same fixture."""
        import json
        from espalier.freshness import read_state_cache_safe as espalier_reader
        sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "cc"))
        try:
            from _freshness_cache import (  # type: ignore[import-not-found]
                _read_state_cache_safe as tools_cc_reader,
            )
        finally:
            sys.path.pop(0)

        repo = tmp_path / "repo"
        (repo / ".espalier").mkdir(parents=True)
        # TP-329: the per-install cache file's whole body IS the cache object
        # (no `state_cache` wrapper); write it directly to the relocated path.
        (repo / ".espalier" / ".freshness_state_cache.json").write_text(
            json.dumps({
                "computed_at": "2026-05-17T12:00:00Z",
                "computed_at_sha": "c" * 40,
                "counts": ["not", "a", "dict"],  # corrupt subfield
            }),
            encoding="utf-8",
        )
        e = espalier_reader(repo)
        t = tools_cc_reader(repo)
        assert e == t, f"reader divergence on non-dict counts: espalier={e} tools_cc={t}"
        assert e["counts"] == {}  # both coerced

    def test_pinned_bound_paths_agree_on_symbol_and_malformed_bounds(
        self, tmp_path: Path
    ) -> None:
        """TP-174a: the two _pinned_bound_paths copies must agree on the
        `::symbol`-suffix strip, the git-pathspec dash guard, and a non-list
        (string) bound. The pre-fix tools/cc mirror added bounds verbatim and
        char-iterated a string bound, diverging from the espalier copy."""
        from espalier.freshness import _pinned_bound_paths as espalier_paths
        sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "cc"))
        try:
            from _freshness_cache import (  # type: ignore[import-not-found]
                _pinned_bound_paths as tools_cc_paths,
            )
        finally:
            sys.path.pop(0)

        repo = tmp_path / "repo"
        (repo / ".espalier").mkdir(parents=True)
        (repo / ".espalier" / "freshness.json").write_text(
            json.dumps({
                "schema_version": 1,
                "fragments": {
                    "f1": {"bound": ["espalier/cli.py::DENIED_PATTERNS"]},
                    "f2": {"bound": ["espalier/y.py", "-weird-flag"]},
                    "f3": {"bound": "espalier/typo.py"},  # malformed (string)
                },
            }),
            encoding="utf-8",
        )
        e = espalier_paths(repo)
        t = tools_cc_paths(repo)
        assert e == t, f"reader divergence: espalier={e} tools_cc={t}"
        # ::symbol stripped, dash dropped, string bound ignored (not char-split).
        assert e == ["espalier/cli.py", "espalier/y.py"], e

    def test_staleness_functions_agree(self, tmp_path: Path) -> None:
        """TP-152 152-A: the two staleness predicates must stay in
        lockstep — A-1 (naive-tz guard), A-3 (W17 bound-change), and
        A-4 (SHA length) were applied to both copies. Drive the same
        caches through both and assert identical verdicts."""
        from espalier.freshness import is_state_cache_stale as espalier_stale
        sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "cc"))
        try:
            from _freshness_cache import (  # type: ignore[import-not-found]
                _is_state_cache_stale as tools_cc_stale,
            )
        finally:
            sys.path.pop(0)

        cases = [
            # naive timestamp (A-1): both -> stale
            {"computed_at": "2026-05-17T12:00:00", "computed_at_sha": "0" * 40,
             "counts": {}},
            # aware + missing SHA: both -> stale
            {"computed_at": "2026-05-17T12:00:00Z", "counts": {}},
        ]
        for cache in cases:
            assert (
                espalier_stale(cache, repo_root=tmp_path)
                == tools_cc_stale(cache, repo_root=tmp_path)
            ), f"staleness verdict diverged on {cache!r}"
