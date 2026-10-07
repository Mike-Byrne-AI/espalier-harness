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


@pytest.mark.contract
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


@pytest.mark.contract
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


class TestSayOnce:
    """The once-a-session voice for a fail-open: one audit record, one stderr
    line, one flag under STATE_DIR; the same key in the same session is
    silent; the flag family is cleared at the next fresh SessionStart."""

    def _fresh(self, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        return _hook_utils

    def test_speaks_once_writes_one_record_and_one_flag(self, tmp_path, monkeypatch, capsys):
        hu = self._fresh(monkeypatch)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))  # the audit log lives under ~/.espalier
        hu.say_once(tmp_path, "integrity-scan", "write_guard", "pretooluse_failed_open_integrity_scan",
                    "integrity scan failed (OSError); kill-switch check skipped", fault="OSError")
        hu.say_once(tmp_path, "integrity-scan", "write_guard", "pretooluse_failed_open_integrity_scan",
                    "integrity scan failed (OSError); kill-switch check skipped", fault="OSError")
        err = capsys.readouterr().err
        assert err.count("[write_guard] integrity scan failed") == 1, err
        assert (tmp_path / hu.STATE_DIR / "once_integrity-scan").is_file()

    def test_a_flag_from_an_earlier_process_keeps_it_silent(self, tmp_path, monkeypatch, capsys):
        hu = self._fresh(monkeypatch)
        (tmp_path / hu.STATE_DIR).mkdir()
        (tmp_path / hu.STATE_DIR / "once_k").write_text("", encoding="utf-8")
        hu.say_once(tmp_path, "k", "plan_guard", "x", "should not print")
        assert "should not print" not in capsys.readouterr().err

    def test_never_raises_on_a_read_only_state_dir(self, tmp_path, monkeypatch, capsys):
        hu = self._fresh(monkeypatch)
        monkeypatch.setattr(hu, "atomic_write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        hu.say_once(tmp_path, "k2", "stop_gate", "x", "still speaks")
        assert "[stop_gate] still speaks" in capsys.readouterr().err
        hu.say_once(tmp_path, "k2", "stop_gate", "x", "still speaks")
        assert "still speaks" not in capsys.readouterr().err, "the in-process set keeps it to once"

    def test_a_fresh_session_start_clears_the_family(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        hu.say_once(tmp_path, "k3", "write_guard", "x", "m")
        flag = tmp_path / hu.STATE_DIR / "once_k3"
        assert flag.is_file()
        import importlib.util
        spec = importlib.util.spec_from_file_location("session_start_for_once_flags", str(HOOKS_DIR / "session_start.py"))
        ss = importlib.util.module_from_spec(spec)
        sys.modules["session_start_for_once_flags"] = ss
        spec.loader.exec_module(ss)
        ss._clean_state_flags(tmp_path, source="compact")
        assert flag.is_file(), "a continuation keeps the session's flags"
        ss._clean_state_flags(tmp_path, source="startup")
        assert not flag.exists(), "a fresh session speaks again"


class TestReadTomlStringList:
    """The one hook-side reader of espalier.toml: the RAW value, ``None`` for an
    absent file or key, the caller's channel on a malformed file, the regex
    arm when no parser is importable, and an injectable parser binding."""

    def test_returns_the_raw_value_and_none_for_absent(self, tmp_path):
        import _hook_utils
        assert _hook_utils.read_toml_string_list(tmp_path, "k") is None
        (tmp_path / "espalier.toml").write_text('k = ["a", "b"]\nn = 3\n', encoding="utf-8")
        assert _hook_utils.read_toml_string_list(tmp_path, "k") == ["a", "b"]
        assert _hook_utils.read_toml_string_list(tmp_path, "n") == 3  # raw: the caller validates
        assert _hook_utils.read_toml_string_list(tmp_path, "missing") is None

    def test_a_malformed_file_reports_through_on_error_and_returns_none(self, tmp_path):
        import _hook_utils
        (tmp_path / "espalier.toml").write_text('k = ["a"\n', encoding="utf-8")
        said: list[str] = []
        assert _hook_utils.read_toml_string_list(tmp_path, "k", on_error=said.append) is None
        assert len(said) == 1 and said[0], said
        assert _hook_utils.read_toml_table(tmp_path) is None

    def test_no_parser_takes_the_regex_arm(self, tmp_path):
        import _hook_utils
        (tmp_path / "espalier.toml").write_text('# k = ["no"]\nk = ["a", "b"]\n', encoding="utf-8")
        assert _hook_utils.read_toml_string_list(tmp_path, "k", parser=None) == ["a", "b"]
        assert _hook_utils.read_toml_string_list(tmp_path, "zz", parser=None) is None
        assert _hook_utils.read_toml_table(tmp_path, parser=None) is None

    def test_adopter_prefixes_are_boundary_matched_pairs(self, tmp_path, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        (tmp_path / "espalier.toml").write_text(
            'protected_paths = ["data", "./models/"]\ngenerated_paths = ["dist\\\\out"]\n', encoding="utf-8")
        assert _hook_utils.adopter_protected_prefixes(tmp_path) == (
            ("data/", "protected"), ("models/", "protected"), ("dist/out/", "generated"))
        assert _hook_utils.adopter_zone_for("data/x.csv", tmp_path) == ("data/", "protected")
        assert _hook_utils.adopter_zone_for("DATA", tmp_path) == ("data/", "protected")
        assert _hook_utils.adopter_zone_for("database.py", tmp_path) is None
        assert _hook_utils.adopter_zone_for("dist/out/b.js", tmp_path) == ("dist/out/", "generated")
        assert _hook_utils.protected_prefixes(tmp_path) == ["tools/cc/", "cc/", "data/", "models/"]


class TestBadStdinVoice:
    """A payload the hooks could not read is an empty dict that remembers why
    (``BadStdin``); empty stdin is a plain ``{}``. Every ``== {}`` pin above
    keeps its truth; the blocking hooks add one line, once a session."""

    def test_non_empty_unusable_payloads_carry_their_fault(self, monkeypatch):
        from _hook_utils import BadStdin, read_stdin_safely
        for raw, fault in ((b"[1,2,3]", "NotADict"), (b"{{broken", "JSONDecodeError"), (b"\xff\xfe" + b'{"a":1}', "JSONDecodeError")):
            monkeypatch.setattr(sys, "stdin", _StdinShim(raw))
            data = read_stdin_safely()
            assert data == {} and isinstance(data, BadStdin) and data.fault == fault, (raw, data)

    def test_empty_or_whitespace_stdin_is_a_plain_dict(self, monkeypatch):
        from _hook_utils import BadStdin, read_stdin_safely
        for raw in (b"", b"\n", b"  \n"):
            monkeypatch.setattr(sys, "stdin", _StdinShim(raw))
            data = read_stdin_safely()
            assert data == {} and not isinstance(data, BadStdin), raw

    def test_say_bad_stdin_speaks_once_for_a_bad_payload_and_never_for_empty(self, tmp_path, monkeypatch, capsys):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _hook_utils.say_bad_stdin(tmp_path, "write_guard", "pretooluse_failed_open_bad_stdin", {})
        assert capsys.readouterr().err == ""
        _hook_utils.say_bad_stdin(tmp_path, "write_guard", "pretooluse_failed_open_bad_stdin", _hook_utils.BadStdin("NotADict"))
        err = capsys.readouterr().err
        assert "[write_guard] stdin was not a JSON object (NotADict)" in err
        _hook_utils.say_bad_stdin(tmp_path, "write_guard", "pretooluse_failed_open_bad_stdin", _hook_utils.BadStdin("NotADict"))
        assert capsys.readouterr().err == ""


class TestLockedIncrementReadOnlyDir:
    """The read-only-state-dir branch of ``_locked_increment`` reads THE SAME
    counter it was asked for (it dropped ``name`` until 2026-09-30, so a caller
    counting anything but the default file read the default's count) and says
    so once."""

    def test_the_named_counter_is_read_not_the_default(self, tmp_path, monkeypatch, capsys):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        state = tmp_path / _hook_utils.STATE_DIR
        state.mkdir()
        (state / "write_count").write_text("2", encoding="utf-8")
        (state / "tool_call_count").write_text("7", encoding="utf-8")
        real_mkdir = Path.mkdir

        def _ro(self, *a, **k):
            if self == state:
                raise PermissionError(13, "read-only")
            return real_mkdir(self, *a, **k)

        monkeypatch.setattr(Path, "mkdir", _ro)
        assert _hook_utils._locked_increment(state, "tool_call_count") == 7
        err = capsys.readouterr().err
        assert "tool_call_count cannot be written (PermissionError)" in err, err


class TestSayOnceNeverRaises:
    """Every step of ``say_once`` sits in its own try -- including the one that
    builds the flag path, which the 2-A review found outside every try (a
    ``str`` root raised ``TypeError`` past a blocking hook's umbrella)."""

    @pytest.mark.parametrize("shape", ["str", "none", "int", "missing"])
    def test_a_bad_root_speaks_and_does_not_raise(self, shape, tmp_path, monkeypatch, capsys):
        """Every bad root lands under tmp_path (a relative flag path resolves
        against the cwd, so the cwd is tmp_path): the first draft of this case
        wrote `None/` and `3/` into the live tree and a flag under /tmp that
        silenced its own second run."""
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        monkeypatch.chdir(tmp_path)
        root = {"str": str(tmp_path / "as-a-str"), "none": None, "int": 3, "missing": tmp_path / "no" / "such"}[shape]
        _hook_utils.say_once(root, f"k-bad-root-{shape}", "write_guard", "x", "still speaks")  # type: ignore[arg-type]
        assert "[write_guard] still speaks" in capsys.readouterr().err

    def test_a_raising_audit_writer_or_exists_does_not_raise(self, tmp_path, monkeypatch, capsys):
        import _hook_utils
        import _integrity
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        monkeypatch.setattr(_integrity, "append_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
        monkeypatch.setattr(Path, "exists", lambda self: (_ for _ in ()).throw(PermissionError(13, "eacces")))
        _hook_utils.say_once(tmp_path, "k-raising", "plan_guard", "x", "still speaks")
        assert "[plan_guard] still speaks" in capsys.readouterr().err

    def test_a_key_with_path_characters_stays_in_the_once_family(self, tmp_path, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        _hook_utils.say_once(tmp_path, "../zone/x", "write_guard", "x", "m")
        flags = sorted(p.name for p in (tmp_path / _hook_utils.STATE_DIR).iterdir())
        assert flags == ["once_.._zone_x"], flags


class TestBadStdinKeyIsPerHook:
    def test_two_hooks_two_flags_two_records(self, tmp_path, monkeypatch, capsys):
        """A shared key let the first hook to speak silence the other three for
        the session (the 2-A review drove four hooks: one flag)."""
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        bad = _hook_utils.BadStdin("JSONDecodeError")
        _hook_utils.say_bad_stdin(tmp_path, "write_guard", "pretooluse_failed_open_bad_stdin", bad)
        _hook_utils.say_bad_stdin(tmp_path, "stop_gate", "stop_failed_open_bad_stdin", bad)
        err = capsys.readouterr().err
        assert "[write_guard] stdin was not" in err and "[stop_gate] stdin was not" in err
        flags = sorted(p.name for p in (tmp_path / _hook_utils.STATE_DIR).iterdir())
        assert flags == ["once_bad-stdin-stop_gate", "once_bad-stdin-write_guard"], flags


class TestDeclaredDependencyDirs:
    """espalier.toml's flat ``dependency_dirs`` key (TP-469 lane C): the names
    an adopter adds to the stack table's dependency directories, read by the
    two tools/cc walkers through this one reader. Additive, stripped, a bad
    entry ignored and said once."""

    def _fresh(self, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        return _hook_utils

    def test_no_toml_declares_nothing(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        assert hu.declared_dependency_dirs(tmp_path, hook="t") == frozenset()

    def test_declared_names_are_read_as_written_and_stripped(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text(
            'dependency_dirs = [" deps ", "Third-Party", ".pnpm-cache"]\n', encoding="utf-8"
        )
        assert hu.declared_dependency_dirs(tmp_path, hook="t") == {"deps", "Third-Party", ".pnpm-cache"}

    @pytest.mark.parametrize("text,said", [
        ('dependency_dirs = "deps"\n', "must be a list of strings, got str"),
        ('dependency_dirs = ["vendor/pkg", "ok"]\n', "entry 'vendor/pkg' is not a directory name"),
        ('dependency_dirs = ["..", "ok"]\n', "entry '..' is not a directory name"),
        ('dependency_dirs = [3, "ok"]\n', "entry 3 is not a directory name"),
    ])
    def test_a_malformed_value_adds_nothing_and_is_said(self, tmp_path, monkeypatch, capsys, text, said):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text(text, encoding="utf-8")
        got = hu.declared_dependency_dirs(tmp_path, hook="t")
        assert "vendor/pkg" not in got and ".." not in got and "deps" not in got
        assert got <= {"ok"}
        assert said in capsys.readouterr().err

    def test_the_shape_twin_is_the_engines(self):
        """Pinned in tests/test_forced_copy_parity.py too; held here so the
        hook-side file reads as its own contract."""
        import _hook_utils
        for name in ("deps", "Third-Party", ".pnpm-cache", "a b"):
            assert _hook_utils._DEPENDENCY_DIR_SHAPE.match(name), name
        for name in ("", ".", "..", "a/b", "a\\b", "/abs"):
            assert not _hook_utils._DEPENDENCY_DIR_SHAPE.match(name), name


class TestSourceExtensions:
    """The shipped source set reads the ES-module, TypeScript-module and
    component formats, and espalier.toml's ``source_extensions`` adds to it
    (DEF-961). A Node or Astro tree written in them never armed the write
    count or the root plan gate."""

    def _fresh(self, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        return _hook_utils

    def test_the_shipped_set_names_the_node_and_component_formats(self):
        import _hook_utils
        for ext in (".mjs", ".cjs", ".mts", ".cts", ".astro", ".vue", ".svelte"):
            assert ext in _hook_utils.SOURCE_LANGUAGE_EXTENSIONS, ext
        # Decided, not appended: documentation and styling are not source.
        assert not {".mdx", ".md", ".css"} & _hook_utils.SOURCE_LANGUAGE_EXTENSIONS

    def test_no_toml_is_the_shipped_set(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        assert hu.source_extensions(tmp_path, hook="t") == hu.SOURCE_LANGUAGE_EXTENSIONS

    def test_declared_extensions_are_added_never_removed(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text('source_extensions = [".Liquid", " .njk "]\n', encoding="utf-8")
        got = hu.source_extensions(tmp_path, hook="t")
        assert {".liquid", ".njk"} <= got and hu.SOURCE_LANGUAGE_EXTENSIONS <= got

    @pytest.mark.parametrize("text,said", [
        ('source_extensions = ".liquid"\n', "must be a list of strings, got str"),
        ('source_extensions = ["liquid", ".ok"]\n', "entry 'liquid' is not an extension"),
        ('source_extensions = [3]\n', "entry 3 is not an extension"),
    ])
    def test_a_malformed_value_adds_nothing_and_is_said(self, tmp_path, monkeypatch, capsys, text, said):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text(text, encoding="utf-8")
        got = hu.source_extensions(tmp_path, hook="t")
        assert ".liquid" not in got and "liquid" not in got
        assert said in capsys.readouterr().err

    def test_an_edit_to_the_file_is_seen_on_the_next_call(self, tmp_path, monkeypatch):
        """The parse is memoised on the file's mtime and size (reflect_trigger
        asks on every non-source write); an edit must still take effect."""
        import os as _os

        hu = self._fresh(monkeypatch)
        cfg = tmp_path / "espalier.toml"
        cfg.write_text('source_extensions = [".liquid"]\n', encoding="utf-8")
        assert ".liquid" in hu.source_extensions(tmp_path, hook="t")
        cfg.write_text('source_extensions = [".njk"]\n', encoding="utf-8")
        _os.utime(cfg, ns=(cfg.stat().st_atime_ns, cfg.stat().st_mtime_ns + 1_000_000))
        got = hu.source_extensions(tmp_path, hook="t")
        assert ".njk" in got and ".liquid" not in got
        cfg.unlink()
        assert hu.source_extensions(tmp_path, hook="t") == hu.SOURCE_LANGUAGE_EXTENSIONS

    def test_plan_guard_and_reflect_trigger_read_the_declared_extensions(self, tmp_path, monkeypatch):
        """Both consumers: a root-level ``site.liquid`` needs a plan, and a
        write to one counts, only once espalier.toml declares the extension."""
        self._fresh(monkeypatch)
        import plan_guard
        import reflect_trigger
        assert plan_guard._is_exempt("site.liquid", tmp_path) is True
        assert reflect_trigger._is_source_file("src/page.liquid", tmp_path) is False
        (tmp_path / "espalier.toml").write_text('source_extensions = [".liquid"]\n', encoding="utf-8")
        assert plan_guard._is_exempt("site.liquid", tmp_path) is False
        assert reflect_trigger._is_source_file("src/page.liquid", tmp_path) is True
        # The shipped formats need no declaration.
        assert plan_guard._is_exempt("site.config.mjs", tmp_path) is False
        assert reflect_trigger._is_source_file("src/pages/index.astro", tmp_path) is True


class TestDeclaredReliefAgents:
    """espalier.toml's ``code_review_agents`` and ``docs_refresh_agents``:
    the adopter's own agents relieve the stop gate's hygiene gates beside the
    shipped code-reviewer and docs-maintainer (DEF-963)."""

    def _fresh(self, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        return _hook_utils

    def test_declared_agents_join_the_shipped_table(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text(
            'code_review_agents = ["astro-reviewer"]\ndocs_refresh_agents = ["site-docs"]\n',
            encoding="utf-8",
        )
        table = hu.relief_flags(tmp_path, hook="t")
        assert table["astro-reviewer"] == hu.CODE_REVIEWED
        assert table["site-docs"] == hu.DOCS_REFRESHED
        assert table["code-reviewer"] == hu.CODE_REVIEWED, "the shipped agent still relieves"
        assert hu.relief_flags(tmp_path / "nowhere", hook="t") == hu.RELIEF_FLAGS

    @pytest.mark.parametrize("text,said", [
        ('code_review_agents = "astro-reviewer"\n', "must be a list of agent names, got str"),
        ('code_review_agents = ["has space"]\n', "is not an agent name"),
        ('docs_refresh_agents = ["code-reviewer"]\n', "is a shipped agent"),
        ('code_review_agents = ["both"]\ndocs_refresh_agents = ["both"]\n', "declared for both stop gates"),
        ('code_review_agents = ["general-purpose"]\n', "is a built-in agent"),
        ('code_review_agents = ["Explore"]\n', "is a built-in agent"),
    ])
    def test_a_malformed_declaration_relieves_nothing_and_is_said(
        self, tmp_path, monkeypatch, capsys, text, said,
    ):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text(text, encoding="utf-8")
        table = hu.relief_flags(tmp_path, hook="t")
        assert "has space" not in table and table["code-reviewer"] == hu.CODE_REVIEWED
        assert "general-purpose" not in table and "Explore" not in table
        if "both" in text:
            assert table["both"] == hu.CODE_REVIEWED, "the first declaration stands"
        assert said in capsys.readouterr().err

    def test_the_deny_line_names_the_agents_and_a_missing_body(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        (tmp_path / "espalier.toml").write_text(
            'code_review_agents = ["astro-reviewer", "typo-reviewer"]\n', encoding="utf-8",
        )
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        (tmp_path / ".claude" / "agents" / "astro-reviewer.md").write_text("---\nname: astro-reviewer\n---\n", encoding="utf-8")
        line = hu.relief_agents_line(tmp_path, hu.CODE_REVIEWED, hook="t")
        assert "code_review_agents" in line
        assert "`astro-reviewer`," in line or line.count("`astro-reviewer`") == 1
        assert "`typo-reviewer` (no body found under .claude/agents/)" in line
        assert "`astro-reviewer` (no body" not in line
        assert hu.relief_agents_line(tmp_path, hu.DOCS_REFRESHED, hook="t") == ""


class TestAdopterZoneReadingEdges:
    def _fresh(self, monkeypatch):
        import _hook_utils
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        monkeypatch.setattr(_hook_utils, "_ADOPTER_ZONES_MEMO", {})
        return _hook_utils

    def test_a_mistyped_key_name_is_said_at_the_hook(self, tmp_path, monkeypatch, capsys):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text('protected_path = ["data/"]\n', encoding="utf-8")
        assert hu.adopter_protected_prefixes(tmp_path) == ()
        err = capsys.readouterr().err
        assert "`protected_path` is not a key the guard reads (did you mean `protected_paths`?)" in err, err

    @pytest.mark.parametrize("text", [
        'plan_exempt_prefixes = ["src/"]  # protected_paths = ["/"]',   # a key inside a trailing comment
        '[tool.other]\nprotected_paths = ["src/"]',                    # table-scoped, not top-level
        'unprotected_paths = ["src/"]',                                 # a substring key
    ])
    def test_the_regex_arm_agrees_with_a_real_parse_on_the_three_divergences(self, tmp_path, text):
        """The no-parser fallback now creates DENIES, so an over-match is a false
        deny on user-owned code; the 2-A review drove these three rows."""
        import _hook_utils
        (tmp_path / "espalier.toml").write_text(text + "\n", encoding="utf-8")
        assert _hook_utils.read_toml_string_list(tmp_path, "protected_paths", parser=None) is None
        assert _hook_utils.read_toml_string_list(tmp_path, "protected_paths") is None

    def test_a_zone_read_by_the_degraded_reader_is_said(self, tmp_path, monkeypatch, capsys):
        hu = self._fresh(monkeypatch)
        monkeypatch.setattr(hu, "_toml_parser", lambda: None)
        (tmp_path / "espalier.toml").write_text('protected_paths = ["data/"]\n', encoding="utf-8")
        assert hu.adopter_protected_prefixes(tmp_path) == (("data/", "protected"),)
        assert "read by the no-parser regex fallback" in capsys.readouterr().err

    def test_the_memo_follows_the_file(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        cfg = tmp_path / "espalier.toml"
        cfg.write_text('protected_paths = ["data/"]\n', encoding="utf-8")
        assert hu.adopter_protected_prefixes(tmp_path) == (("data/", "protected"),)
        cfg.write_text('protected_paths = ["models/"]\n', encoding="utf-8")
        import os as _os
        _os.utime(cfg, ns=(cfg.stat().st_atime_ns, cfg.stat().st_mtime_ns + 1_000_000))
        assert hu.adopter_protected_prefixes(tmp_path) == (("models/", "protected"),), "an edit takes effect on the next call"
        cfg.unlink()
        assert hu.adopter_protected_prefixes(tmp_path) == ()

    def test_adopter_zone_for_folds_like_the_zone_predicate(self, tmp_path, monkeypatch):
        hu = self._fresh(monkeypatch)
        (tmp_path / "espalier.toml").write_text('protected_paths = ["data/"]\n', encoding="utf-8")
        assert hu.adopter_zone_for("\uff44ata/x.csv", tmp_path) == ("data/", "protected")  # fullwidth d
