"""TP-56-B: statusline appends a freshness segment when the state
cache has critical or stale entries.

Pins the suppression-vs-emission rules: the segment is suppressed
for all-fresh OR when the cache itself is missing/stale (no
signal beats a misleading one). Without this contract a regression
could silently always-emit the freshness chip even when the cache
is unreliable, conditioning the operator to ignore the signal so
the actual stale-fragment warnings get lost in noise.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _import_statusline():
    tools_cc_dir = Path(__file__).parent.parent / "tools" / "cc"
    sys.path.insert(0, str(tools_cc_dir))
    if "statusline" in sys.modules:
        del sys.modules["statusline"]
    import statusline  # type: ignore[import-not-found]
    return statusline


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-q"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True, capture_output=True,
    )
    return repo


def _head_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _write_cache(
    repo: Path,
    *,
    counts: dict[str, int],
    critical: list[dict] | None = None,
    stale: list[dict] | None = None,
    sha: str | None = None,
) -> None:
    from espalier.freshness import update_state_cache
    update_state_cache(
        repo,
        counts=counts,
        critical=critical or [],
        stale=stale or [],
        computed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        computed_at_sha=sha or _head_sha(repo),
    )


class TestStatuslineFreshnessSegment:
    def test_critical_segment_appended(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 8, "stale": 0, "critical": 2, "unpinned": 0},
            critical=[
                {"id": "x", "source": "a.md:1", "reason": "drift"},
                {"id": "y", "source": "b.md:1", "reason": "drift"},
            ],
        )
        statusline = _import_statusline()
        seg = statusline._freshness_summary(repo)
        assert seg == "fresh:8 crit:2"

    def test_stale_segment_appended_when_no_critical(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 10, "stale": 3, "critical": 0, "unpinned": 0},
            stale=[
                {"id": "a", "source": "x.md:1", "reason": "drift"},
                {"id": "b", "source": "y.md:1", "reason": "drift"},
                {"id": "c", "source": "z.md:1", "reason": "drift"},
            ],
        )
        statusline = _import_statusline()
        seg = statusline._freshness_summary(repo)
        assert seg == "fresh:10 stale:3"

    def test_no_segment_when_all_fresh(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 5, "stale": 0, "critical": 0, "unpinned": 0},
        )
        statusline = _import_statusline()
        assert statusline._freshness_summary(repo) is None

    def test_no_segment_when_state_cache_stale(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 0, "stale": 0, "critical": 5, "unpinned": 0},
            critical=[{"id": "z", "source": "a.md:1", "reason": "drift"}],
            sha="0" * 40,
        )
        statusline = _import_statusline()
        assert statusline._freshness_summary(repo) is None

    def test_non_dict_counts_does_not_crash(self, tmp_path: Path) -> None:
        """TP-174a R62: a present-but-non-dict 'counts' must degrade (coerced to
        {}, segment None) instead of raising AttributeError on counts.get()."""
        import json
        repo = _init_repo(tmp_path)
        _write_cache(repo, counts={"fresh": 5, "stale": 0, "critical": 0, "unpinned": 0})
        # TP-329: the cache is its own gitignored file (whole body IS the cache).
        cache_file = repo / ".espalier" / ".freshness_state_cache.json"
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["counts"] = ["not", "a", "dict"]  # corrupt subfield
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        statusline = _import_statusline()
        assert statusline._freshness_summary(repo) is None  # no AttributeError

    def test_one_failing_indicator_does_not_blank_others(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """TP-174a R54: a single failing indicator must degrade only itself —
        the healthy segments still render. Pre-fix the whole line reset to the
        bare 'espalier' header on any segment failure."""
        repo = _init_repo(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        statusline = _import_statusline()
        monkeypatch.setattr(statusline, "_maintenance_indicator", lambda: "MAINT=1")

        def _boom(*_a):
            raise RuntimeError("indicator exploded")

        monkeypatch.setattr(statusline, "_freshness_summary", _boom)
        rc = statusline.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "MAINT=1" in out  # healthy indicator survived the failure
        assert "espalier" in out
