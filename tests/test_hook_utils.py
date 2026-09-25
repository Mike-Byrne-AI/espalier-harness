"""Unit tests for ``tools/cc/hooks/_hook_utils.py`` — the shared
helper module every governance hook imports for path normalization,
mutation-tool detection, and the TP-76 ``is_self_host_repo`` 5-signal
layout check.

Pins the self-host predicate exactly: all five signals (``espalier/``
dir, ``tools/cc/`` dir, ``bench/`` dir, pyproject project-name
match, write_guard SHA-pinned first-200-bytes hash) must align or
the predicate reports False. Without this contract a hook fail-safe
gated on self-host could silently fire on an adopter repo (over-
reach) or fail to fire on the harness itself (under-reach), and
both modes corrupt cross-repo behavior in ways no other test catches.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


def _make_self_host_layout(tmp_path: Path, name: str = "espalier-harness") -> None:
    """Create the layout required by the 5-signal `is_self_host_repo`:

      1. `espalier/` directory
      2. `tools/cc/` directory (and `tools/cc/hooks/` for the write_guard copy)
      3. `bench/` directory
      4. `pyproject.toml` with the given project name
      5. `tools/cc/hooks/write_guard.py` whose first 200 bytes hash to
         the pinned SHA (TP-76) — copied from the live repo so the SHA matches.

    Tests that target a specific failure mode override one signal at a
    time on top of this baseline (e.g., `test_user_repo_not_detected`
    overwrites only the pyproject `name`).
    """
    import shutil
    (tmp_path / "espalier").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "bench").mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOKS_DIR / "write_guard.py", tmp_path / "tools" / "cc" / "hooks" / "write_guard.py")
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")


class TestIsSelfHostRepo:
    def test_self_host_pyproject_detected(self, tmp_path: Path) -> None:
        _make_self_host_layout(tmp_path, "espalier-harness")
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is True

    def test_underscore_form_detected(self, tmp_path: Path) -> None:
        _make_self_host_layout(tmp_path, "espalier_harness")
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is True

    def test_user_repo_not_detected(self, tmp_path: Path) -> None:
        _make_self_host_layout(tmp_path, "user-app")
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is False

    def test_no_pyproject_returns_false(self, tmp_path: Path) -> None:
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is False

    def test_user_repo_with_espalier_harness_dependency_is_not_self_host(
        self, tmp_path: Path
    ) -> None:
        """Regression: a user repo declaring espalier-harness as a dependency
        is NOT a self-host repo.

        Pre-fix bug: substring match on pyproject.toml text would fire on
        `dependencies = ["espalier-harness>=1.0"]`, causing the user's own
        `espalier/` directory (if any) to be silently protected. The proper
        TOML name parser only matches the project's own `name = "..."`.
        """
        (tmp_path / "espalier").mkdir(parents=True)
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "user-app"\n'
            'dependencies = ["espalier-harness>=1.0", "espalier_harness-extras"]\n', encoding="utf-8",
        )
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is False

    def test_poetry_form_self_host_detected(self, tmp_path: Path) -> None:
        """Poetry-style [tool.poetry] section is also recognized."""
        _make_self_host_layout(tmp_path)
        # Overwrite the [project]-style pyproject with [tool.poetry] form;
        # the other 4 signals stay satisfied via the helper baseline.
        (tmp_path / "pyproject.toml").write_text(
            '[tool.poetry]\nname = "espalier-harness"\nversion = "1.0"\n', encoding="utf-8",
        )
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is True

    def test_name_in_dependency_line_does_not_match(self, tmp_path: Path) -> None:
        """Edge case: a `name = "espalier-harness"` literal in a non-target
        section (e.g., a pre-commit hook config) must not match."""
        (tmp_path / "espalier").mkdir(parents=True)
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "user-app"\n\n'
            '[tool.somelinter]\n'
            'name = "espalier-harness"\n', encoding="utf-8",
        )
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is False

    def test_espalier_harness_name_without_dirs_is_not_self_host(
        self, tmp_path: Path
    ) -> None:
        """Regression: a repo named `espalier-harness` in pyproject.toml but
        WITHOUT espalier/ + tools/cc/ directories is NOT a self-host repo.

        This mirrors the canonical predicate in
        `espalier/surface_contract.py:is_self_host_repo` which requires the
        directory pre-checks. Without them, a user could create a fresh
        directory, write pyproject.toml with name="espalier-harness", and
        flip the hook into self-host mode without actually being the harness.
        """
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8"
        )
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is False

    def test_missing_tools_cc_dir_is_not_self_host(self, tmp_path: Path) -> None:
        """`espalier/` exists but `tools/cc/` doesn't — still not self-host."""
        (tmp_path / "espalier").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8"
        )
        from _hook_utils import is_self_host_repo
        assert is_self_host_repo(tmp_path) is False


class TestHarnessProtectedPrefixes:
    def test_self_host_includes_espalier(self, tmp_path: Path) -> None:
        _make_self_host_layout(tmp_path, "espalier-harness")
        from _hook_utils import harness_protected_prefixes
        assert "espalier/" in harness_protected_prefixes(tmp_path)

    def test_user_repo_excludes_espalier(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "user-app"\n', encoding="utf-8")
        from _hook_utils import harness_protected_prefixes
        assert "espalier/" not in harness_protected_prefixes(tmp_path)

    def test_universal_prefixes_present_in_both(self, tmp_path: Path) -> None:
        from _hook_utils import harness_protected_prefixes
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "user-app"\n', encoding="utf-8")
        prefixes = harness_protected_prefixes(tmp_path)
        for p in ["tools/cc/", "cc/"]:
            assert p in prefixes
        # W4-1: .github/workflows/ is self-host-only as a write_guard prefix
        # (adopters own their CI); only harness-guard.yml stays protected via
        # PROTECTED_FILES. It must NOT be in the adopter prefix set.
        assert ".github/workflows/" not in prefixes

    def test_github_workflows_prefix_is_self_host_only(self, tmp_path: Path) -> None:
        """W4-1: the full .github/workflows/ tree is a write_guard prefix only
        on the self-host repo; an adopter only has harness-guard.yml protected
        (exact, via PROTECTED_FILES)."""
        _make_self_host_layout(tmp_path, "espalier-harness")
        from _hook_utils import harness_protected_prefixes
        assert ".github/workflows/" in harness_protected_prefixes(tmp_path)

    def test_self_host_set_parity_with_engine_sot(self, tmp_path: Path) -> None:
        """TP-176 W4-2: on self-host the hook-side prefix set must EQUAL the
        engine SoT (surface_contract.get_protected_mutation_prefixes). The
        docstring claims the two mirror, but nothing pinned set-equality — a
        new member added to the engine SoT would silently fail to propagate
        to write_guard's protected-zone denial."""
        _make_self_host_layout(tmp_path, "espalier-harness")
        from _hook_utils import harness_protected_prefixes
        from espalier.surface_contract import get_protected_mutation_prefixes
        assert set(harness_protected_prefixes(tmp_path)) == set(
            get_protected_mutation_prefixes()
        )

    def test_user_repo_set_parity_minus_espalier(self, tmp_path: Path) -> None:
        """On an adopter repo, the session-side write_guard prefix set is the
        engine SoT minus the two self-host-only prefixes: espalier/ (potential
        user code) and .github/workflows/ (W4-1: adopters own their CI; only
        harness-guard.yml stays protected, via PROTECTED_FILES exact-match).
        The engine SoT / ci_guard still protect the whole workflows tree at the
        CI-merge layer — a separate, deliberate policy."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "user-app"\n', encoding="utf-8")
        from _hook_utils import harness_protected_prefixes
        from espalier.surface_contract import get_protected_mutation_prefixes
        assert set(harness_protected_prefixes(tmp_path)) == (
            set(get_protected_mutation_prefixes()) - {"espalier/", ".github/workflows/"}
        )


class TestHarnessExemptPrefixes:
    def test_self_host_exempts_espalier(self, tmp_path: Path) -> None:
        _make_self_host_layout(tmp_path, "espalier-harness")
        from _hook_utils import harness_exempt_prefixes
        assert "espalier/" in harness_exempt_prefixes(tmp_path)

    def test_user_repo_does_not_exempt_espalier(self, tmp_path: Path) -> None:
        """Critical regression: reviewer Finding 4 flagged this as the
        more dangerous half of the protection bug. A user repo with an
        espalier/ directory must NOT skip plan discipline."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "user-app"\n', encoding="utf-8")
        from _hook_utils import harness_exempt_prefixes
        assert "espalier/" not in harness_exempt_prefixes(tmp_path)


class TestHarnessExcludedPrefixes:
    def test_self_host_includes_source(self, tmp_path: Path) -> None:
        """On self-host, espalier/ and tools/cc/ ARE source — reflect
        should walk them."""
        _make_self_host_layout(tmp_path, "espalier-harness")
        from _hook_utils import harness_excluded_prefixes
        excluded = harness_excluded_prefixes(tmp_path)
        assert "espalier/" not in excluded
        assert "tools/cc/" not in excluded

    def test_user_repo_excludes_harness(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "user-app"\n', encoding="utf-8")
        from _hook_utils import harness_excluded_prefixes
        excluded = harness_excluded_prefixes(tmp_path)
        assert "espalier/" in excluded
        assert "tools/cc/" in excluded


# ── read_stdin_safely (post-v0.6.6 review followup) ──────────────────────────


import io  # noqa: E402  -- block-level imports here keep the helper-tests
            # self-contained without polluting the original file's import set


class _StdinShim:
    """Bytes-fed stdin shim with a ``.buffer`` attribute, like real stdin."""

    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


class TestReadStdinSafely:
    """Coverage gaps surfaced by the post-v0.6.6 multi-agent review.

    End-to-end behavior across all 10 hooks is in
    ``tests/test_hook_unicode_stdin.py``. This class pins the helper-
    level contract directly so refactors are caught at the unit level
    before the slower subprocess tests run.
    """

    def test_returns_empty_dict_for_json_list(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _StdinShim(b"[1,2,3]"))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_json_string(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _StdinShim(b'"hello"'))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_json_null(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _StdinShim(b"null"))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_json_number(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _StdinShim(b"42"))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_json_boolean(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", _StdinShim(b"true"))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_dict_for_dict_top_level(self, monkeypatch):
        """Happy path — a valid JSON object on stdin survives parsing."""
        monkeypatch.setattr(sys, "stdin", _StdinShim(b'{"tool_name":"Write"}'))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {"tool_name": "Write"}

    def test_strips_utf8_bom_via_utf_8_sig(self, monkeypatch):
        """UTF-8 BOM (``\\xef\\xbb\\xbf``) is silently stripped; dict survives."""
        payload = b"\xef\xbb\xbf" + b'{"tool_name":"Write"}'
        monkeypatch.setattr(sys, "stdin", _StdinShim(payload))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {"tool_name": "Write"}

    def test_utf16_le_bom_returns_empty_dict(self, monkeypatch):
        """``utf-8-sig`` strips ONLY the UTF-8 BOM. A UTF-16-LE BOM
        (``\\xff\\xfe``) is not valid UTF-8 — ``errors="replace"``
        produces gibberish that ``json.loads`` rejects, so the helper
        returns ``{}``. The BOM-bypass class stays closed for the
        UTF-16 variant: failure mode is silent-allow with empty ``{}``,
        not a crash."""
        payload = b"\xff\xfe" + b'{"tool_name":"Write"}'
        monkeypatch.setattr(sys, "stdin", _StdinShim(payload))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_utf16_be_bom_returns_empty_dict(self, monkeypatch):
        """Same as the LE case but UTF-16-BE BOM (``\\xfe\\xff``)."""
        payload = b"\xfe\xff" + b'{"tool_name":"Write"}'
        monkeypatch.setattr(sys, "stdin", _StdinShim(payload))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_when_stdin_buffer_absent(self, monkeypatch):
        """``io.StringIO`` (used in some test fixtures) has no ``.buffer``
        attribute. The helper catches ``AttributeError`` and returns
        ``{}`` instead of raising and crashing the hook."""
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"tool_name":"Write"}'))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_empty_bytes(self, monkeypatch):
        """Empty stdin produces ``b""`` from ``read()``; helper short-circuits."""
        monkeypatch.setattr(sys, "stdin", _StdinShim(b""))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_whitespace_only(self, monkeypatch):
        """Whitespace-only stdin parses to nothing; ``json.loads`` raises
        and the helper returns ``{}``."""
        monkeypatch.setattr(sys, "stdin", _StdinShim(b"   \n\t  "))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}

    def test_returns_empty_dict_for_malformed_json(self, monkeypatch):
        """Truncated / missing-brace JSON returns ``{}``."""
        monkeypatch.setattr(sys, "stdin", _StdinShim(b'{"tool_name":"Write"'))
        from _hook_utils import read_stdin_safely
        assert read_stdin_safely() == {}


# ── protected-zone doc parity (self-host only) ───────────────────────────────

import pytest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every doc line that ENUMERATES SPECIFIC protected zones, keyed by a stable
# anchor substring. Prose that says "protected zones" generically is accurate
# by construction and deliberately not listed here.
#
# These enumerations were hand-maintained and drifted from the code SoT
# (`_hook_utils.harness_protected_prefixes` + `_protected_zones.PROTECTED_FILES`):
# they overstated a bare `.claude/` (only the two settings files are protected),
# understated `tools/cc/hooks/` (the whole `tools/cc/` tree is), and omitted
# `cc/`. Nothing pinned them to the code, so the drift silently misinformed a
# pack author. This class is that pin.
# Each entry is (path, anchor, end_marker). ``end_marker`` is None for a
# single-line enumeration (a markdown table row); otherwise the block runs from
# the anchor line up to — and excluding — the first later line containing it.
_DOC_ENUMERATION_SITES = [
    ("CLAUDE.md", "protected harness zones", None),
    ("docs/SECURITY_TAXONOMY.md", "Hard-deny on mutations (a write, a delete, a move) of harness machinery", None),
    ("docs/SURFACE_SUPPORT_MATRIX.md", "hard-blocked unless", None),
    ("docs/HOOKS.md", "**Protected-zone mutations.**", "3. **Dangerous commands.**"),
    ("docs/TROUBLESHOOTING.md", "protected harness zones", "The block is mechanical"),
    ("docs/POSITIONING.md", "hard-blocks mutations (a write, a delete, a move) of protected harness paths", "- `plan_guard.py`"),
]

# Prefixes that protect ONLY on the self-host repo. An adopter owns their engine
# source and their CI, so a doc naming these without the qualifier tells them
# their own files are blocked when they are not — the false-positive-on-user-code
# failure that `harness_protected_prefixes`' W4-1 split exists to avoid.
_SELF_HOST_ONLY_PREFIXES = ("espalier/", ".github/workflows/")

# Sites that cite the ENGINE-side declaration `get_protected_mutation_prefixes()`
# — context-free, always all four zones — NOT the self-host-gated runtime
# `harness_protected_prefixes()`. Pinned to the engine tuple and deliberately kept
# OUT of `_DOC_ENUMERATION_SITES`: the engine declaration names every zone
# unconditionally, so the self-host-qualifier arm would wrongly red on it. The
# tuple wraps onto its own line in the doc, so block-span it via (anchor,
# end_marker) rather than a single-line anchor that the per-line matcher can't reach.
_ENGINE_SOT_ENUMERATION_SITES = [
    ("docs/CONVENTIONS.md", "`get_protected_mutation_prefixes`", "is_self_host_repo"),
]

import re  # noqa: E402

# ── closed-world (doc ⊆ code) support ────────────────────────────────────────
# A backticked token is "path-shaped" if it names a path: contains a "/", is not a
# slash-command (`/status`), and is not an ellipsis-truncated illustrative token
# (`.claude/…`). Bare trailing-slash dir names (`cc/`, `hooks/`, a fabricated
# `reports/`) ARE path-shaped and DO get checked — narrowing this to require an
# interior slash would exclude a fabricated bare zone and defeat the arm.
_BACKTICK_TOKEN_RE = re.compile(r"`([^`\s]+)`")


def _path_shaped(tok: str) -> bool:
    if "…" in tok or "..." in tok:            # illustrative truncation, not a real path
        return False
    return "/" in tok and not tok.startswith("/")   # leading-slash-only => slash-command


# Paths a registered enumeration block legitimately names as explicitly NOT
# protected (so a reader knows they stay editable) and which are not already in the
# code SoT union. CALIBRATED to 0 false-positives over the corrected tree (every
# path-shaped token in all six blocks lands in the union). Do NOT pad this — every
# entry weakens the closed-world guarantee by exactly one path.
_CLOSED_WORLD_NONZONE_ALLOWLIST = {
    ".claude/commands/",                      # HOOKS.md: freely-editable .claude subtree
    # `.claude/` subdirs named as freely-editable in the HOOKS.md line-303 block:
    "skills/", "agents/", "workflows/",
    # `hooks/` is different: it appears only in "the whole tree, not just `hooks/`"
    # (shorthand for tools/cc/hooks/ in the PROTECTED bullet). Still a literal
    # token that must be allowed, but not a .claude subdir — grouped honestly so a
    # future recalibration doesn't drop it thinking it's a .claude name.
    "hooks/",
}


def _allowed_zone_union() -> set[str]:
    """Real protected zones (runtime ∪ engine) ∪ exact protected files ∪
    allowed-in-protected exceptions ∪ the calibrated named-as-not-protected
    allowlist. A fabricated zone (`reports/`, `bench/`) is in none of these."""
    from _hook_utils import harness_protected_prefixes
    from _protected_zones import ALLOWED_IN_PROTECTED, PROTECTED_FILES
    from espalier.surface_contract import get_protected_mutation_prefixes
    union = set(harness_protected_prefixes(REPO_ROOT))
    union |= set(get_protected_mutation_prefixes())
    union |= set(PROTECTED_FILES)
    union |= set(ALLOWED_IN_PROTECTED)
    union |= _CLOSED_WORLD_NONZONE_ALLOWLIST
    return union


def _enumeration_block(rel_path: str, anchor: str, end_marker: str | None) -> list[str]:
    """The doc lines enumerating protected zones, or [] if the anchor moved."""
    lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if anchor in line:
            if end_marker is None:
                return [line]
            for j in range(i + 1, len(lines)):
                if end_marker in lines[j]:
                    return lines[i:j]
            return lines[i:]
    return []


def _enumeration_line(rel_path: str, anchor: str, end_marker: str | None) -> str:
    """The enumeration block flattened to one string for substring checks."""
    return "\n".join(_enumeration_block(rel_path, anchor, end_marker))


from _hook_utils import is_self_host_repo as _is_self_host_repo  # noqa: E402


@pytest.mark.skipif(
    not _is_self_host_repo(REPO_ROOT),
    reason="self-host only: the prefix set the docs describe is the self-host overlay",
)
class TestProtectedZoneDocParity:
    """Pin every specific protected-zone enumeration in the docs to the code SoT.

    Scope, honestly: this pins the KNOWN enumeration sites listed in
    ``_DOC_ENUMERATION_SITES``. It catches a hand-edit that rots an existing
    enumeration — the failure that actually occurred — but a *newly authored*
    doc that enumerates zones wrongly is not caught until its line is added
    here. A tree-wide "does this prose enumerate zones?" detector was
    considered and rejected: generic "protected zones" phrasing is both common
    and correct, so the detector would be a false-positive machine.
    """

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _DOC_ENUMERATION_SITES)
    def test_doc_names_every_live_protected_prefix(self, rel_path, anchor, end_marker) -> None:
        from _hook_utils import harness_protected_prefixes
        row = _enumeration_line(rel_path, anchor, end_marker)
        assert row, (
            f"{rel_path}: protected-zone enumeration anchored on {anchor!r} not found "
            "(did the wording move? re-anchor _DOC_ENUMERATION_SITES)"
        )
        for prefix in harness_protected_prefixes(REPO_ROOT):
            assert f"`{prefix}`" in row, (
                f"{rel_path} omits the live protected prefix {prefix!r} "
                "(SoT: _hook_utils.harness_protected_prefixes)"
            )

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _DOC_ENUMERATION_SITES)
    def test_doc_names_every_live_protected_file(self, rel_path, anchor, end_marker) -> None:
        """The exact-match protections are half the SoT and apply on EVERY repo.
        Without this arm a doc could silently drop `.claude/settings.local.json`
        or `.espalier/freshness.json` and the prefix arm would still pass."""
        from _protected_zones import PROTECTED_FILES
        row = _enumeration_line(rel_path, anchor, end_marker)
        assert row, f"{rel_path}: enumeration anchored on {anchor!r} not found"
        for protected_file in sorted(PROTECTED_FILES):
            assert f"`{protected_file}`" in row, (
                f"{rel_path} omits the live protected file {protected_file!r} "
                "(SoT: _protected_zones.PROTECTED_FILES)"
            )

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _DOC_ENUMERATION_SITES)
    def test_doc_qualifies_the_self_host_only_prefixes(self, rel_path, anchor, end_marker) -> None:
        """`espalier/` and `.github/workflows/` protect ONLY on the self-host
        repo. Naming them without the qualifier tells an adopter their own
        engine source and CI are blocked when they are not — so require the
        qualifier on the same LINE as the token, not merely somewhere nearby."""
        block = _enumeration_block(rel_path, anchor, end_marker)
        assert block, f"{rel_path}: enumeration anchored on {anchor!r} not found"
        for prefix in _SELF_HOST_ONLY_PREFIXES:
            bearing = [ln for ln in block if f"`{prefix}`" in ln]
            assert bearing, (
                f"{rel_path} omits the self-host-only prefix {prefix!r}"
            )
            for line in bearing:
                assert "self-host" in line, (
                    f"{rel_path} names {prefix!r} without the 'self-host' qualifier "
                    f"on the same line — an adopter reads it as blocked on their "
                    f"repo, but harness_protected_prefixes() omits it there. Line: {line!r}"
                )

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _DOC_ENUMERATION_SITES)
    def test_doc_does_not_overstate_dot_claude(self, rel_path, anchor, end_marker) -> None:
        """Only `.claude/settings{,.local}.json` are protected — commands/,
        skills/, workflows/ and agents/ are freely editable. A bare `.claude/`
        in an enumeration tells a reader (or a pack author) the opposite."""
        row = _enumeration_line(rel_path, anchor, end_marker)
        assert row, f"{rel_path}: enumeration anchored on {anchor!r} not found"
        assert "`.claude/`" not in row, (
            f"{rel_path} lists a bare `.claude/` as protected, but only "
            ".claude/settings.json and .claude/settings.local.json are "
            "(SoT: _protected_zones.PROTECTED_FILES)"
        )

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _DOC_ENUMERATION_SITES)
    def test_doc_does_not_understate_tools_cc(self, rel_path, anchor, end_marker) -> None:
        """`tools/cc/hooks/` is a sub-path of the real prefix `tools/cc/`;
        naming the narrower path implies the rest of the tree is writable."""
        row = _enumeration_line(rel_path, anchor, end_marker)
        assert row, f"{rel_path}: enumeration anchored on {anchor!r} not found"
        assert "`tools/cc/hooks/`" not in row, (
            f"{rel_path} names `tools/cc/hooks/` as the protected zone; the live "
            "prefix is the whole `tools/cc/` tree "
            "(SoT: _hook_utils.harness_protected_prefixes)"
        )

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _ENGINE_SOT_ENUMERATION_SITES)
    def test_doc_names_full_engine_sot_tuple(self, rel_path, anchor, end_marker) -> None:
        """CONVENTIONS.md cites `get_protected_mutation_prefixes()` — the ENGINE
        declaration, all four zones unconditionally. The tuple is a verbatim code
        mirror, so pin it with SET EQUALITY: the doc must name every real zone AND
        no fabricated one. The closed-world token arm below cannot cover this site —
        the tuple is one backticked span `("...", ...)` with spaces inside, from
        which `_BACKTICK_TOKEN_RE` extracts nothing — so the absence half (a
        hand-edit adding a stale `"reports/"` beside the real four) is enforced HERE,
        against the double-quoted tuple entries, not deferred to that arm."""
        from espalier.surface_contract import get_protected_mutation_prefixes
        row = _enumeration_line(rel_path, anchor, end_marker)
        assert row, f"{rel_path}: engine-SoT enumeration anchored on {anchor!r} not found"
        quoted = {t for t in re.findall(r'"([^"]+)"', row) if _path_shaped(t)}
        assert quoted == set(get_protected_mutation_prefixes()), (
            f"{rel_path} engine-SoT tuple {sorted(quoted)} != code SoT "
            f"{sorted(get_protected_mutation_prefixes())} "
            "(SoT: surface_contract.get_protected_mutation_prefixes) — a missing zone "
            "OR a fabricated one both red this closed-world set-equality pin"
        )

    def test_self_host_only_prefixes_match_sot(self, tmp_path: Path) -> None:
        """`_SELF_HOST_ONLY_PREFIXES` must equal the prefixes that appear ONLY on
        the self-host overlay: harness_protected_prefixes(self_host) − (user_repo).
        A hardcoded copy silently drifts — the exact hand-maintained-list class this
        whole file forecloses, one level up. Derive-and-assert rather than trust."""
        from _hook_utils import harness_protected_prefixes
        self_host = harness_protected_prefixes(REPO_ROOT)      # REPO_ROOT is self-host
        user_repo = harness_protected_prefixes(tmp_path)       # bare dir -> universal only
        derived = tuple(p for p in self_host if p not in user_repo)
        assert set(_SELF_HOST_ONLY_PREFIXES) == set(derived), (
            f"_SELF_HOST_ONLY_PREFIXES {_SELF_HOST_ONLY_PREFIXES} drifted from the SoT "
            f"difference {derived} (SoT: harness_protected_prefixes self-host minus user-repo)"
        )

    @pytest.mark.parametrize("rel_path,anchor,end_marker", _DOC_ENUMERATION_SITES)
    def test_doc_names_only_real_zones(self, rel_path, anchor, end_marker) -> None:
        """Closed-world (doc ⊆ code): every path-shaped backticked token in an
        enumeration block must be a real protected zone / file (or a calibrated
        named-as-not-protected path). Forecloses the fabricated-zone hole the
        presence-only arms leave open — proven at HEAD, injecting `reports/` into a
        block left every presence arm green. The engine-tuple site
        (`_ENGINE_SOT_ENUMERATION_SITES`) is deliberately NOT parametrized here: its
        enumeration is one backticked tuple literal `("...", ...)`, which the
        tokenizer would extract whole; `test_doc_names_full_engine_sot_tuple` pins
        it instead."""
        block = _enumeration_block(rel_path, anchor, end_marker)
        assert block, f"{rel_path}: enumeration anchored on {anchor!r} not found"
        allowed = _allowed_zone_union()
        for line in block:
            for tok in _BACKTICK_TOKEN_RE.findall(line):
                if "::" in tok:
                    # A pytest node id (`tests/x.py::Class::test`) names the row
                    # that pins a declared limit -- since 2026-09-22 every such
                    # sentence in docs/HOOKS.md carries one (TP-453 2-B) -- and
                    # is never a zone. Skipped by shape, not allowlisted by name.
                    continue
                if _path_shaped(tok):
                    assert tok in allowed, (
                        f"{rel_path} names `{tok}` as a protected zone, but it is not in "
                        f"the code SoT (harness_protected_prefixes ∪ engine tuple ∪ "
                        f"PROTECTED_FILES ∪ ALLOWED_IN_PROTECTED ∪ calibrated allowlist). "
                        f"Fabricated/stale zone, or add it to _CLOSED_WORLD_NONZONE_ALLOWLIST "
                        f"if it is a genuine named-as-not-protected path."
                    )


def test_hooks_md_postcompaction_sample_matches_adopter_runtime() -> None:
    """The docs/HOOKS.md §8 "What you see" sample must mirror the REAL adopter
    output of post_compact.py — not drift into stale self-host wording. It rotted
    for months (a `RULES: ... (tools/cc/, espalier/) are protected` box the runtime
    no longer emits — it now emits a `RESUME:` sentence) precisely because nothing
    pinned the sample to the runtime. Pinning it to the mirror alone would only
    make two copies agree on a wrong contract — the exact failure docs/external
    exists to prevent — so pin the sample to the runtime-emitted MARKERS (the
    RESUME sentence, the adopter `managed` phrase, the BC-033 `bp=<sid>/d<depth>`
    blueprint form, ASCII bars). This is a marker pin, not a live invocation: it
    catches the drift shapes that actually occur without importing the hook."""
    text = (REPO_ROOT / "docs/HOOKS.md").read_text(encoding="utf-8")
    idx = text.index("POST-COMPACTION CONTEXT")
    sample = text[text.rfind("```", 0, idx): text.index("```", idx)]
    assert "RESUME:" in sample and "RULES:" not in sample, (
        "HOOKS.md post-compaction sample uses a stale `RULES:` line; the runtime "
        "emits a `RESUME:` sentence (tools/cc/hooks/post_compact.py adopter branch)"
    )
    assert "tools/cc/ is harness-managed" in sample, (
        "sample must show the adopter form `tools/cc/ is harness-managed` "
        "(post_compact.py non-self-host branch)"
    )
    assert "espalier/" not in sample, (
        "sample names `espalier/`, but the runtime gates that to the self-host "
        "branch only — an adopter never sees it, so the generic sample must omit it"
    )
    assert "═" not in sample, "sample uses unicode box bars; the runtime emits ASCII `=`"
    # BC-033 typed blueprint form: _blueprint_summary emits `bp=<sid>/d<depth>`,
    # not the retired prose `Session <id> (depth <n>)`. The pin's first version
    # missed this line and green-stamped a stale sample — pin the marker now.
    assert "bp=" in sample and "/d" in sample, (
        "sample's Blueprint line must use the runtime `bp=<sid>/d<depth>` form "
        "(SoT: post_compact.py::_blueprint_summary), not prose `Session ... (depth ...)`"
    )
    assert "Session " not in sample and "(depth " not in sample, (
        "sample's Blueprint line still uses the retired `Session <id> (depth <n>)` "
        "wording; the runtime emits `bp=<sid>/d<depth>`"
    )


def test_hooks_md_reflect_trigger_sample_uses_ascii_bars() -> None:
    """Sibling of the post-compaction sample-pin: the docs/HOOKS.md §7 REFLECT
    TRIGGER "What you see" box must use ASCII `=` bars, matching what
    reflect_trigger.py actually prints (`=== REFLECT TRIGGER (auto) ===` + `"=" * 30`,
    deliberately ASCII "so log sinks that strip non-ASCII don't render the divider as
    garbage"). This box carried unicode `═══` rot — the identical failure two sections
    below in §8 — uncaught for the same reason: nothing pinned it to the runtime."""
    text = (REPO_ROOT / "docs/HOOKS.md").read_text(encoding="utf-8")
    idx = text.index("REFLECT TRIGGER (auto)")
    sample = text[text.rfind("```", 0, idx): text.index("```", idx)]
    assert "═" not in sample and "─" not in sample, (
        "HOOKS.md §7 REFLECT TRIGGER sample uses unicode box bars, but "
        "reflect_trigger.py emits ASCII `=` — the doc shows a format the hook never prints"
    )
    assert "=== REFLECT TRIGGER (auto) ===" in sample, (
        "sample header must match the runtime ASCII form `=== REFLECT TRIGGER (auto) ===`"
    )


def test_closed_world_predicate_flags_a_fabricated_zone() -> None:
    """Committed self-witness for the closed-world arm: a synthetic fabricated
    `reports/` MUST be flagged (path-shaped AND not in the allowed union). Makes the
    earn-the-red durable — if a future refactor neuters `_path_shaped` or auto-widens
    `_allowed_zone_union()`, THIS reds, rather than relying on a one-time manual
    injection. Also pins the two exemptions the arm depends on."""
    allowed = _allowed_zone_union()
    assert _path_shaped("reports/") and "reports/" not in allowed, (
        "closed-world predicate no longer flags a fabricated `reports/` — the arm "
        "has gone vacuous (check _path_shaped / _allowed_zone_union)"
    )
    assert _path_shaped("tools/cc/") and "tools/cc/" in allowed  # a real zone passes
    assert not _path_shaped("/status")          # slash-command, not a path
    assert not _path_shaped(".claude/…")        # ellipsis truncation, not a real path


def test_deny_string_enumeration_matches_sot() -> None:
    """Pin the PROTECTED_ZONE_WRITE illustrative enumeration to the code SoT the same
    way the six doc sites are — the one hand-typed protected-zone list the pack would
    otherwise leave un-pinned, so a future edit could silently reintroduce the bare
    `.claude/` / `tools/cc/hooks/` / `espalier/scanners/` mistake with nothing to
    catch it. Names only UNIVERSALLY-protected examples: `espalier/` is self-host-only
    (W4-1), so a generic deny message must not illustrate with it (adopter over-claim)."""
    import _denial_reasons
    msg = _denial_reasons.PROTECTED_ZONE_WRITE
    assert "`.claude/settings.json`" in msg, "deny string must name the exact settings file, not bare `.claude/`"
    assert "`tools/cc/`" in msg, "deny string must name the whole `tools/cc/` tree"
    for retired in ("`.claude/`,", "`tools/cc/hooks/`", "`espalier/scanners/`"):
        assert retired not in msg, f"deny string still names the retired/under-scoped token {retired!r}"
    assert "`espalier/`" not in msg, (
        "deny string illustrates with `espalier/`, but it protects only on the self-host "
        "repo (W4-1) — a generic deny message over-claims it to adopters"
    )


class TestWarnExcRendersThePathAsAPath:
    """DEF-799: `warn_exc` is the one reporter a hook hands an exception to,
    and it renders through `_json_safe.os_error_text`, so an OSError's path
    reaches stderr as a path -- not `'C:\\\\x'`. The AST pin in
    tests/test_portability_contract.py proves the CALL is in the body; this
    proves the rendering."""

    def test_an_oserror_path_is_not_reprd(self, capsys):
        from _hook_utils import warn_exc
        warn_exc("read failed", OSError(13, "Access is denied", r"C:\repo\x"))
        err = capsys.readouterr().err
        assert err == "[WARN] espalier: read failed: PermissionError: [Errno 13] Access is denied: C:\\repo\\x\n", err

    def test_a_non_oserror_is_unchanged(self, capsys):
        from _hook_utils import warn_exc
        warn_exc("parse failed", ValueError("bad"))
        assert capsys.readouterr().err == "[WARN] espalier: parse failed: ValueError: bad\n"


class TestPluralHelper:
    """`_hook_utils.plural` renders `<n> <word>`, pluralizing on the count.

    Intentional duplicate of `espalier._text.plural` (the `tools/cc/` import
    boundary forbids importing espalier — see the pack's do-not-dedup note), so
    it carries the same four edge-case pins as `espalier._text`'s TestPluralHelper.
    """

    def test_singular_at_one(self):
        from _hook_utils import plural
        assert plural(1, "warning") == "1 warning"

    def test_default_plural_adds_s(self):
        from _hook_utils import plural
        assert plural(2, "warning") == "2 warnings"

    def test_zero_is_plural(self):
        from _hook_utils import plural
        assert plural(0, "file") == "0 files"

    def test_irregular_plural_form(self):
        from _hook_utils import plural
        assert plural(1, "entry", "entries") == "1 entry"
        assert plural(3, "entry", "entries") == "3 entries"


def test_the_protected_zone_prefix_carve_out_is_deliberately_singular():
    """`_protected_zones.ALLOWED_PREFIXES_IN_PROTECTED` carries ONE prefix (the
    blueprint chain directory), and the comment above it says a second prefix
    needs its reason written there. This pins the count so a widening is a
    deliberate edit of both, never a silent tuple append."""
    from _protected_zones import ALLOWED_PREFIXES_IN_PROTECTED
    assert len(ALLOWED_PREFIXES_IN_PROTECTED) == 1, ALLOWED_PREFIXES_IN_PROTECTED
