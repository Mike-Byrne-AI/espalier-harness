"""TP-345 1-B: session_start's load-bearing-tool banner (ruff) is self-host-gated.

Guards the adopter-friction parity between the SessionStart banner and the
``doctor`` command: ruff ships only in espalier's own dev-extras and its CI lint
gate is ``if: is_source == 'true'``, so a ruff-less ``pip install`` adopter has no
ruff gate and must not be nagged at every session boot. This pins the gate that
prevents that nag while preserving the self-host signal — because a self-host-only
warning that degrades to friction on an adopter's machine is a regression, not a
banner. Mirrors the doctor-side gate so the two sides tell one story.
"""
from __future__ import annotations

import io
import shutil
import sys
from contextlib import redirect_stderr
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


def _warn_stderr(self_host: bool, monkeypatch) -> str:
    """Call the banner with ruff stubbed absent; return captured stderr.

    The function does ``import shutil as _shutil`` then ``_shutil.which(tool)``;
    patching ``shutil.which`` on the shared module object reaches it.
    """
    ss = _import_session_start()
    monkeypatch.setattr(shutil, "which", lambda name: None)  # ruff absent on PATH
    buf = io.StringIO()
    with redirect_stderr(buf):
        ss._warn_if_load_bearing_tool_missing(self_host)
    return buf.getvalue()


class TestSessionStartRuffGate:
    def test_adopter_context_suppresses_ruff_banner(self, monkeypatch):
        """1-B earn-the-red: a non-self-host adopter (self_host=False) with ruff
        absent must get NO ruff banner. RED before the gate: the ungated function
        warned regardless of context, nagging every ruff-less adopter at boot.
        GREEN after: the early-return suppresses it."""
        out = _warn_stderr(self_host=False, monkeypatch=monkeypatch)
        assert "ruff" not in out, (
            f"ruff banner leaked to a non-self-host adopter (self_host=False): {out!r}"
        )

    def test_self_host_still_warns(self, monkeypatch):
        """The gate must not silence the self-host signal: with ruff absent on the
        self-host repo the lint gate is load-bearing, so the banner is real signal
        and must remain."""
        out = _warn_stderr(self_host=True, monkeypatch=monkeypatch)
        assert "ruff" in out and "[WARN]" in out, (
            f"self-host repo lost its ruff-absent banner (self_host=True): {out!r}"
        )


# ─── DEF-1122: an adopter whose tree declares ruff is told it is missing ─────

import inspect  # noqa: E402

import pytest  # noqa: E402


def _warn_for(root: Path, monkeypatch, self_host: bool = False) -> str:
    """The banner for ``root`` with ruff stubbed absent; asserts first that the
    function reads the tree (before DEF-1122 it took the self-host flag alone,
    so an adopter's declaration could not reach it)."""
    ss = _import_session_start()
    params = inspect.signature(ss._warn_if_load_bearing_tool_missing).parameters
    assert "root" in params, "the load-bearing-tool banner never reads the tree it runs on"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    buf = io.StringIO()
    with redirect_stderr(buf):
        ss._warn_if_load_bearing_tool_missing(self_host, root=root)
    return buf.getvalue()


# One row per way a tree can declare ruff, or not (analyze.ruff_is_declared's
# reading: a mention in pyproject.toml, or a ruff.toml / .ruff.toml beside it).
_DECLARATIONS = {
    "tool_table": {"pyproject.toml": "[project]\nname = \"app\"\n\n[tool.ruff]\nline-length = 100\n"},
    "dev_requirement": {"pyproject.toml": "[project]\nname = \"app\"\n[project.optional-dependencies]\ndev = [\"ruff>=0.5\"]\n"},
    "ruff_toml": {"ruff.toml": "line-length = 100\n"},
    "dot_ruff_toml": {".ruff.toml": "line-length = 100\n"},
    "none": {"pyproject.toml": "[project]\nname = \"app\"\n"},
    "no_python_at_all": {"package.json": "{\"name\": \"app\"}\n"},
    "a_directory_named_ruff_toml": {"ruff.toml/keep": ""},
    # Declared, yet /preflight lints another way (the failure-mode review).
    "makefile_lint": {"ruff.toml": "line-length = 100\n", "Makefile": "lint:\n\tuv run ruff check .\n"},
    "package_lint": {"ruff.toml": "line-length = 100\n", "package.json": "{\"scripts\": {\"lint\": \"eslint .\"}}\n"},
    "declared_uv_ruff": {"ruff.toml": "", "espalier.toml": "[extra_actions]\nlint = [\"uv run ruff check .\"]\n"},
    "lint_suppressed": {"ruff.toml": "", "espalier.toml": "suppress_actions = [\"lint\"]\n"},
    # Declared in espalier.toml, with no ruff configuration at all.
    "declared_ruff": {"espalier.toml": "[extra_actions]\nlint = [\"ruff check src\"]\n"},
}

# Whether /preflight runs ruff from PATH on each tree above.
_RUNS_RUFF = {"tool_table", "dev_requirement", "ruff_toml", "dot_ruff_toml", "declared_ruff"}


def _tree(tmp_path: Path, files: dict) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


class TestAnAdopterThatDeclaresRuffIsWarned:
    """DEF-1122: doctor and the SessionStart banner checked the load-bearing
    tools on the source repository alone, so an adopter whose lint step runs
    ruff (/preflight runs it where the tree declares it) lost the binary with
    no word from either surface."""

    @pytest.mark.parametrize("name", sorted(_RUNS_RUFF))
    def test_the_banner_warns_an_adopter_that_declares_ruff(self, tmp_path, monkeypatch, name):
        out = _warn_for(_tree(tmp_path, _DECLARATIONS[name]), monkeypatch)
        assert "[WARN] ruff not on PATH" in out, out
        assert "pip install -e" not in out, f"the source repo's dev-extra hint reached an adopter: {out!r}"

    @pytest.mark.parametrize("name", sorted(set(_DECLARATIONS) - _RUNS_RUFF))
    def test_the_banner_stays_quiet_for_an_adopter_that_declares_none(self, tmp_path, monkeypatch, name):
        assert _warn_for(_tree(tmp_path, _DECLARATIONS[name]), monkeypatch) == ""

    def test_doctor_warns_an_adopter_that_declares_ruff(self, tmp_path, monkeypatch):
        from espalier import doctor as d

        reader = getattr(d, "_load_bearing_tool_warnings", None)
        assert reader is not None, "doctor's load-bearing-tool loop reads no tree but the source repo"
        monkeypatch.setattr(shutil, "which", lambda name: None)
        warnings, steps = reader(_tree(tmp_path, _DECLARATIONS["tool_table"]))
        assert any("ruff" in w for w in warnings), warnings
        assert steps and all("pip install -e" not in s for s in steps), steps
        quiet, _ = reader(_tree(tmp_path / "plain", _DECLARATIONS["none"]))
        assert quiet == [], quiet

    @pytest.mark.parametrize("name", sorted(_DECLARATIONS))
    def test_the_hook_twin_reads_a_declaration_as_the_engine_does(self, tmp_path, name):
        from espalier import analyze

        ss = _import_session_start()
        twin = getattr(ss, "_ruff_is_declared", None)
        assert twin is not None, "session_start has no reading of a ruff declaration"
        root = _tree(tmp_path, _DECLARATIONS[name])
        assert twin(root) == analyze.ruff_is_declared(root), name

    @pytest.mark.parametrize("name", sorted(_DECLARATIONS))
    def test_the_hook_reads_what_preflight_runs_as_doctor_does(self, tmp_path, name):
        """The hook's twin of /preflight's lint resolution against the engine's
        own (``harness_config.declared_action``, which doctor reads)."""
        from espalier import doctor

        ss = _import_session_start()
        root = _tree(tmp_path, _DECLARATIONS[name])
        engine = doctor._adopter_ruff_relevance(root)
        assert engine == (name in _RUNS_RUFF), name
        assert ss._preflight_runs_ruff(root) == engine, name

    def test_the_two_relevance_tables_name_the_same_tools(self):
        """A tool given an adopter row on one surface only would be warned
        about by doctor and never by the banner, or the reverse."""
        from espalier import doctor

        ss = _import_session_start()
        assert set(ss._ADOPTER_TOOL_RELEVANCE) == set(doctor._ADOPTER_TOOL_RELEVANCE)
        assert set(doctor._ADOPTER_TOOL_RELEVANCE) <= set(doctor._LOAD_BEARING_EXTERNAL_TOOLS)
