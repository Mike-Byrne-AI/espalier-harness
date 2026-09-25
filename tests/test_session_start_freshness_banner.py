"""TP-56-B: session_start emits a freshness banner when the state
cache shows critical>0 OR stale>=3. Otherwise silent (or when the
cache is missing / stale / under threshold).
"""
from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path


def _import_session_start():
    """Load the hook module fresh with the correct sys.path discipline."""
    hooks_dir = Path(__file__).parent.parent / "tools" / "cc" / "hooks"
    tools_cc_dir = Path(__file__).parent.parent / "tools" / "cc"
    sys.path.insert(0, str(hooks_dir))
    sys.path.insert(0, str(tools_cc_dir))
    if "session_start" in sys.modules:
        del sys.modules["session_start"]
    import session_start  # type: ignore[import-not-found]
    return session_start


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


class TestSessionStartFreshnessBanner:
    def test_banner_emitted_when_critical_present(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 5, "stale": 0, "critical": 1, "unpinned": 0},
            critical=[{"id": "x", "source": "a.md:1", "reason": "drift"}],
        )
        session_start = _import_session_start()
        err = io.StringIO()
        with redirect_stderr(err):
            session_start._report_freshness(repo)
        assert "[freshness]" in err.getvalue()
        assert "1 critical" in err.getvalue()

    def test_banner_emitted_when_stale_three_or_more(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 5, "stale": 3, "critical": 0, "unpinned": 0},
            stale=[
                {"id": "a", "source": "x.md:1", "reason": "drift"},
                {"id": "b", "source": "y.md:1", "reason": "drift"},
                {"id": "c", "source": "z.md:1", "reason": "drift"},
            ],
        )
        session_start = _import_session_start()
        err = io.StringIO()
        with redirect_stderr(err):
            session_start._report_freshness(repo)
        assert "[freshness]" in err.getvalue()
        assert "3 stale" in err.getvalue()

    def test_no_banner_when_stale_under_threshold(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 5, "stale": 2, "critical": 0, "unpinned": 0},
            stale=[
                {"id": "a", "source": "x.md:1", "reason": "drift"},
                {"id": "b", "source": "y.md:1", "reason": "drift"},
            ],
        )
        session_start = _import_session_start()
        err = io.StringIO()
        with redirect_stderr(err):
            session_start._report_freshness(repo)
        assert err.getvalue() == ""

    def test_no_banner_when_state_cache_stale(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _write_cache(
            repo,
            counts={"fresh": 0, "stale": 0, "critical": 5, "unpinned": 0},
            critical=[{"id": "z", "source": "a.md:1", "reason": "drift"}],
            sha="0" * 40,  # mismatched -> cache classifies as stale
        )
        session_start = _import_session_start()
        err = io.StringIO()
        with redirect_stderr(err):
            session_start._report_freshness(repo)
        assert err.getvalue() == ""
