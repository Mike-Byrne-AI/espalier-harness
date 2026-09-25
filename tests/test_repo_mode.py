"""TP-59 BC-035: strengthened self-host detection requires 3 signals.

Without the pin, a user repo named ``espalier-harness`` with empty
``espalier/`` and ``tools/cc/`` stubs would acquire the elevated harness
posture (espalier/ added to write_guard's protected prefixes, etc.).
The pin forces a spoofer to ship the actual write_guard.py prefix.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from espalier import surface_contract as sc
from espalier._self_host_fingerprint import (
    WRITE_GUARD_PREFIX_BYTES,
    WRITE_GUARD_PREFIX_SHA256,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSelfHostFingerprintStrength:
    """Three-signal self-host detection: name + bench + write_guard pin."""

    def test_live_repo_classifies_as_self_host(self):
        """Sanity: the actual repo (which ships the pin) must still
        register as self-host. If this fails, the pin has drifted from
        the live write_guard.py and needs `espalier _refresh-self-host-pin`."""
        assert sc.is_self_host_repo(REPO_ROOT) is True

    def test_pin_matches_live_write_guard_prefix(self):
        """The pinned hash must equal the SHA-256 of the current
        write_guard.py's first 200 bytes. Drift here means the pin
        is stale and self-host detection is broken on this repo."""
        write_guard = REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py"
        prefix = write_guard.read_bytes()[:WRITE_GUARD_PREFIX_BYTES]
        actual = hashlib.sha256(prefix).hexdigest()
        assert actual == WRITE_GUARD_PREFIX_SHA256, (
            f"pin drift: live write_guard.py prefix hashes to {actual!r} "
            f"but _self_host_fingerprint.py pins {WRITE_GUARD_PREFIX_SHA256!r}. "
            f"Run `espalier _refresh-self-host-pin` to update the pin."
        )

    def test_missing_bench_rejects_self_host(self, tmp_path):
        """Pre-fix: name+layout alone was enough. Post-fix: missing
        bench/ disqualifies a candidate."""
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8",
        )
        # bench/ absent
        assert sc.is_self_host_repo(tmp_path) is False

    def test_missing_pin_match_rejects_self_host(self, tmp_path):
        """A spoofer with the right name + layout + bench/ but a
        write_guard.py whose first 200 bytes don't match the pin must
        NOT classify as self-host."""
        (tmp_path / "espalier").mkdir()
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "write_guard.py").write_text(
            "# spoofed write_guard\n" + "x" * 300, encoding="utf-8",
        )
        (tmp_path / "bench").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8",
        )
        assert sc.is_self_host_repo(tmp_path) is False

    def test_missing_write_guard_rejects_self_host(self, tmp_path):
        """No write_guard.py at all -> pin check fails -> reject."""
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "bench").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8",
        )
        assert sc.is_self_host_repo(tmp_path) is False

    def test_matching_pin_in_synthetic_repo_accepts_self_host(self, tmp_path):
        """If a synthetic repo copies the live write_guard.py prefix
        verbatim, it should be accepted (this is the documented
        spoofing path -- the pin is not a cryptographic boundary, it
        is a supply-chain friction)."""
        (tmp_path / "espalier").mkdir()
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True)
        live_prefix = (REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_bytes()
        (hooks_dir / "write_guard.py").write_bytes(live_prefix)
        (tmp_path / "bench").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8",
        )
        assert sc.is_self_host_repo(tmp_path) is True


class TestRefreshSelfHostPinCLI:
    """The hidden ``espalier _refresh-self-host-pin`` subcommand rewrites
    the constant in ``espalier/_self_host_fingerprint.py``."""

    def test_subcommand_registered(self):
        from espalier.cli import build_parser
        parser = build_parser()
        # argparse subparser names are stored on the SubParsersAction;
        # walk parser._actions to find it.
        for action in parser._actions:
            if hasattr(action, "choices") and action.choices:
                if "_refresh-self-host-pin" in action.choices:
                    return
        pytest.fail("_refresh-self-host-pin subcommand not registered")

    def test_refresh_rewrites_pin(self, tmp_path):
        from espalier.cli import cmd_refresh_self_host_pin
        import argparse as _argparse

        # Synthesize a minimal repo carrying EVERY pin file the verb must
        # rewrite, derived from SELF_HOST_PIN_CARRIERS rather than listed
        # here -- a fixture that builds a subset is how this test kept
        # passing while the verb refreshed only one of three carriers.
        from espalier.cli import SELF_HOST_PIN_CARRIERS

        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True)
        stub_prefix = b"# synthetic write_guard\n" + b"y" * 300
        (hooks_dir / "write_guard.py").write_bytes(stub_prefix)

        pin_files = []
        for rel in SELF_HOST_PIN_CARRIERS:
            pin_file = tmp_path / rel
            pin_file.parent.mkdir(parents=True, exist_ok=True)
            if "ci_guard" in rel:
                # ci_guard's real shape: a distinct constant name and the
                # parenthesized literal black produces for it. Reproduced so
                # the substitution is proven against BOTH spellings in use,
                # not just the plain one.
                pin_file.write_text(
                    "_CI_WRITE_GUARD_PREFIX_SHA256 = (\n"
                    '    "deadbeef"\n'
                    ")\n"
                    "_CI_WRITE_GUARD_PREFIX_BYTES = 200\n",
                    encoding="utf-8",
                )
            else:
                pin_file.write_text(
                    'WRITE_GUARD_PREFIX_SHA256 = "deadbeef"\n'
                    'WRITE_GUARD_PREFIX_BYTES = 200\n',
                    encoding="utf-8",
                )
            pin_files.append(pin_file)

        ns = _argparse.Namespace(repo=str(tmp_path))
        rc = cmd_refresh_self_host_pin(ns)
        assert rc == 0

        expected = hashlib.sha256(stub_prefix[:WRITE_GUARD_PREFIX_BYTES]).hexdigest()
        for pin_file in pin_files:
            new_text = pin_file.read_text(encoding="utf-8")
            assert expected in new_text, (
                f"{pin_file.name} was not refreshed — a carrier the verb "
                "misses goes stale silently and flips is_self_host_repo() "
                "to False on the real repo"
            )
            assert "deadbeef" not in new_text

    def test_a_missing_carrier_aborts_without_writing_the_others(self, tmp_path):
        """A partial refresh is the state this verb exists to prevent.

        If any carrier is absent, nothing is written at all — otherwise the
        remedy for a stale pin would itself produce a half-updated tree,
        which is the exact failure it is supposed to repair.
        """
        from espalier.cli import SELF_HOST_PIN_CARRIERS, cmd_refresh_self_host_pin
        import argparse as _argparse

        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "write_guard.py").write_bytes(b"# synthetic\n" + b"z" * 300)

        # Build every carrier EXCEPT the last one.
        present = []
        for rel in SELF_HOST_PIN_CARRIERS[:-1]:
            pin_file = tmp_path / rel
            pin_file.parent.mkdir(parents=True, exist_ok=True)
            pin_file.write_text(
                'WRITE_GUARD_PREFIX_SHA256 = "deadbeef"\n', encoding="utf-8"
            )
            present.append(pin_file)

        rc = cmd_refresh_self_host_pin(_argparse.Namespace(repo=str(tmp_path)))
        assert rc == 2
        for pin_file in present:
            assert "deadbeef" in pin_file.read_text(encoding="utf-8"), (
                f"{pin_file.name} was rewritten even though another carrier "
                "was missing — the refresh is not all-or-nothing"
            )


class TestRuntimeMarkerBinding:
    """TP-192 M1: a committed ``.espalier/`` artifact (``freshness.json``,
    git-tracked since TP-189) made the ``.espalier`` DIRECTORY a runtime
    marker, so the self-host repo's own fresh ``git clone`` (and any adopter
    who commits ``.espalier/``) misclassified as ``initialized_*`` instead of
    ``source_checkout`` — masked only by undocumented CI flags
    (``release.yml --mode source-checkout`` / ``test.yml --skip-self-host``).
    A runtime marker must bind to a per-install artifact that no project commits
    (``.espalier/integrity.json``, gitignored)."""

    def test_fresh_self_host_clone_is_source_checkout(self, tmp_path):
        from espalier.repo_mode import REPO_MODE_SOURCE_CHECKOUT, detect_repo_mode

        # Mirror a fresh clone's TRACKED set: committed harness surface + the
        # committed .espalier/freshness.json — but NO gitignored/untracked
        # runtime artifacts (integrity.json / settings.json / fingerprint.json).
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "COMMANDS.md").write_text("# cmds\n", encoding="utf-8")
        (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# live\n", encoding="utf-8")
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("\n", encoding="utf-8")
        (tmp_path / ".espalier").mkdir()
        (tmp_path / ".espalier" / "freshness.json").write_text("{}", encoding="utf-8")

        # Earn-the-red: pre-fix the `.espalier` dir marker → initialized_*.
        assert detect_repo_mode(tmp_path) == REPO_MODE_SOURCE_CHECKOUT

    def test_initialized_repo_still_detected(self, tmp_path):
        """Negative control: a genuinely initialized repo (the per-install
        ``.espalier/integrity.json`` present on disk) still classifies
        ``initialized_*`` — the marker swap must not break the real init path."""
        from espalier.repo_mode import REPO_MODE_SOURCE_CHECKOUT, detect_repo_mode

        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "COMMANDS.md").write_text("# cmds\n", encoding="utf-8")
        (tmp_path / ".espalier").mkdir()
        (tmp_path / ".espalier" / "integrity.json").write_text("{}", encoding="utf-8")

        assert detect_repo_mode(tmp_path) != REPO_MODE_SOURCE_CHECKOUT


class TestFilesystemFallbackPrunesReleaseExcluded:
    """The non-git filesystem fallback must not surface release-excluded
    runtime state (.espalier-state/, *.egg-info/, reports/, ...) as a tracked
    file. On a source archive / sdist an extract + install + test cycle creates
    that state in place; ``git ls-files`` (tracked-only) never lists it, so the
    fallback must match — otherwise the release-noise / provenance / codename
    checks fail on a fresh extract for a benign reason (a masking failure had
    hidden this: the archive-stage pytest timeout aborted before it surfaced).
    """

    def test_runtime_state_pruned_shipped_file_kept(self, tmp_path):
        from espalier.repo_mode import (
            list_repo_files_via_filesystem,
            list_tracked_or_walked_files,
        )
        # A shipped source file + release-excluded runtime state; NO .git.
        (tmp_path / "espalier").mkdir()
        (tmp_path / "espalier" / "cli.py").write_text("x\n", encoding="utf-8")
        state = tmp_path / ".espalier-state"
        state.mkdir()
        (state / "reinject_count").write_text("3\n", encoding="utf-8")

        raw = list_repo_files_via_filesystem(tmp_path)
        files, source = list_tracked_or_walked_files(tmp_path)

        assert source == "filesystem"  # no .git -> the fallback path
        # Earn-the-red: the raw walk (what the wrapper used to return directly)
        # DOES surface the runtime state ...
        assert ".espalier-state/reinject_count" in raw, (
            "precondition: the raw walk should still surface the runtime state; "
            "if this fails, .espalier-state joined _WALK_SKIP_DIRS and this test "
            "needs a different release-excluded fixture"
        )
        # ... and the git-faithful wrapper prunes it while keeping the shipped
        # file. Revert the prune and this last assertion goes red.
        assert "espalier/cli.py" in files
        assert ".espalier-state/reinject_count" not in files


class TestGitPrintsANameTheDecoderRefuses:
    """Ledger DEF-821. ``list_tracked_or_walked_files`` runs ``git -c
    core.quotePath=false ls-files`` -- raw bytes, by its own choice, so the git
    and filesystem branches agree on non-ASCII names -- and decoded them
    strictly under a handler that caught only ``FileNotFoundError`` and
    ``TimeoutExpired``. A tracked filename git prints in a non-UTF-8 encoding
    (a latin-1 name from an old checkout on ext4) is a legitimate repository
    state, and it ended ``doctor``, ``audit`` and ``init`` in a traceback.

    The oracle is a ``git`` on PATH that prints such a name: the decode is
    what is under test, not the filesystem (APFS refuses to create the name,
    so a real file could not earn this red on the self-host box). Skips where
    ``sh`` is absent; unverified on Windows."""

    @staticmethod
    def _shim_git(tmp_path, monkeypatch, terminator: str) -> Path:
        import os
        import shutil
        if os.name == "nt" or shutil.which("sh") is None:
            pytest.skip("the git shim is a /bin/sh script")
        bindir = tmp_path / "bin"
        bindir.mkdir()
        shim = bindir / "git"
        # \351 is 0xE9: 'é' in latin-1, an invalid lone continuation in UTF-8.
        shim.write_text(f"#!/bin/sh\nprintf 'caf\\351.txt{terminator}'\n", encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        return repo

    def test_a_non_utf8_tracked_name_is_a_verdict_not_a_traceback(self, tmp_path, monkeypatch):
        from espalier.repo_mode import list_tracked_or_walked_files
        repo = self._shim_git(tmp_path, monkeypatch, "\\n")
        files, source = list_tracked_or_walked_files(repo)
        assert source == "git"
        assert files == ["caf�.txt"], files
