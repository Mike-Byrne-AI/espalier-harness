"""TP-179: `espalier fuse` — fusion-repo bootstrap.

Pins the source-of-truth fusion command: host copy + harness overlay into a
NEW repo, both originals untouched, espalier-specific CONTENT reseeded empty,
managed surface owned by init (marked), engine self-contained.

Guards against the two failure modes that make a fusion useless: clobbering
host files (the collision-abort), and leaking espalier's own history/content
(ESPALIER_MEMORY.md, blueprints, TP-packs, conventions) into the host because the
overlay forgot the SYSTEM-vs-CONTENT line.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from espalier import fuse

from tests._symlink_support import requires_symlink


def _make_host(tmp_path: Path, *, with_tools: bool = False) -> Path:
    host = tmp_path / "host"
    (host / "src").mkdir(parents=True)
    (host / "tests").mkdir()
    (host / "src" / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (host / "tests" / "test_app.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    (host / "README.md").write_text("# My App\n", encoding="utf-8")
    (host / "pyproject.toml").write_text('[project]\nname = "my-app"\n', encoding="utf-8")
    if with_tools:
        (host / "tools" / "cc" / "hooks").mkdir(parents=True)
        (host / "tools" / "cc" / "hooks" / "write_guard.py").write_text("# my own\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    subprocess.run(["git", "-C", str(host), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(host), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(host), "-c", "commit.gpgsign=false", "commit", "-qm", "init"], check=True)
    return host


def _make_nonpython_host(tmp_path: Path) -> Path:
    """A committed Node host: no Python file anywhere, so the host-only
    fingerprint init reads yields no ``scan`` action (the DEF-806 stressor)."""
    host = tmp_path / "host"
    (host / "src").mkdir(parents=True)
    (host / "src" / "index.js").write_text("module.exports = (a, b) => a + b;\n", encoding="utf-8")
    (host / "package.json").write_text(
        '{ "name": "demo", "version": "1.0.0", "scripts": { "test": "node --test" } }\n',
        encoding="utf-8",
    )
    (host / "README.md").write_text("# node demo\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(host)], check=True)
    subprocess.run(["git", "-C", str(host), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(host), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(host), "-c", "commit.gpgsign=false", "commit", "-qm", "init"], check=True)
    return host


_GATE_COND = "needs.detect-source.outputs.is_source == 'true'"
_GUARD_COPIES = (
    Path(".github/workflows/harness-guard.yml"),
    Path("espalier/assets/github/workflows/harness-guard.yml"),
)


def _self_host_gated_jobs(workflow: Path) -> set[str]:
    """Job names in ``workflow`` gated on the self-host marker's absence.

    Regex over the ``jobs:`` block rather than a YAML parse — the suite has
    no third-party dep here, and the shape is stable.
    """
    import re as _re

    text = (Path(__file__).resolve().parent.parent / workflow).read_text(
        encoding="utf-8"
    )
    jobs_block = text.split("\njobs:", 1)[1]
    gated: set[str] = set()
    chunks = _re.split(r"\n  (?=[a-zA-Z0-9_-]+:)", jobs_block)
    for chunk in chunks:
        name = _re.match(r"\s*([a-zA-Z0-9_-]+):", chunk)
        if name and _GATE_COND in chunk:
            gated.add(name.group(1))
    return gated


class TestFusionMarkerJobList:
    """TP-398 LANEB-04: the marker ships into every fusion, so its job list
    is a shipped claim. It named three jobs while four were gated —
    ``mypy-hooks`` was added later and the marker was never updated."""

    def test_marker_names_exactly_the_gated_jobs(self):
        gated = _self_host_gated_jobs(_GUARD_COPIES[0])
        assert gated, "no self-host-gated jobs found — gate condition changed?"
        body = fuse._FUSION_MARKER_BODY
        # Strip comment prefixes/newlines so a wrapped list still parses.
        flat = " ".join(line.lstrip("# ").strip() for line in body.splitlines())
        import re as _re

        listed = _re.search(r"CI jobs \(([^)]*)\)", flat)
        assert listed, "marker must name its gated jobs in a parenthetical"
        named = {j.strip() for j in listed.group(1).split(",") if j.strip()}
        assert named == gated, (
            f"fusion marker names {sorted(named)} but harness-guard.yml gates "
            f"{sorted(gated)}. The marker ships into every fusion — update it."
        )

    def test_both_guard_copies_gate_the_same_jobs(self):
        """Family-5 mirror hazard: the packaged asset is what an adopter
        installs, so a divergence there ships even though the root copy is
        what CI runs. Pin them together."""
        root, asset = (_self_host_gated_jobs(p) for p in _GUARD_COPIES)
        assert root == asset, (
            f"harness-guard.yml copies disagree: root gates {sorted(root)}, "
            f"packaged asset gates {sorted(asset)}"
        )


class TestFusePlan:
    def test_plan_lists_host_and_harness_and_no_collision(self, tmp_path):
        host = _make_host(tmp_path)
        plan = fuse.plan_fusion(host, tmp_path / "out")
        assert plan["host_is_git"] is True
        assert "src/app.py" in plan["host_files"]
        assert any(r.startswith("espalier/") for r in plan["harness_files"])
        assert any(r.startswith("tools/cc/") for r in plan["harness_files"])
        assert plan["collisions"] == []

    def test_plan_detects_host_harness_collision(self, tmp_path):
        host = _make_host(tmp_path, with_tools=True)
        plan = fuse.plan_fusion(host, tmp_path / "out")
        assert "tools/cc/hooks/write_guard.py" in plan["collisions"]


class TestFuseGuards:
    def test_refuses_nonempty_out(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        out.mkdir()
        (out / "x").write_text("y", encoding="utf-8")
        with pytest.raises(FileExistsError):
            fuse.fuse_repos(host, out, run_init=False)

    def test_collision_aborts_without_clobber(self, tmp_path):
        host = _make_host(tmp_path, with_tools=True)
        out = tmp_path / "out"
        with pytest.raises(RuntimeError, match="collision"):
            fuse.fuse_repos(host, out, run_init=False)
        # host's own file is untouched (we never wrote into the host)
        assert (host / "tools" / "cc" / "hooks" / "write_guard.py").read_text(encoding="utf-8") == "# my own\n"
        # collision aborts in plan_fusion, BEFORE any write — out is never created
        assert not out.exists()

    def test_dry_run_writes_nothing(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        report = fuse.fuse_repos(host, out, dry_run=True)
        assert report["dry_run"] is True
        assert not out.exists()

    def test_short_host_copy_warns_and_reports_actual(self, tmp_path, capsys):
        """#6 earn-the-red: a tracked-but-absent host file (committed then
        removed from the worktree, or a submodule gitlink) enters
        ``plan['host_files']`` via git-ls-files but is silently skipped by
        ``_copy`` (not a regular file/symlink). The report must show the ACTUAL
        copied count (not the planned count) alongside ``host_files_planned``,
        and a WARN must fire — a fusion that dropped files must never print a
        full count, exit 0, no signal. Pre-fix ``report['host_files']`` was the
        planned count and no WARN fired."""
        host = _make_host(tmp_path)
        ghost = host / "src" / "ghost.py"
        ghost.write_text("# tracked, then deleted from the worktree\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(host), "add", "src/ghost.py"], check=True)
        subprocess.run(["git", "-C", str(host), "commit", "-qm", "add ghost"], check=True)
        ghost.unlink()  # gone from the worktree, still tracked by git

        out = tmp_path / "out"
        report = fuse.fuse_repos(host, out, run_init=False, preserve_history=False)

        planned = report["host_files_planned"]
        assert report["host_files"] == planned - 1, (
            f"host_files should reflect the ACTUAL copy ({planned - 1}), "
            f"got {report['host_files']} (planned={planned})"
        )
        assert not (out / "src" / "ghost.py").exists()
        err = capsys.readouterr().err
        assert "WARN" in err and "INCOMPLETE" in err.upper(), (
            f"expected an INCOMPLETE-copy WARN on stderr; got: {err!r}"
        )


class TestFuseNonGitSource:
    """W1-1: the primary fetcher channel ships espalier as a `git archive` tag
    tarball with NO .git, so `_tracked_files(src)` is None. The overlay must NOT
    be silently empty (which would print 'fusion built' with no engine)."""

    def _fake_src(self, tmp_path: Path) -> Path:
        src = tmp_path / "esp_archive"  # a .git-stripped espalier tree
        (src / "espalier").mkdir(parents=True)
        (src / "espalier" / "cli.py").write_text("x = 1\n", encoding="utf-8")
        (src / "tools" / "cc" / "hooks").mkdir(parents=True)
        (src / "tools" / "cc" / "hooks" / "write_guard.py").write_text("# guard\n", encoding="utf-8")
        # noise that must be skipped even though espalier/ is INCLUDE'd
        (src / "espalier" / "__pycache__").mkdir()
        (src / "espalier" / "__pycache__" / "cli.pyc").write_text("junk", encoding="utf-8")
        (src / "reports").mkdir()
        (src / "reports" / "x.json").write_text("{}", encoding="utf-8")
        return src

    def test_nongit_source_overlay_not_empty(self, tmp_path, monkeypatch):
        host = _make_host(tmp_path)
        src = self._fake_src(tmp_path)
        monkeypatch.setattr(fuse, "_espalier_source_root", lambda: src)
        plan = fuse.plan_fusion(host, tmp_path / "out")
        assert plan["harness_files"], "non-git source overlaid 0 files (W1-1 regression)"
        assert "espalier/cli.py" in plan["harness_files"]
        assert "tools/cc/hooks/write_guard.py" in plan["harness_files"]
        # noise dirs skipped even under an INCLUDE'd prefix
        assert not any("__pycache__" in r for r in plan["harness_files"])
        assert not any(r.startswith("reports/") for r in plan["harness_files"])

    def test_nongit_source_files_helper_skips_noise(self, tmp_path):
        src = self._fake_src(tmp_path)
        files = fuse._nongit_source_files(src)
        assert "espalier/cli.py" in files
        assert "tools/cc/hooks/write_guard.py" in files
        assert not any("__pycache__" in f or f.startswith("reports/") for f in files)


class TestFuseRequiresSourceCheckout:
    """PKG-01: `fuse` under a NON-EDITABLE (wheel) install.

    `_espalier_source_root()` is `Path(__file__).parent.parent`, which under a
    wheel is `site-packages/` — where only `espalier/` resolves, because the
    harness payload ships at REMAPPED paths (`espalier/_vendor/cc/`,
    `espalier/assets/...`). The overlay plan therefore could never contain a
    file `init` also deploys, `harness_via_init` was pinned at 0 by
    construction, and `fuse` exited 1 blaming init — which had succeeded —
    AFTER leaving a half-built fusion on disk.

    Operator decision (2026-08-03): refuse accurately rather than teach `fuse`
    the remapped layout. A refusal is honest today; making it work has a
    29/31 ceiling until the shipped-asset drift (DEF-399a) is closed.
    """

    def _wheel_like_src(self, tmp_path: Path) -> Path:
        """site-packages/: espalier/ resolves, nothing else in the manifest does.

        Built once per test and reused — fuse_repos resolves the source root
        and then plan_fusion resolves it again, so a fixture that rebuilds on
        every call raises FileExistsError on the second resolve.
        """
        src = tmp_path / "site-packages"
        if not src.exists():
            (src / "espalier" / "_vendor" / "cc").mkdir(parents=True)
            (src / "espalier" / "cli.py").write_text("x = 1\n", encoding="utf-8")
            (src / "espalier" / "assets" / "docs").mkdir(parents=True)
        return src

    def test_wheel_install_refuses_before_any_work(self, tmp_path, monkeypatch):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        src = self._wheel_like_src(tmp_path)
        monkeypatch.setattr(fuse, "_espalier_source_root", lambda: src)
        with pytest.raises(ValueError) as exc:
            fuse.fuse_repos(host, out)
        assert "SOURCE CHECKOUT" in str(exc.value)
        # The whole point of refusing over failing: nothing is left behind.
        assert not out.exists(), (
            "fuse must refuse BEFORE doing any work — a half-built fusion on "
            "disk is what made the old failure worse than a clean refusal"
        )

    def test_refusal_names_the_unsupported_mode_and_the_alternative(
        self, tmp_path, monkeypatch
    ):
        """An accurate refusal has to be actionable, not just non-zero."""
        monkeypatch.setattr(
            fuse, "_espalier_source_root", lambda: self._wheel_like_src(tmp_path)
        )
        with pytest.raises(ValueError) as exc:
            fuse.plan_fusion(_make_host(tmp_path), tmp_path / "out")
        msg = str(exc.value)
        assert "wheel" in msg                      # names the mode it refuses
        assert "pip install -e ." in msg           # names the supported one
        assert "init" in msg                       # says what still works

    def test_source_checkout_is_not_refused(self, tmp_path, monkeypatch):
        """Negative control: the supported mode must plan exactly as before.

        Without this, the refusal could be over-broad and nothing would say so
        — every other fuse test would still pass on a refusal that never fires
        in CI because CI runs from a checkout.
        """
        src = tmp_path / "checkout"
        (src / "espalier").mkdir(parents=True)
        (src / "espalier" / "cli.py").write_text("x = 1\n", encoding="utf-8")
        (src / "tools" / "cc").mkdir(parents=True)
        (src / "tools" / "cc" / "x.py").write_text("# x\n", encoding="utf-8")
        monkeypatch.setattr(fuse, "_espalier_source_root", lambda: src)
        plan = fuse.plan_fusion(_make_host(tmp_path), tmp_path / "out")
        assert plan["harness_files"]

    def test_missing_source_entries_reports_the_real_gap(self, tmp_path):
        """The count in the refusal must be measured, not asserted."""
        src = self._wheel_like_src(tmp_path)
        missing = fuse.missing_source_entries(src)
        assert "tools/" in missing
        assert "bench/corpus/" in missing
        assert "espalier/" not in missing, "espalier/ is the one entry a wheel DOES carry"


class TestFuseOverlaySummaryIsDerived:
    """PKG-01 second half: the overlay summary named four fixed categories.

    `(engine, bench, docs, workflows)` was a hardcoded literal, printed no
    matter what the copy loop wrote. Under a wheel it read
    `188 overlaid (engine, bench, docs, workflows)` when the total was exactly
    the `espalier/` file count — one category, four names. It is also wrong in
    the SUPPORTED mode: `.claude/workflows/` is `_should_overlay=False` so it
    contributes nothing, while `scripts/` and `tools/` contribute and were
    never named.
    """

    def test_categories_name_only_what_contributed(self):
        cats = fuse._overlay_categories([
            "espalier/cli.py", "espalier/fuse.py",
            "tools/cc/hooks/write_guard.py",
            "docs/HOOKS.md",
        ])
        assert cats == ["docs", "engine", "tools"]
        assert "bench" not in cats, "a category that contributed nothing was named"
        assert "workflows" not in cats

    def test_empty_overlay_says_nothing_not_four_categories(self):
        assert fuse._overlay_categories([]) == []

    def test_unknown_top_level_is_named_after_itself(self):
        """A new fusion-manifest root must appear, not silently vanish.

        The alias map is for readability only; anything absent from it falls
        back to its own path segment. A mapping that DROPPED unknown roots
        would reintroduce the original defect one manifest edit later.
        """
        assert fuse._overlay_categories(["brand_new_root/x.py"]) == ["brand_new_root"]

    def test_printed_summary_uses_the_reports_categories(
        self, tmp_path, monkeypatch, capsys
    ):
        """The PRINT path must read the report, not a literal.

        Every other test here exercises _overlay_categories directly, so all
        of them stay green if someone reverts the summary line to the
        hardcoded four names while leaving the helper in place. This drives
        cmd_fuse and reads the bytes the operator actually sees.
        """
        out = tmp_path / "f"
        out.mkdir()
        (out / ".claude").mkdir()
        (out / ".claude" / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "python3",
                 "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]}]}]}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(fuse, "fuse_repos", lambda *a, **k: {
            "dry_run": False, "out": str(out), "host_files": 3,
            "host_is_git": True, "history_preserved": True,
            "harness_overlaid": 7, "harness_via_init": 50, "init_rc": 0,
            "overlay_categories": ["docs", "engine"],
        })
        fuse.cmd_fuse(argparse.Namespace(
            host=str(tmp_path), out=str(out), fresh=False,
            dry_run=False, no_init=False,
        ))
        printed = capsys.readouterr().out
        # Scope the negative to the summary LINE — "bench" legitimately appears
        # in the finish-up checklist prose further down the same output.
        summary = next(ln for ln in printed.splitlines() if "overlaid (" in ln)
        assert "7 overlaid (docs, engine)" in summary
        for absent in ("bench", "workflows"):
            assert absent not in summary, (
                f"the summary named {absent!r}, which the report did not carry "
                "— the hardcoded (engine, bench, docs, workflows) literal is back"
            )


class TestFuseNonGitHost:
    """W1-4: refuse a non-git host. A filesystem walk would carry secrets (.env)
    and silently DROP source under a generic dir name (`src/reports/` — `reports`
    is in _NONGIT_SKIP_DIRS). `git init` first removes both risks."""

    def _raw_host(self, tmp_path: Path) -> Path:
        host = tmp_path / "rawhost"
        (host / "src" / "reports").mkdir(parents=True)
        (host / "src" / "reports" / "real_module.py").write_text("x = 1\n", encoding="utf-8")
        (host / ".env").write_text("SECRET=hunter2\n", encoding="utf-8")
        (host / "main.py").write_text("print('hi')\n", encoding="utf-8")
        return host  # deliberately NOT git-inited

    def test_plan_refuses_nongit_host(self, tmp_path):
        host = self._raw_host(tmp_path)
        with pytest.raises(ValueError, match="not a git repo"):
            fuse.plan_fusion(host, tmp_path / "out")

    def test_fuse_refuses_nongit_host_and_writes_nothing(self, tmp_path):
        host = self._raw_host(tmp_path)
        out = tmp_path / "out"
        with pytest.raises(ValueError, match="not a git repo"):
            fuse.fuse_repos(host, out, run_init=False)
        assert not out.exists()


class TestFuseEmptyTrackedSet:
    """§C21: absence and emptiness are the same answer from `git ls-files`.

    `_tracked_files` returns ``None`` for "not a git repo" and ``[]`` for
    "a git repo that tracks nothing". Both mean *there is no source to copy*,
    and both call sites tested only for ``None`` — so a git-inited host with
    nothing committed built a fusion containing zero of the user's source and
    exited 0 reporting success, and a git-less espalier export extracted under
    a parent git worktree answered ``[]`` (rc 0) so the filesystem fallback
    never fired.
    """

    def _empty_git_host(self, tmp_path: Path) -> Path:
        """A real git repo with real files that have never been committed."""
        host = tmp_path / "emptyhost"
        (host / "src").mkdir(parents=True)
        (host / "src" / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(host)], check=True)
        return host  # git-inited, nothing added or committed

    def test_plan_refuses_git_host_that_tracks_nothing(self, tmp_path):
        """Earn-the-red: pre-fix this returned a plan whose host half was empty."""
        host = self._empty_git_host(tmp_path)
        assert fuse._tracked_files(host) == [], "fixture must produce the empty-not-None shape"
        with pytest.raises(ValueError, match="tracks no files"):
            fuse.plan_fusion(host, tmp_path / "out")

    def test_fuse_refuses_empty_git_host_and_writes_nothing(self, tmp_path):
        host = self._empty_git_host(tmp_path)
        out = tmp_path / "out"
        with pytest.raises(ValueError, match="tracks no files"):
            fuse.fuse_repos(host, out, run_init=False)
        assert not out.exists()

    def test_nongit_source_fallback_fires_on_empty_not_just_none(self, tmp_path, monkeypatch):
        """The SOURCE half: `[]` must reach `_nongit_source_files`, not sail past it.

        Reproduces the extracted-export-under-a-parent-worktree shape without
        needing one: `git ls-files` answers rc 0 with no paths.
        """
        host = _make_host(tmp_path)
        called: list[Path] = []
        real_tracked = fuse._tracked_files  # capture BEFORE patching, or _fake_tracked recurses

        def _fake_tracked(repo: Path):
            return real_tracked(host) if Path(repo) == Path(host) else []

        def _fake_nongit(src: Path):
            called.append(Path(src))
            return ["espalier/__init__.py"]

        monkeypatch.setattr(fuse, "_tracked_files", _fake_tracked)
        monkeypatch.setattr(fuse, "_nongit_source_files", _fake_nongit)
        fuse.plan_fusion(host, tmp_path / "out")
        assert called, (
            "_nongit_source_files was never called for an empty tracked set — "
            "the fallback is gated on `is None` instead of falsiness"
        )


class TestFuseInitFailure:
    """W1-2: a failed init = no settings.json = unwired governance. `cmd_fuse`
    must NOT report 'the harness is live' nor exit 0."""

    def _report(self, out, *, init_rc, via_init):
        return {
            "dry_run": False, "out": str(out), "host_files": 3,
            "host_is_git": True, "history_preserved": True,
            "harness_overlaid": 100, "harness_via_init": via_init, "init_rc": init_rc,
        }

    def _args(self, tmp_path, out):
        return argparse.Namespace(host=str(tmp_path), out=str(out),
                                  fresh=False, dry_run=False, no_init=False)

    def test_nonzero_when_init_returns_error(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "f"
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, init_rc=1, via_init=0))
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        assert rc != 0
        assert "harness is live" not in capsys.readouterr().out.lower()

    def test_nonzero_when_init_wired_nothing(self, tmp_path, monkeypatch, capsys):
        # Defensive branch: init_rc==0 with harness_via_init==0 cannot occur in
        # practice (a successful init always deploys >=32 managed scripts), but the
        # gate must still reject it — this pins that the "is the fusion live?" check
        # is via_init-aware, not init_rc-only, against a future refactor.
        out = tmp_path / "f"
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, init_rc=0, via_init=0))
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        assert rc != 0
        assert "harness is live" not in capsys.readouterr().out.lower()

    @staticmethod
    def _stage_settings(out, *, wired: bool) -> None:
        """Write the fused out/.claude/settings.json the F2 banner check reads."""
        (out / ".claude").mkdir(parents=True, exist_ok=True)
        if wired:
            data = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "python3",
                 "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]}]}]}}
        else:
            data = {"permissions": {"allow": ["Bash(ls:*)"]}}
        (out / ".claude" / "settings.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_success_reports_live(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "f"
        out.mkdir()
        self._stage_settings(out, wired=True)  # init wired the hooks
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, init_rc=0, via_init=50))
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        assert rc == 0
        assert "harness is live" in capsys.readouterr().out.lower()

    def test_live_banner_names_a_dead_reporter(self, tmp_path, monkeypatch, capsys):
        """DEF-619: "live" is a sentence about the gates. A reporter deployed
        on disk but not wired in the fused settings.json is named under it."""
        out = tmp_path / "f"
        out.mkdir()
        self._stage_settings(out, wired=True)  # gates wired, nothing else
        hooks_dir = out / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "post_compact.py").write_text("# deployed\n", encoding="utf-8")
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, init_rc=0, via_init=50))
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        captured = capsys.readouterr().out
        assert rc == 0
        assert "harness is live" in captured.lower()
        assert "NOT wired: post_compact.py is a reporter hook" in captured, captured

    def test_preserved_host_settings_not_reported_live(self, tmp_path, monkeypatch, capsys):
        # B-1 F2: init succeeds (rc 0, assets deployed) but PRESERVED the host's
        # own settings.json, so NO hooks are wired. The banner must NOT re-assert
        # "harness is live" over init's honest WARN — it must point at merge-settings.
        out = tmp_path / "f"
        out.mkdir()
        self._stage_settings(out, wired=False)  # host's own settings.json preserved
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, init_rc=0, via_init=50))
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        captured = capsys.readouterr().out
        assert rc == 0
        assert "harness is live" not in captured.lower(), (
            "fuse re-asserted liveness over a preserved (unwired) settings.json:\n"
            + captured
        )
        assert "merge-settings" in captured, (
            "fuse did not point at the activation command:\n" + captured
        )

    def test_unwired_plus_active_ci_gate_warns_first_pr_will_red(
        self, tmp_path, monkeypatch, capsys
    ):
        # TP-193 R4 (Major ①): when fuse preserves an unwired settings.json AND
        # harness-guard.yml is the active merge-gate, the non-self-host-gated
        # `verify` job reds the fusion's first PR. The banner must say so loudly
        # instead of framing merge-settings as optional finish-up polish.
        out = tmp_path / "f"
        out.mkdir()
        self._stage_settings(out, wired=False)  # host settings preserved, unwired
        monkeypatch.setattr(
            fuse, "fuse_repos",
            lambda *a, **k: {**self._report(out, init_rc=0, via_init=50),
                             "ci_gate_active": True},
        )
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        captured = capsys.readouterr().out.lower()
        assert rc == 0
        assert "will fail your first" in captured, (
            "unwired+active-CI fusion did not warn that the first PR will red:\n"
            + captured
        )
        assert "verify" in captured and "not optional" in captured

    # DEF-807 (walk 3, W3-P39): the WARNING used to say the workflow "is now
    # committed"; fuse commits nothing after install-ci writes it, so it was
    # untracked on both paths. The sentence now reads git's answer.
    def _unwired_active_gate(self, tmp_path, monkeypatch, out):
        self._stage_settings(out, wired=False)
        monkeypatch.setattr(
            fuse, "fuse_repos",
            lambda *a, **k: {**self._report(out, init_rc=0, via_init=50),
                             "ci_gate_active": True},
        )
        return fuse.cmd_fuse(self._args(tmp_path, out))

    @staticmethod
    def _stage_workflow(out, *, commit: bool) -> None:
        subprocess.run(["git", "init", "-q", str(out)], check=True)
        wf = out / ".github" / "workflows" / "harness-guard.yml"
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text("name: harness-guard\n", encoding="utf-8")
        if commit:
            subprocess.run(["git", "-C", str(out), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(out), "-c", "user.name=t", "-c", "user.email=t@t.com",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "wf"], check=True,
            )

    def test_active_gate_names_the_add_when_the_workflow_is_untracked(
        self, tmp_path, monkeypatch, capsys
    ):
        out = tmp_path / "f"
        out.mkdir()
        self._stage_workflow(out, commit=False)
        assert fuse._workflow_tracked(out) is False
        assert self._unwired_active_gate(tmp_path, monkeypatch, out) == 0
        captured = capsys.readouterr().out
        low = captured.lower()
        assert "not yet committed" in low, captured
        assert "git add .github/workflows/harness-guard.yml" in captured, captured
        assert "is now committed" not in low and "already in git" not in low, captured
        assert "will fail your first" in low and "verify" in low and "not optional" in low

    def test_active_gate_says_tracked_when_git_tracks_the_workflow(
        self, tmp_path, monkeypatch, capsys
    ):
        out = tmp_path / "f"
        out.mkdir()
        self._stage_workflow(out, commit=True)
        assert fuse._workflow_tracked(out) is True
        assert self._unwired_active_gate(tmp_path, monkeypatch, out) == 0
        captured = capsys.readouterr().out
        low = captured.lower()
        assert "already in git" in low, captured
        assert "not yet committed" not in low and "git add" not in low, captured
        assert "will fail your first" in low and "verify" in low and "not optional" in low

    def test_active_gate_claims_nothing_when_git_cannot_answer(
        self, tmp_path, monkeypatch, capsys
    ):
        out = tmp_path / "f"
        out.mkdir()

        import types

        self._stage_workflow(out, commit=False)  # on disk, so absence is not the reason
        real_run = subprocess.run

        def _no_git(argv, *a, **k):  # only the workflow probe loses git
            if argv[:1] == ["git"] and fuse._WORKFLOW_REL in argv:
                raise FileNotFoundError("git")
            return real_run(argv, *a, **k)

        # fuse's own view of the module, not the shared stdlib attribute
        monkeypatch.setattr(fuse, "subprocess", types.SimpleNamespace(
            run=_no_git, SubprocessError=subprocess.SubprocessError,
            TimeoutExpired=subprocess.TimeoutExpired,
        ))
        assert fuse._workflow_tracked(out) is None
        assert self._unwired_active_gate(tmp_path, monkeypatch, out) == 0
        captured = capsys.readouterr().out
        low = captured.lower()
        assert "once committed" in low, captured
        assert "not yet committed" not in low and "already in git" not in low, captured
        assert "will fail your first" in low and "verify" in low and "not optional" in low

    def test_workflow_tracked_is_none_when_the_file_is_absent(self, tmp_path):
        """Absent is a non-answer, not "untracked": the False branch says the
        file is written, so False is reserved for a file on disk."""
        out = tmp_path / "f"
        out.mkdir()
        subprocess.run(["git", "init", "-q", str(out)], check=True)
        assert fuse._workflow_tracked(out) is None

    def test_workflow_rel_is_the_bundled_workflow(self):
        """The path the probe asks about is the one install-ci writes: pinned
        to the packaged workflow roster, so a rename reds here and not only
        in this file's own spelling."""
        from espalier.asset_inventory import _BUNDLED_WORKFLOWS

        assert fuse._WORKFLOW_REL == ".github/workflows/" + _BUNDLED_WORKFLOWS[0]

    def test_unwired_without_active_ci_gate_does_not_overwarn(
        self, tmp_path, monkeypatch, capsys
    ):
        # Negative control: with NO active harness-guard.yml gate there is no
        # first-PR-red, so the loud warning must NOT fire (still points at
        # merge-settings, just without the escalation).
        out = tmp_path / "f"
        out.mkdir()
        self._stage_settings(out, wired=False)
        monkeypatch.setattr(
            fuse, "fuse_repos",
            lambda *a, **k: {**self._report(out, init_rc=0, via_init=50),
                             "ci_gate_active": False},
        )
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        captured = capsys.readouterr().out.lower()
        assert rc == 0
        assert "will fail your first" not in captured
        assert "merge-settings" in captured


    def test_a_refused_host_file_is_not_offered_the_merge(self, tmp_path, monkeypatch, capsys):
        """The negative twin of the two offers above (DEF-700 failure-mode
        review, driven): a host settings.json with a string event value is a
        file `merge-settings` refuses whole and `--wire-hooks` refuses the
        same way, so the pre-push warning must name the value, not the command."""
        for ci_gate_active in (True, False):
            out = tmp_path / ("f-ci" if ci_gate_active else "f-noci")
            out.mkdir()
            (out / ".claude").mkdir(parents=True, exist_ok=True)
            (out / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {"PreToolUse": "my-own-broken-entry"},
            }, indent=2) + "\n", encoding="utf-8")
            monkeypatch.setattr(
                fuse, "fuse_repos",
                lambda *a, **k: {**self._report(out, init_rc=0, via_init=50),
                                 "ci_gate_active": ci_gate_active},
            )
            rc = fuse.cmd_fuse(self._args(tmp_path, out))
            captured = capsys.readouterr().out
            assert rc == 0
            assert "merge-settings .   (or re-fuse" not in captured, captured
            assert "Run `" not in captured or "merge-settings .`" not in captured, captured
            assert "hooks.PreToolUse: str" in captured, captured
            if ci_gate_active:
                assert "WILL FAIL your first" in captured, captured

class TestFuseStartHereAnchor:
    """1-A/1-B: `fuse`'s output tree is never cwd, so the final start-here block
    must anchor the operator to the FUSION. The un-anchored line shipped for the
    life of the verb because nothing pinned it, and the 2026-08-18 Windows walk
    landed a real operator in the ungoverned original as a result."""

    def _report(self, out):
        return {
            "dry_run": False, "out": str(out), "host_files": 3,
            "host_is_git": True, "history_preserved": True,
            "harness_overlaid": 100, "harness_via_init": 50, "init_rc": 0,
        }

    def _args(self, tmp_path, out):
        return argparse.Namespace(host=str(tmp_path), out=str(out),
                                  fresh=False, dry_run=False, no_init=False)

    def test_start_here_block_cds_to_the_fusion(self, tmp_path, monkeypatch, capsys):
        # The fixture path CONTAINS A SPACE deliberately. Space handling is the
        # entire motivation -- every path on the walk had one -- and a space-free
        # fixture leaves the quoting this fix exists for wholly unexercised, so
        # the pin would go green against a defect it never touched.
        out = tmp_path / "fused out"
        out.mkdir()
        TestFuseInitFailure._stage_settings(out, wired=True)
        monkeypatch.setattr(fuse, "fuse_repos", lambda *a, **k: self._report(out))
        rc = fuse.cmd_fuse(self._args(tmp_path, out))
        assert rc == 0
        printed = capsys.readouterr().out
        assert f'cd "{out}"' in printed, (
            "fuse's start-here block must `cd` to the fusion, quoted, or an "
            f"operator who pastes it verbatim starts in the original.\n{printed}"
        )
        # The bare, un-anchored form must be gone -- not merely accompanied.
        assert "Start Claude Code with: claude" not in printed

    def test_maintenance_relaunch_cds_to_the_fusion_too(self, tmp_path, monkeypatch, capsys):
        """DEF-382a leg b: the maintenance-mode relaunch printed a few lines
        above the start-here block carried NO `cd`, while that block documents
        the `cd` as load-bearing -- so an operator who pasted the relaunch got
        a maintenance-mode session in the ungoverned original. The `cd` rides
        directly above the invocation, and the expected block is built from
        the same helper so the pin holds on the Windows three-shell form."""
        from espalier.cli import _maintenance_mode_invocation
        out = tmp_path / "fused out"
        out.mkdir()
        TestFuseInitFailure._stage_settings(out, wired=True)
        monkeypatch.setattr(fuse, "fuse_repos", lambda *a, **k: self._report(out))
        assert fuse.cmd_fuse(self._args(tmp_path, out)) == 0
        printed = capsys.readouterr().out
        expected = f'    cd "{out}"\n' + _maintenance_mode_invocation("claude") + "\n"
        assert expected in printed, (
            "the maintenance relaunch must `cd` to the fusion on the line "
            f"above it, quoted, like the start-here block does.\n{printed}"
        )

    def test_no_unconditional_tomli_advice(self, tmp_path, monkeypatch, capsys):
        """1-C: `tomli` is already a declared dependency (pyproject.toml, marker
        python_version < '3.11'), so `pip install espalier` pulls it. Printing
        the advice to every adopter -- including a TypeScript site -- is
        redundant, not merely noisy."""
        out = tmp_path / "fused out"
        out.mkdir()
        TestFuseInitFailure._stage_settings(out, wired=True)
        monkeypatch.setattr(fuse, "fuse_repos", lambda *a, **k: self._report(out))
        fuse.cmd_fuse(self._args(tmp_path, out))
        assert "pip install tomli" not in capsys.readouterr().out


class TestFuseIORollback:
    """W1-3: a mid-write OSError must remove the half-built `out` (which would
    otherwise block retry via the non-empty-out guard) instead of leaving a
    poisoned directory + raising an uncaught traceback."""

    def test_iofault_rolls_back_created_out(self, tmp_path, monkeypatch):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        real_copy2 = fuse.shutil.copy2

        # Fault on a specific HOST file (not a positional call count) so the test
        # robustly exercises the host-copy-phase rollback even if a future refactor
        # adds a copy2 call earlier in the write phase.
        def flaky_copy2(s, d, *a, **k):
            if str(s).replace("\\", "/").endswith("src/app.py"):
                raise OSError("disk full (injected)")
            return real_copy2(s, d, *a, **k)

        monkeypatch.setattr(fuse.shutil, "copy2", flaky_copy2)
        with pytest.raises(OSError, match="disk full"):
            fuse.fuse_repos(host, out, run_init=False)
        assert not out.exists(), "half-built out left behind (blocks retry)"

    def test_iofault_preserves_preexisting_empty_out(self, tmp_path, monkeypatch):
        # An empty dir the user pointed --out at must NOT be deleted on fault.
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        out.mkdir()
        real_copy2 = fuse.shutil.copy2

        def flaky_copy2(s, d, *a, **k):
            if str(s).replace("\\", "/").endswith("src/app.py"):
                raise OSError("disk full (injected)")
            return real_copy2(s, d, *a, **k)

        monkeypatch.setattr(fuse.shutil, "copy2", flaky_copy2)
        with pytest.raises(OSError, match="disk full"):
            fuse.fuse_repos(host, out, run_init=False)
        assert out.exists(), "pre-existing empty out wrongly removed"

    def test_non_oserror_fault_also_rolls_back(self, tmp_path, monkeypatch):
        """W2-3: cmd_init / the seed helpers can raise ValueError / KeyError /
        SubprocessError — a narrow `except OSError` would let those escape PAST
        the rollback, leaving a half-built `out` that blocks retry."""
        host = _make_host(tmp_path)
        out = tmp_path / "out"

        def boom(*a, **k):
            raise ValueError("non-OSError fault (injected)")

        monkeypatch.setattr(fuse, "_copy", boom)  # fails after out.mkdir()
        with pytest.raises(ValueError, match="non-OSError fault"):
            fuse.fuse_repos(host, out, run_init=False)
        assert not out.exists(), "half-built out left behind after a non-OSError fault"


class TestFuseManifestOverlay:
    """W3: manifest leak/drop corrections, asserted via the pure `_should_overlay`
    predicate (no real fuse needed)."""

    def test_no_workflow_oneshots_overlay(self):  # W3-2 / TP-186: exhaustive
        # The convention is "the fan-out ENGINE ships, the operator authors their
        # own workflows" — so EVERY tracked .claude/workflows/*.js must be excluded
        # from the overlay. Exhaustive (not a 5-file sample) because the TP-186
        # _fanout_audit.js scaffold added a workflow whose prefix matched none of
        # the existing EXCLUDE lines and would have silently leaked into adopter
        # fusions; the sample would not have caught it.
        tracked = fuse._tracked_files(Path.cwd()) or []
        assert tracked, "expected to run inside the espalier git checkout"
        workflows = [
            r for r in tracked
            if r.startswith(".claude/workflows/") and r.endswith(".js")
        ]
        # Floor guards a vacuous pass (empty glob / _tracked_files regression) and
        # catches a mass-deletion; it is NOT a "keep N workflows" contract. Tracks the
        # live population — the spent one-shot run-scripts (the TP-169 freeze-hardening
        # saga + the frozen v1 release-hardening/oss-readiness reviews) were pruned once
        # their lessons landed in docs/sharp-edges/ + RELEASE_FINDINGS_LEDGER, dropping
        # the corpus from 28 to 7 (3 templates + 4 live-v2 reviews).
        assert len(workflows) >= 5, f"tracked workflow corpus too small: {len(workflows)}"
        leaked = [w for w in workflows if fuse._should_overlay(w)]
        assert not leaked, f"espalier workflow(s) leaked into the fusion overlay: {leaked}"

    def test_quickstart_not_overlaid(self):  # W3-1
        assert not fuse._should_overlay("docs/QUICKSTART.md")

    def test_portable_sharp_edges_overlaid(self):  # W3-5
        for body in ("docs/sharp-edges/convergence-is-an-angle-set-property.md",
                     "docs/sharp-edges/closed-loop-verification-trap.md",
                     "docs/sharp-edges/hook-exit-codes-channel-xor.md"):
            assert fuse._should_overlay(body), body

    def test_espalier_specific_sharp_edges_not_overlaid(self):  # W3-5 negative control
        # only README + the 3 portable bodies ship; the espalier-specific ones don't
        assert not fuse._should_overlay("docs/sharp-edges/protected-zone-symlink-backstop.md")
        assert not fuse._should_overlay("docs/sharp-edges/malformed-json-fail-open.md")

    def test_no_internal_content_leaks_into_overlay(self):  # W5 leak gate
        """CI fusion-payload leak gate (the v0.6.0 project.zip leak precedent): the
        overlay computed against espalier's own tracked tree must carry ZERO
        espalier-internal content — only SYSTEM (mechanism), never CONTENT."""
        tracked = fuse._tracked_files(Path.cwd()) or []
        assert tracked, "expected to run inside the espalier git checkout"
        overlay = {r for r in tracked if fuse._should_overlay(r)}
        # RESEED_SKIP exact docs + the self-hosted MEMORY/CLAUDE must never ship
        for internal in ("ESPALIER_MEMORY.md", "CLAUDE.md", "docs/CONVENTIONS.md",
                         "docs/SHARP_EDGES.md", "docs/POSITIONING.md",
                         "docs/RELEASE_DECISIONS.md", "docs/DEMO.md"):
            assert internal not in overlay, f"internal doc leaked into overlay: {internal}"
        # espalier's accumulated memory topic files (only the convention ships)
        mem_leaks = [r for r in overlay if r.startswith("memory/") and r != "memory/README.md"]
        assert not mem_leaks, f"espalier memory content leaked: {mem_leaks}"
        # espalier's own task packs + review evidence (only the router ships)
        tp_leaks = [r for r in overlay if r.startswith("task-packs/") and r != "task-packs/CLAUDE.md"]
        assert not tp_leaks, f"espalier task packs leaked: {tp_leaks}"
        # rendered surface indexes + blueprints
        cc_leaks = [r for r in overlay if r.startswith("cc/")]
        assert not cc_leaks, f"espalier surface indexes leaked: {cc_leaks}"


class TestFuseEspalierTomlStub:
    """W2-3: fuse seeds a COMMENTED plan_exempt_prefixes stub — never an active
    exemption (the adopter's source stays plan-gated by default; settled in
    docs/RELEASE_DECISIONS.md)."""

    def test_seeds_commented_inert_stub(self, tmp_path):
        from espalier.config import load_config
        assert fuse._seed_espalier_toml(tmp_path) is True
        toml = tmp_path / "espalier.toml"
        assert toml.is_file()
        text = toml.read_text(encoding="utf-8")
        # the knob is documented but COMMENTED — no active key at line start
        assert "plan_exempt_prefixes" in text
        assert not any(
            stripped.startswith("plan_exempt_prefixes")
            for line in text.splitlines()
            for stripped in [line.lstrip()]
            if not stripped.startswith("#")
        ), "stub seeded an ACTIVE plan_exempt_prefixes — must stay commented"
        # parses to the default (empty) — fully inert
        assert load_config(tmp_path).plan_exempt_prefixes == []

    def test_does_not_overwrite_existing(self, tmp_path):
        existing = tmp_path / "espalier.toml"
        existing.write_text('plan_exempt_prefixes = ["src/"]\n', encoding="utf-8")
        assert fuse._seed_espalier_toml(tmp_path) is False
        assert existing.read_text(encoding="utf-8") == 'plan_exempt_prefixes = ["src/"]\n'


class TestFuseSelfHostCIMarker:
    """W1-1: a fusion overlays the full espalier/ engine, so the 3 self-host CI
    jobs in harness-guard.yml (gated on `espalier/__init__.py` presence) would
    fire on the adopter's first PR. `fuse` drops a tracked `.espalier-fusion`
    marker; the jobs gate on its ABSENCE so they skip in a fusion."""

    def test_seeds_tracked_marker(self, tmp_path):
        assert fuse._seed_fusion_marker(tmp_path) is True
        marker = tmp_path / fuse._FUSION_MARKER
        assert marker.is_file()
        # presence is what CI gates on; body is human-facing but non-vacuous
        assert "espalier fuse" in marker.read_text(encoding="utf-8").lower()

    def test_marker_is_idempotent(self, tmp_path):
        (tmp_path / fuse._FUSION_MARKER).write_text("# pre-existing\n", encoding="utf-8")
        assert fuse._seed_fusion_marker(tmp_path) is False
        assert (tmp_path / fuse._FUSION_MARKER).read_text(encoding="utf-8") == "# pre-existing\n"

    def test_fuse_writes_marker_even_without_init(self, tmp_path):
        # cheap (run_init=False): the marker is a write-phase artifact, not an
        # init/orchestration product, so it lands in every successful fusion.
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        report = fuse.fuse_repos(host, out, run_init=False)
        assert report.get("fusion_marker") is True
        assert (out / fuse._FUSION_MARKER).is_file()

    def test_marker_not_under_gitignored_espalier_dir(self):
        # CI's detect-source job reads the COMMITTED file — the marker must live
        # OUTSIDE the gitignored `.espalier/` runtime dir or it never reaches CI.
        assert "/" not in fuse._FUSION_MARKER
        assert not fuse._FUSION_MARKER.startswith(".espalier/")


class TestFuseInstallCiWarn:
    """W1-3: cmd_install_ci handles its failure modes INTERNALLY (`return 1`,
    never raises), so `_orchestrate_bootstrap`'s `except OSError` can't see them.
    A non-zero rc must still surface an operator-visible WARN — otherwise the
    fusion ships with no PR merge-gate under cmd_fuse's 'harness is live' banner."""

    def test_nonzero_install_ci_rc_warns(self, tmp_path, monkeypatch, capsys):
        import espalier.cli as cli
        monkeypatch.setattr(cli, "cmd_install_ci", lambda *a, **k: 1)
        monkeypatch.setattr(fuse, "_run_in_fusion", lambda *a, **k: 0)
        report = {}
        fuse._orchestrate_bootstrap(tmp_path, report)
        assert report["install_ci_rc"] == 1
        err = capsys.readouterr().err
        assert "install-ci returned 1" in err
        assert "merge-gate is not installed" in err

    def test_zero_install_ci_rc_does_not_warn(self, tmp_path, monkeypatch, capsys):
        import espalier.cli as cli
        monkeypatch.setattr(cli, "cmd_install_ci", lambda *a, **k: 0)
        monkeypatch.setattr(fuse, "_run_in_fusion", lambda *a, **k: 0)
        report = {}
        fuse._orchestrate_bootstrap(tmp_path, report)
        assert report["install_ci_rc"] == 0
        assert "install-ci returned" not in capsys.readouterr().err


class TestFuseW2Correctness:
    """W2-1 (worktree/submodule history honesty), W2-2 (managed-md predicate),
    W2-4 (don't clobber a host-authored harness-guard.yml)."""

    def test_worktree_host_history_not_preserved_warns(self, tmp_path, capsys):  # W2-1
        main = _make_host(tmp_path)
        wt = tmp_path / "wt"
        subprocess.run(
            ["git", "-C", str(main), "worktree", "add", "-q", "--detach", str(wt)],
            check=True,
        )
        assert (wt / ".git").is_file()  # worktree: .git is a pointer FILE
        out = tmp_path / "out"
        report = fuse.fuse_repos(wt, out, run_init=False)
        assert report["history_preserved"] is False
        assert "worktree/submodule" in capsys.readouterr().err
        assert (out / ".git").is_dir()  # fusion is still a valid (fresh-init) repo

    def test_is_managed_md_recognizes_claude_bodies(self):  # W2-2
        assert fuse._is_managed_md(".claude/agents/code-reviewer.md")
        assert fuse._is_managed_md(".claude/commands/commit.md")
        assert fuse._is_managed_md(".claude/skills/reflect/SKILL.md")
        assert not fuse._is_managed_md(".claude/settings.json")
        assert not fuse._is_managed_md("espalier/cli.py")
        assert not fuse._is_managed_md(".claude/workflows/foo.js")

    def test_install_ci_preserves_host_authored_workflow(self, tmp_path, capsys):  # W2-4
        from espalier.cli import cmd_install_ci
        repo = tmp_path / "repo"
        wf = repo / ".github" / "workflows" / "harness-guard.yml"
        wf.parent.mkdir(parents=True)
        wf.write_text("name: My Own Workflow\n", encoding="utf-8")
        rc = cmd_install_ci(argparse.Namespace(repo=str(repo)))
        assert rc == 0
        # host workflow left untouched; espalier's written alongside as `.new`
        assert wf.read_text(encoding="utf-8") == "name: My Own Workflow\n"
        assert (wf.parent / "harness-guard.yml.new").is_file()
        assert "exists and differs" in capsys.readouterr().err


@pytest.mark.integration
class TestFuseEndToEnd:
    """Real fuse (copies the live espalier tree + runs init). Marked integration."""

    def _fuse(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "fusion"
        report = fuse.fuse_repos(host, out, run_init=True)
        return host, out, report

    def test_host_code_and_pyproject_preserved(self, tmp_path):
        host, out, _ = self._fuse(tmp_path)
        assert (out / "src" / "app.py").read_text(encoding="utf-8") == (host / "src" / "app.py").read_text(encoding="utf-8")
        assert 'name = "my-app"' in (out / "pyproject.toml").read_text(encoding="utf-8")
        # original host untouched
        assert not (host / "espalier").exists()

    def test_harness_overlaid_and_managed(self, tmp_path):
        _, out, report = self._fuse(tmp_path)
        assert report["init_rc"] == 0
        assert report["harness_overlaid"] > 0 and report["harness_via_init"] > 0
        # engine + bench + crown-jewel docs + fan-out (overlay extras)
        assert (out / "espalier" / "scanners" / "exceptions.py").is_file()
        assert (out / "bench" / "corpus").is_dir()
        assert (out / "docs" / "FAILURE_MODES.md").is_file()
        assert (out / "espalier" / "fan_out_findings.py").is_file()
        assert (out / "tools" / "cc" / "ci_guard.py").is_file()  # the init-gap file
        # hooks deployed by init are MARKED managed
        assert "espalier:managed" in (out / "tools" / "cc" / "hooks" / "write_guard.py").read_text(encoding="utf-8")

    def test_no_espalier_content_leak(self, tmp_path):
        _, out, _ = self._fuse(tmp_path)
        mem = (out / "ESPALIER_MEMORY.md").read_text(encoding="utf-8")
        # direct, non-vacuous check: the fused ESPALIER_MEMORY.md must NOT be espalier's
        # source file verbatim (an overlay that ignored RESEED_SKIP would copy it).
        src_mem = (fuse._espalier_source_root() / "ESPALIER_MEMORY.md").read_text(encoding="utf-8")
        assert mem != src_mem, "fused ESPALIER_MEMORY.md is espalier's source verbatim (RESEED_SKIP leak)"
        assert "self-hosted memory log" not in mem.lower()  # espalier's MEMORY header
        # categorized memory ships the convention only, not espalier's topic files
        memfiles = [p.name for p in (out / "memory").glob("*.md")]
        assert memfiles == ["README.md"], memfiles
        # no espalier task packs / conventions
        assert not list((out / "task-packs").glob("TP-*.md")) if (out / "task-packs").exists() else True
        # docs/CONVENTIONS.md + docs/SHARP_EDGES.md are RESEED_SKIP: espalier's own
        # bodies must never reach the fusion. This was an ABSENCE check until both
        # became init-seeded as near-empty adopter stubs
        # (managed_inventory._SEED_ASSET_SOURCES) — presence no longer separates a
        # leak from a seed, so it asks the same question the ESPALIER_MEMORY.md
        # check above asks: is the CONTENT espalier's? The line bound is what makes
        # it non-vacuous; espalier's own bodies are thousands of lines.
        for rel in ("docs/CONVENTIONS.md", "docs/SHARP_EDGES.md"):
            fused = (out / rel).read_text(encoding="utf-8")
            source = (fuse._espalier_source_root() / rel).read_text(encoding="utf-8")
            assert fused != source, (
                f"fused {rel} is espalier's source verbatim (RESEED_SKIP leak)"
            )
            n = len(fused.splitlines())
            assert n < 60, (
                f"fused {rel} is not a near-empty stub ({n} lines) — espalier "
                "content leaked into the fusion"
            )

    def test_fusion_is_not_self_host_and_engine_runs(self, tmp_path):
        _, out, _ = self._fuse(tmp_path)
        import sys
        # is_self_host False because the host pyproject name is preserved
        hooks = out / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hooks))
        try:
            from _hook_utils import is_self_host_repo  # noqa: PLC0415
            assert is_self_host_repo(out) is False
        finally:
            sys.path.remove(str(hooks))
        # the fusion's own engine runs self-contained (zero-pip) against itself
        r = subprocess.run(
            [sys.executable, "-m", "espalier", "audit", str(out)],
            cwd=str(out), env={**__import__("os").environ, "PYTHONPATH": str(out)},
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        assert '"status"' in r.stdout

    def test_history_preserved_by_default(self, tmp_path):
        _, out, report = self._fuse(tmp_path)
        assert report["history_preserved"] is True
        n = subprocess.run(["git", "-C", str(out), "rev-list", "--count", "HEAD"],
                           capture_output=True, text=True, encoding="utf-8").stdout.strip()
        assert n == "1"

    def test_install_ci_merge_gate_landed(self, tmp_path):
        """W2-2: init alone never writes .github/workflows/harness-guard.yml; the
        orchestration step must (it is the PR merge-gate)."""
        _, out, report = self._fuse(tmp_path)
        assert report.get("install_ci_rc") == 0
        assert (out / ".github" / "workflows" / "harness-guard.yml").is_file()

    def test_overlaid_claude_bodies_are_managed_marked(self, tmp_path):
        """W2-2: every .claude/{agents,commands,skills} body in the fusion carries
        the espalier:managed marker — init marks the common tier, the overlay
        marks the harness-dev tier. Without the overlay-side marking those bodies
        are orphaned by `clean-generated` (uninstall contract broken)."""
        from espalier import managed_markers
        _, out, _ = self._fuse(tmp_path)
        unmarked = []
        for sub in ("agents", "commands", "skills"):
            for p in (out / ".claude" / sub).rglob("*.md"):
                if not managed_markers.has_managed_marker(p.read_text(encoding="utf-8")):
                    unmarked.append(str(p.relative_to(out)))
        assert not unmarked, f"overlaid .claude bodies missing managed marker: {unmarked}"

    def test_fusion_marker_present_and_self_host_jobs_gated_off(self, tmp_path):
        """W1-1: the real fusion ships the tracked `.espalier-fusion` marker, and
        the installed harness-guard.yml's self-host jobs gate on its absence — so
        freshness/ruff-lint/memory-tag-parity skip on the adopter's first PR."""
        _, out, report = self._fuse(tmp_path)
        assert report.get("fusion_marker") is True
        assert (out / fuse._FUSION_MARKER).is_file()
        wf = (out / ".github" / "workflows" / "harness-guard.yml").read_text(encoding="utf-8")
        # TP-246: the fusion-absence check now lives in the `detect-source` job's
        # step (job-level hashFiles() is illegal — it startup-failed the whole
        # workflow), and the self-host jobs gate on its output. Assert the
        # marker is still consulted AND all self-host jobs read the gate.
        # TP-321a added `mypy-hooks` as a 4th self-host-gated job.
        assert ".espalier-fusion" in wf, wf
        assert wf.count("needs.detect-source.outputs.is_source == 'true'") == 4, wf

    def test_analyze_fingerprint_refreshed_post_overlay(self, tmp_path):
        """W2-4: fuse re-fingerprints the fused repo (host-targeted test gating).

        Bench (`--update-canonical`) is intentionally NOT run here — its corpus is
        espalier-self-referential, so a fresh fusion scores <100% and the
        canonical-update guard fail-closes. The scoreboard is a finish-up step."""
        _, out, report = self._fuse(tmp_path)
        assert report.get("fingerprint_rc") == 0
        assert (out / "reports" / "repo_fingerprint.json").is_file()

    def test_commented_plan_exempt_stub_seeded(self, tmp_path):
        """W2-3: the fusion ships a commented plan_exempt_prefixes stub (the host's
        source is plan-gated by default; the knob is discoverable but inert)."""
        _, out, report = self._fuse(tmp_path)
        assert report.get("seeded_espalier_toml") is True
        toml = out / "espalier.toml"
        assert toml.is_file()
        assert "# plan_exempt_prefixes" in toml.read_text(encoding="utf-8")

    def test_fused_write_guard_blocks_protected_zone(self, tmp_path):
        """W5: prove the overlaid governance is LIVE — pipe a protected-zone Write
        event to the FUSED write_guard.py and assert it denies. The deny rides the
        structured channel (exit 0 + JSON permissionDecision), per channel-XOR."""
        import json
        import os
        import sys
        _, out, _ = self._fuse(tmp_path)
        guard = out / "tools" / "cc" / "hooks" / "write_guard.py"
        assert guard.is_file()
        # prove it's the init-DEPLOYED (managed-marked) guard, not a raw source copy
        assert "espalier:managed" in guard.read_text(encoding="utf-8")
        event = {"tool_name": "Write",
                 "tool_input": {"file_path": ".claude/settings.json"}}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(out)}
        env.pop("ESPALIER_MAINTENANCE_MODE", None)  # don't let the parent shell bypass
        r = subprocess.run([sys.executable, str(guard)], input=json.dumps(event),
                           capture_output=True, text=True, timeout=15, env=env, encoding="utf-8")
        assert r.returncode == 0, (r.returncode, r.stderr)
        decision = json.loads(r.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny", decision
        assert "protected" in decision["permissionDecisionReason"].lower()

    def test_a_nonpython_fusion_is_upgrade_clean_and_doctor_clean(self, tmp_path, capsys):
        """DEF-806 (walk 3, W3-P38): init renders the two plan-reading cc/ docs
        from a fingerprint of the HOST alone; the overlay lands the engine, and
        install-ci's re-baseline gives the plan the ``scan`` action the engine's
        Python earns. The docs must follow the plan, or ``upgrade`` on a tree
        built seconds earlier says the surface is not current. The stressor is
        asserted: the host on its own is not Python, so its plan has no
        ``scan``; the fusion's plan does. The ``doctor`` lines are a
        no-regression control, not the oracle (doctor does not see a stale
        plan render); ``upgrade`` is."""
        import argparse
        import json

        from espalier.cli import cmd_upgrade
        from espalier.doctor import run_doctor_check
        from espalier.analyze import fingerprint_repo
        from espalier.render_surface import PLAN_READERS

        host = _make_nonpython_host(tmp_path)
        assert "python" not in fingerprint_repo(host).languages, "stressor: a non-Python host"
        out = tmp_path / "fusion"
        report = fuse.fuse_repos(host, out, run_init=True)
        assert report["init_rc"] == 0 and report.get("install_ci_rc") == 0, report
        plan = json.loads((out / "reports" / "harness_config.json").read_text(encoding="utf-8"))
        assert "scan" in plan["stable_actions"], "stressor: the fusion's plan gained scan"
        for rel in PLAN_READERS:
            assert "espalier scan ." in (out / rel).read_text(encoding="utf-8"), (
                f"{rel} still renders the host-only plan"
            )
        capsys.readouterr()
        assert cmd_upgrade(argparse.Namespace(repo=str(out), execute=False, config=None)) == 0
        assert "nothing to do" in capsys.readouterr().out, "a fresh fusion is not upgrade-clean"
        doctor = run_doctor_check(out)
        assert doctor["status"] == "pass", doctor
        assert not any("plan" in w or "surface" in w for w in doctor["warnings"]), doctor["warnings"]

    @pytest.mark.parametrize("preserve_history", [True, False])
    def test_the_workflow_is_untracked_on_both_paths(self, tmp_path, preserve_history):
        """DEF-807 (walk 3, W3-P39): the baseline commit runs at step 2 and
        install-ci writes the workflow at step 5 on the fresh path, and the
        history-preserving path commits nothing -- so the file the epilogue
        once called committed is untracked on both, and the helper the
        sentence now reads agrees with git."""
        host = _make_host(tmp_path)
        out = tmp_path / "fusion"
        report = fuse.fuse_repos(host, out, run_init=True, preserve_history=preserve_history)
        assert report["init_rc"] == 0 and report.get("ci_gate_active") is True, report
        wf = out / ".github" / "workflows" / "harness-guard.yml"
        assert wf.is_file()
        status = subprocess.run(
            ["git", "-C", str(out), "status", "--porcelain", "--", str(wf.relative_to(out))],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        assert status.startswith("??"), status
        assert fuse._workflow_tracked(out) is False


class TestFuseSymlinkFidelity:
    """B-1 #7: a host that tracks a symlink must come out of the fusion with the
    symlink PRESERVED (not skipped, not dereferenced) so its first `git status`
    is clean. The old `_copy` dropped symlinks-to-dirs / dangling symlinks and
    silently dereferenced file-symlinks."""

    def _host_with_symlink(self, tmp_path: Path) -> Path:
        host = tmp_path / "host"
        host.mkdir()
        (host / "real.txt").write_text("hi\n", encoding="utf-8")
        (host / "link.txt").symlink_to("real.txt")
        subprocess.run(["git", "init", "-q", str(host)], check=True)
        subprocess.run(["git", "-C", str(host), "config", "user.email", "t@t.com"], check=True)
        subprocess.run(["git", "-C", str(host), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(host), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(host), "commit", "-qm", "init"], check=True)
        return host

    @requires_symlink
    def test_tracked_symlink_preserved_not_dereferenced(self, tmp_path):
        host = self._host_with_symlink(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        fused = out / "link.txt"
        assert fused.is_symlink(), "tracked symlink was dereferenced or dropped"
        assert str(fused.readlink()) == "real.txt"

    @requires_symlink
    def test_fused_symlink_repo_clean_on_first_status(self, tmp_path):
        # The payoff the finding flagged: history-preserving fusion + preserved
        # symlink => the host's tracked symlink is NOT dirty on first `git status`.
        host = self._host_with_symlink(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False, preserve_history=True)
        status = subprocess.run(
            ["git", "-C", str(out), "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "link.txt" not in status.stdout, (
            "tracked symlink shows dirty (typechange/modified) after fusion:\n"
            + status.stdout
        )


class TestFuseSharpEdgesSeed:
    """TP-182 B1: the overlay RESEED_SKIPs espalier's SHARP_EDGES.md monolith, but
    the overlaid harness docs (HOOKS.md, HOOK_ASSUMPTIONS.md, WORKFLOW.md) still
    link `SHARP_EDGES.md`, so without the file a fused adopter's first
    reflect/doctor dangles on 6 links. `_seed_sharp_edges` writes a near-empty
    folder-router stub so those link targets exist. (The SessionStart orientation
    step-2 gap is separate — `is_self_host_repo`-gated, intentional for adopters —
    and is NOT addressed here.)"""

    def test_fuse_seeds_sharp_edges_stub(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        seeded = out / "docs" / "SHARP_EDGES.md"
        assert seeded.exists(), "fusion did not seed docs/SHARP_EDGES.md"
        text = seeded.read_text(encoding="utf-8")
        assert any(line.startswith("## ") for line in text.splitlines()), (
            "seed should carry a `## ` heading (a real sharp-edges doc has sections)"
        )
        assert "sharp-edges/" in text, "seed is not a folder router to docs/sharp-edges/"
        # DEF-696: one renderer. The fused stub is byte-equal to what init
        # writes -- the stamp line and the body -- a second read of the asset
        # here would be the flag-dependent second version of one adopter file
        # the moment the seed gained an adapt header. Stamped since 2026-09-11
        # (DEF-432's review): an unstamped stub was preserved by every later
        # init forever, so its own "refreshed on re-init while untouched"
        # sentence was false on every fused tree.
        from espalier.cli import _write_seed
        from espalier.managed_inventory import render_seed_body, seed_stamp_line
        body = render_seed_body("docs/SHARP_EDGES.md")
        assert text == seed_stamp_line(body) + body
        # ...and therefore refreshable by a later init when the packaged body
        # drifts, exactly as the stub's sentence says.
        assert _write_seed(seeded, body + "DRIFT\n", label="docs/SHARP_EDGES.md") is True
        assert seeded.read_text(encoding="utf-8").endswith("DRIFT\n")

    def test_seeded_sharp_edges_resolves_overlaid_doc_links(self, tmp_path):
        # The real B1 value: the overlaid harness docs link `SHARP_EDGES.md`
        # (relative, same docs/ dir). The seed makes that link target exist, so a
        # fused adopter's first `reflect`/`doctor` no longer dangles on it.
        # earn-the-red: pre-fix the fusion had NO docs/SHARP_EDGES.md (verified
        # live: 6 broken SHARP_EDGES.md links -> 0 after the seed).
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        hooks_doc = out / "docs" / "HOOKS.md"
        assert hooks_doc.exists(), "fixture: overlaid docs/HOOKS.md missing"
        assert "SHARP_EDGES.md" in hooks_doc.read_text(encoding="utf-8"), (
            "fixture: docs/HOOKS.md no longer links SHARP_EDGES.md"
        )
        assert (out / "docs" / "SHARP_EDGES.md").exists(), (
            "overlaid docs link SHARP_EDGES.md but the fusion did not seed the target"
        )

    def test_seed_does_not_clobber_host_sharp_edges(self, tmp_path):
        # Sovereignty: a host that already ships docs/SHARP_EDGES.md keeps it.
        host = _make_host(tmp_path)
        (host / "docs").mkdir(exist_ok=True)
        (host / "docs" / "SHARP_EDGES.md").write_text(
            "# My own edges\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(host), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(host), "commit", "-qm", "edges"], check=True
        )
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        assert (out / "docs" / "SHARP_EDGES.md").read_text(
            encoding="utf-8"
        ) == "# My own edges\n"


class TestFuseNoBrokenLinks:
    """TP-182 B-links: a freshly-fused adopter's first reflect/doctor must show
    ZERO broken markdown links. The fusion ships espalier-internal docs that used
    to link deliberately-unshipped targets (16 danglers). Fixed by: not shipping
    4 espalier-maintainer docs (HOOK_ASSUMPTIONS + 3 folder ladders), de-linking
    HOOKS.md's pointer to the removed rationale, fixing a depth-wrong path, and
    seeding the FINISH_UP bench/RESULTS.md placeholder."""

    def test_maintainer_docs_not_shipped(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        for rel in (
            "docs/HOOK_ASSUMPTIONS.md",
            "espalier/assets/CLAUDE.md",
            "espalier/scanners/CLAUDE.md",
            "tools/cc/hooks/CLAUDE.md",
            # TP-279: the engine-root + scripts-root folder guides (blanket
            # espalier/+tools/ includes → need an explicit RESEED_SKIP).
            "espalier/CLAUDE.md",
            "tools/cc/CLAUDE.md",
        ):
            assert not (out / rel).exists(), (
                f"espalier-maintainer doc {rel} should not ship to a fusion"
            )

    def test_bench_results_seeded(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        results = out / "bench" / "RESULTS.md"
        assert results.exists(), "bench/README.md links RESULTS.md but it was not seeded"
        assert "update-canonical" in results.read_text(encoding="utf-8"), (
            "RESULTS.md placeholder should point at the FINISH_UP step"
        )

    def test_fusion_has_zero_broken_markdown_links(self, tmp_path):
        # earn-the-red: pre-fix a fresh fusion had 16 broken markdown links
        # (verified live). This is the definitive end-to-end proof.
        import sys
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False)
        r = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "reflect", str(out)],
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        report = json.loads(r.stdout)
        broken = report.get("broken_markdown_links", [])
        assert broken == [], (
            f"fusion has {len(broken)} broken markdown links:\n"
            + "\n".join(f"  {b.get('file')} -> {b.get('target')}" for b in broken)
        )


class TestFuseFreshBaseline:
    """TP-182 C1: a --fresh (history-dropped) fusion must not be left with ZERO
    commits — `git log` "no commits yet" + a wall of `??`. The host files are
    committed as a baseline; the harness overlay reads as uncommitted changes."""

    def test_fresh_fusion_has_baseline_commit(self, tmp_path):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False, preserve_history=False)
        count = subprocess.run(
            ["git", "-C", str(out), "rev-list", "--all", "--count"],
            capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        assert count.isdigit() and int(count) >= 1, (
            f"--fresh fusion should have a baseline commit; got rev-list count={count!r}"
        )

    def test_history_preserving_fusion_keeps_host_commit(self, tmp_path):
        # Regression: the default (history-preserving) path is unchanged — the
        # host's own commit is the HEAD, the baseline-commit path does not fire.
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        fuse.fuse_repos(host, out, run_init=False, preserve_history=True)
        log = subprocess.run(
            ["git", "-C", str(out), "log", "--oneline"],
            capture_output=True, text=True, encoding="utf-8",
        ).stdout
        assert "init" in log, "history-preserving fusion lost the host's commit"
        assert "pre-Espalier-fusion snapshot" not in log, (
            "baseline commit fired on the history-preserving path (should not)"
        )


def _make_host_with_settings(tmp_path: Path, settings: dict) -> Path:
    """A host carrying a COMMITTED .claude/settings.json (the B-1 case the fusion
    init sees: permissions-but-no-Espalier-hooks)."""
    host = _make_host(tmp_path)
    claude = host / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(host), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(host), "commit", "-qm", "add settings"], check=True)
    return host


@pytest.mark.integration
class TestFuseWireHooks:
    """TP-183: `fuse --wire-hooks` arms the fusion in ONE command when the host's
    copied .claude/settings.json has no Espalier hooks. Opt-in (same `--wire-hooks`
    polarity as init); the default still preserves the copied file disarmed (the F2
    honest-banner case). Real fuse end-to-end."""

    def test_wire_hooks_arms_fusion(self, tmp_path):
        # earn-the-red: pre-TP-183 fuse has no `wire_hooks` param, so a fused repo
        # whose host brought a permissions-only settings.json shipped disarmed.
        host = _make_host_with_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        out = tmp_path / "fusion"
        report = fuse.fuse_repos(host, out, run_init=True, wire_hooks=True)
        assert report["init_rc"] == 0
        fused = out / ".claude" / "settings.json"
        data = json.loads(fused.read_text(encoding="utf-8"))
        assert "tools/cc/hooks" in json.dumps(data.get("hooks", {})), (
            "fusion not armed by --wire-hooks"
        )
        # the host's own permissions survive the wire
        assert data["permissions"]["allow"] == ["Bash(ls:*)"], (
            "host permissions lost when the fusion was armed"
        )
        assert (out / ".claude" / "settings.json.bak").exists(), (
            ".bak backup not written in the fusion"
        )

    def test_default_leaves_fusion_settings_disarmed(self, tmp_path):
        # The regression pin: WITHOUT the flag the copied host settings.json is
        # preserved disarmed (F2 honesty). Proves the opt-in default is intact.
        host = _make_host_with_settings(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}}
        )
        out = tmp_path / "fusion"
        fuse.fuse_repos(host, out, run_init=True)  # no wire_hooks
        data = json.loads(
            (out / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        assert "tools/cc/hooks" not in json.dumps(data.get("hooks", {})), (
            "fusion wired hooks WITHOUT --wire-hooks (the opt-in default changed!)"
        )


class TestFuseCiGateBanner:
    """TP-184 B2: the fuse success banner must not claim an active PR merge-gate
    when install-ci parked espalier's gate in harness-guard.yml.new (the host
    shipped a differing workflow). The honest signal is report['ci_gate_active'],
    not install_ci_rc (which is 0 on the park too)."""

    def _report(self, out, *, ci_gate_active):
        return {
            "dry_run": False, "out": str(out), "host_files": 3,
            "host_is_git": True, "history_preserved": True,
            "harness_overlaid": 100, "harness_via_init": 50, "init_rc": 0,
            "install_ci_rc": 0, "ci_gate_active": ci_gate_active,
            "fingerprint_rc": None,
        }

    def _args(self, tmp_path, out):
        return argparse.Namespace(host=str(tmp_path), out=str(out),
                                  fresh=False, dry_run=False, no_init=False)

    def _stage(self, out):
        (out / ".claude").mkdir(parents=True, exist_ok=True)
        data = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "python3",
             "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]}]}]}}
        (out / ".claude" / "settings.json").write_text(
            json.dumps(data) + "\n", encoding="utf-8")

    def test_active_gate_claims_merge_gate(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "f"; out.mkdir(); self._stage(out)
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, ci_gate_active=True))
        assert fuse.cmd_fuse(self._args(tmp_path, out)) == 0
        assert "PR merge-gate" in capsys.readouterr().out

    def test_parked_gate_does_not_claim_merge_gate(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "f"; out.mkdir(); self._stage(out)
        monkeypatch.setattr(fuse, "fuse_repos",
                            lambda *a, **k: self._report(out, ci_gate_active=False))
        assert fuse.cmd_fuse(self._args(tmp_path, out)) == 0
        outtxt = capsys.readouterr().out
        assert "installed (PR merge-gate)" not in outtxt, (
            "banner falsely claims an active merge-gate while the gate is parked")
        assert "PARKED" in outtxt


class TestInstallCiGateActiveReport:
    """TP-184 B2 (root): cmd_install_ci records report['ci_gate_active'] so the
    rc==0 .new-park path is distinguishable from an actually-active gate."""

    def test_clean_repo_marks_gate_active(self, tmp_path):
        from espalier.cli import cmd_install_ci
        report: dict = {}
        rc = cmd_install_ci(argparse.Namespace(repo=str(tmp_path)), report=report)
        assert rc == 0
        assert report["ci_gate_active"] is True
        assert (tmp_path / ".github" / "workflows" / "harness-guard.yml").exists()

    def test_differing_host_workflow_parks_and_marks_inactive(self, tmp_path):
        from espalier.cli import cmd_install_ci
        wf = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        wf.parent.mkdir(parents=True)
        wf.write_text("name: host-own-gate\non: push\n", encoding="utf-8")  # differs
        before = wf.read_text(encoding="utf-8")
        report: dict = {}
        rc = cmd_install_ci(argparse.Namespace(repo=str(tmp_path)), report=report)
        assert rc == 0  # returns 0 even though parked — the trap B2 surfaces
        assert report["ci_gate_active"] is False
        assert wf.read_text(encoding="utf-8") == before, "host workflow clobbered"
        assert wf.with_name("harness-guard.yml.new").exists(), "gate not parked in .new"


class TestInstallCiReseedNonFatal:
    """TP-191 M4: the best-effort integrity reseed must not turn a SUCCESSFUL
    install-ci into a false 'CI not installed' rc=1. write_manifest does raw
    filesystem work (mkdir/open/atomic-replace/flock) that genuinely raises
    OSError; unwrapped, that error propagated through fuse.py and set
    ci_gate_active=False at the load-bearing PR-guarantee step even though the
    gate files were already deployed."""

    def test_install_ci_returns_zero_when_reseed_raises(
        self, tmp_path, monkeypatch, capsys
    ):
        from espalier import cli

        # Pre-seed the manifest so the reseed branch is actually reached
        # (it only reseeds when .espalier/integrity.json already exists).
        (tmp_path / ".espalier").mkdir(parents=True)
        (tmp_path / ".espalier" / "integrity.json").write_text("{}", encoding="utf-8")

        class _RaisingIntegrity:
            def write_manifest(self, *a, **k):
                raise OSError("simulated disk-full during reseed")

        monkeypatch.setattr(cli, "load_integrity_module", lambda: _RaisingIntegrity())

        report: dict = {}
        rc = cli.cmd_install_ci(argparse.Namespace(repo=str(tmp_path)), report=report)

        # Earn-the-red: unwrapped, the OSError propagated out of a SUCCESSFUL
        # install-ci instead of returning 0.
        assert rc == 0, "a best-effort reseed OSError falsely failed install-ci"
        assert report["ci_gate_active"] is True, (
            "gate marked inactive despite a successful deploy"
        )
        err = capsys.readouterr().err
        assert "could not re-seed integrity manifest" in err
        assert "simulated disk-full during reseed" in err


class TestFuseRollback:
    """TP-184 B4: a mid-write fault into a PRE-EXISTING empty --out must restore
    it empty (not remove the operator-owned node, not leave it poisoned so the
    line-376 non-empty guard refuses the retry)."""

    def test_rollback_restores_preexisting_empty_out(self, tmp_path, monkeypatch):
        host = _make_host(tmp_path)
        out = tmp_path / "out"
        out.mkdir()  # operator pre-created an EMPTY out dir

        def boom(*a, **k):
            (out / "partial.txt").write_text("half-built", encoding="utf-8")
            raise RuntimeError("simulated mid-write fault")

        monkeypatch.setattr(fuse, "_copy", boom)
        with pytest.raises(RuntimeError):
            fuse.fuse_repos(host, out, dry_run=False, run_init=False)
        assert out.exists(), "fuse removed the operator's pre-existing out dir"
        assert not any(out.iterdir()), "out left poisoned; a retry would be blocked"


class TestFuseSymlinkFallback:
    """TP-184 B11: a host-tracked symlink that cannot be recreated (privilege-less
    Windows -> OSError/WinError 1314) must fall back to a dereferenced regular-file
    copy + WARN, not abort the whole fusion."""

    @requires_symlink
    def test_symlink_copy_falls_back_on_oserror(self, tmp_path, monkeypatch, capsys):
        src_root = tmp_path / "src"
        src_root.mkdir()
        (src_root / "real.txt").write_text("payload", encoding="utf-8")
        (src_root / "link.txt").symlink_to("real.txt")  # relative symlink
        out = tmp_path / "out"

        real_copy2 = fuse.shutil.copy2

        def fake_copy2(s, d, *, follow_symlinks=True):
            # Simulate WinError 1314: only symlink RECREATION fails; regular-file
            # copy (and dereferencing follow_symlinks=True) succeed.
            if not follow_symlinks and Path(s).is_symlink():
                raise OSError(1314, "A required privilege is not held by the client")
            return real_copy2(s, d, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(fuse.shutil, "copy2", fake_copy2)
        n = fuse._copy(src_root, ["real.txt", "link.txt"], out)  # must NOT raise
        assert n == 2
        assert (out / "real.txt").read_text(encoding="utf-8") == "payload"
        assert (out / "link.txt").exists()
        assert not (out / "link.txt").is_symlink(), "fallback should be a regular file"
        assert (out / "link.txt").read_text(encoding="utf-8") == "payload"
        assert "could not recreate symlink" in capsys.readouterr().err

    @requires_symlink
    def test_symlink_dereference_failure_propagates(self, tmp_path, monkeypatch):
        """TP-184 B11 (adversarial follow-up): if BOTH the symlink recreation AND
        the dereferenced-copy fallback fail (e.g. disk full / dangling target),
        _copy must PROPAGATE the OSError so fuse_repos rolls back — never silently
        skip the file and ship an incomplete tree."""
        src_root = tmp_path / "src"
        src_root.mkdir()
        (src_root / "real.txt").write_text("payload", encoding="utf-8")
        (src_root / "link.txt").symlink_to("real.txt")
        out = tmp_path / "out"

        def all_symlink_copies_fail(s, d, *, follow_symlinks=True):
            # Simulate a non-privilege fault (ENOSPC): every copy of the symlink
            # source fails, both the link-preserving and the dereferencing call.
            if Path(s).is_symlink():
                raise OSError(28, "No space left on device")
            return fuse.shutil.copyfile(s, d)

        monkeypatch.setattr(fuse.shutil, "copy2", all_symlink_copies_fail)
        with pytest.raises(OSError):
            fuse._copy(src_root, ["link.txt"], out)


class TestMatchesPredicate:
    """TP-224 (TQ-coverage-engine-3): ``_matches`` must honor its docstring
    contract — a file pattern (no trailing slash) matches by EQUALITY, a dir
    pattern (trailing slash) matches by prefix. Pre-224 the file branch used
    ``startswith`` and over-matched a sibling sharing the prefix, leaking a
    stray ``.bak``/``.swp`` into the fusion overlay."""

    def test_file_pattern_does_not_overmatch_sibling(self):
        from espalier import fuse
        assert fuse._matches("foo/run.py", ("foo/run.py",)) is True
        assert fuse._matches("foo/run.py.bak", ("foo/run.py",)) is False
        assert fuse._matches("foo/run.pyc", ("foo/run.py",)) is False
        from espalier import fusion_manifest as fm
        assert fuse._matches("bench/run_benchmark.py", fm.HARNESS_INCLUDE) is True
        assert fuse._matches("bench/run_benchmark.py.bak", fm.HARNESS_INCLUDE) is False
        assert fuse._matches("docs/FAILURE_MODES.md.swp", fm.HARNESS_INCLUDE) is False
        assert fuse._should_overlay("bench/run_benchmark.py") is True
        assert fuse._should_overlay("bench/run_benchmark.py.bak") is False

    def test_dir_pattern_still_prefix_matches(self):
        from espalier import fuse
        assert fuse._matches("foo", ("foo/",)) is True
        assert fuse._matches("foo/bar.py", ("foo/",)) is True
        assert fuse._matches("foobar/x.py", ("foo/",)) is False


class TestFuseEpilogueOnAnUnparseableSettings:
    """DEF-732: the epilogue's parse of the fused settings.json and its call
    to the merge-refusal classifier shared one try, parse first, so on the
    one file the classifier exists to describe the parse raised, the except
    reset the verdict, and the banner offered `merge-settings` -- which
    refuses that file whole (and `--wire-hooks`, which runs the same merge).
    Driven on the Windows host (walk 2, W2-33): init's own narration printed
    the withheld remedy and this banner the wrong offer fifty lines later.
    Both offer arms are driven: the CI-gate WARNING and the plain one."""

    @staticmethod
    def _report(out, *, ci_gate_active: bool) -> dict:
        return {
            "dry_run": False, "out": str(out), "host_files": 3,
            "host_is_git": True, "history_preserved": True,
            "harness_overlaid": 100, "harness_via_init": 50, "init_rc": 0,
            "ci_gate_active": ci_gate_active,
        }

    @staticmethod
    def _args(tmp_path, out):
        return argparse.Namespace(host=str(tmp_path), out=str(out),
                                  fresh=False, dry_run=False, no_init=False)

    @pytest.mark.parametrize("ci_gate_active", [True, False])
    def test_the_offer_is_withheld_not_reworded(
        self, tmp_path, monkeypatch, capsys, ci_gate_active,
    ):
        out = tmp_path / "f"
        (out / ".claude").mkdir(parents=True)
        # Truncated mid-array: the shape the Windows walk drove.
        (out / ".claude" / "settings.json").write_bytes(b'{"hooks": {"PreToolUse": [')
        monkeypatch.setattr(
            fuse, "fuse_repos",
            lambda *a, **k: self._report(out, ci_gate_active=ci_gate_active),
        )
        fuse.cmd_fuse(self._args(tmp_path, out))
        printed = capsys.readouterr().out
        assert "does not parse" in printed, printed
        assert "merge-settings .   (or re-fuse with --wire-hooks)" not in printed, printed
        assert "merge-settings .` inside the fusion" not in printed, printed
        assert "harness is live" not in printed.lower()
