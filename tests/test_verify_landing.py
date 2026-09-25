"""Contract for espalier.verify_landing (TP-185 W3).

Pins the LANDED/DRIFTED/OWED classification so it cannot silently drift: a
pure-classifier unit suite (deterministic, with injected path sets) plus an
end-to-end run against a throwaway git repo holding one LANDED, one DRIFTED, and
one OWED file — the earn-the-red the pack prescribes, which guards against a
mis-ranked classifier by failing if any classification is wrong. A CLI
subprocess test confirms the subcommand wiring.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from espalier.verify_landing import (
    DRIFTED,
    LANDED,
    OWED,
    LandingEntry,
    _extract_path_tokens,
    classify_against,
    classify_landing,
    render_table,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# A fixture pack claiming three files (one per landing state) plus a directory
# and a glob token, exercising both a numbered/parenthetical heading and a
# command token that must NOT be read as a path.
FIXTURE_PACK = """\
# TP-999 — fixture pack

## 7. Files touched (anticipated)

**New:**
- `src/landed.py` — committed, unchanged
- `src/drifted.py` — committed, then modified
- `src/owed.py` — claimed but never created
- `src/` — a directory token

## 8. Pass criteria
- the glob `src/*.py` resolves; `grep -rn "x" src/*.py` is NOT a path token
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _seed_repo(tmp_path: Path) -> Path:
    """A repo with src/landed.py + src/drifted.py committed, drifted.py then
    modified in the working tree."""
    repo = _init_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "landed.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "src" / "drifted.py").write_text("y = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    (repo / "src" / "drifted.py").write_text("y = 2  # changed\n", encoding="utf-8")
    return repo


class TestClassifyAgainst:
    """Pure classifier — deterministic with injected tracked/modified sets."""

    def _status(self, tracked, modified):
        return {
            e.path: e.status for e in classify_against(FIXTURE_PACK, tracked, modified)
        }

    def test_landed_drifted_owed(self):
        status = self._status({"src/landed.py", "src/drifted.py"}, {"src/drifted.py"})
        assert status["src/landed.py"] == LANDED
        assert status["src/drifted.py"] == DRIFTED
        assert status["src/owed.py"] == OWED

    def test_classification_tracks_state_not_hardcoded(self):
        # Same pack + file: LANDED when tracked, OWED when not — proves the
        # classifier reads the injected state (earn-the-red for the whole point).
        assert self._status({"src/owed.py"}, set())["src/owed.py"] == LANDED
        assert self._status(set(), set())["src/owed.py"] == OWED

    def test_drifted_requires_head_membership(self):
        # A file both tracked and modified is DRIFTED (the actionable signal)...
        assert self._status({"src/drifted.py"}, {"src/drifted.py"})["src/drifted.py"] == DRIFTED
        # ...but a staged-but-uncommitted NEW file shows in `git diff HEAD`
        # (modified) yet is NOT in HEAD (tracked) — that is OWED, not DRIFTED.
        owed = classify_against(FIXTURE_PACK, set(), {"src/owed.py"})
        owed_entry = next(e for e in owed if e.path == "src/owed.py")
        assert owed_entry.status == OWED
        assert owed_entry.head_state == "absent"

    def test_directory_token_prefix_matches(self):
        assert self._status({"src/landed.py"}, set())["src/"] == LANDED

    def test_directory_token_owed_when_nothing_underneath(self):
        assert self._status(set(), set())["src/"] == OWED

    def test_glob_token_fnmatches(self):
        assert self._status({"src/landed.py"}, set())["src/*.py"] == LANDED

    def test_bare_basename_matches_tracked_by_basename(self):
        # TP-186: a pack often references a file by basename (`write_guard.py`)
        # when the tracked file lives deeper (`tools/cc/hooks/write_guard.py`).
        # That is LANDED, not a false OWED. Earn-the-red: pre-fix _resolve_matches
        # has no basename branch, so this classified OWED.
        pack = "## Files touched\n- `write_guard.py`\n"
        status = {
            e.path: e.status
            for e in classify_against(pack, {"tools/cc/hooks/write_guard.py"}, set())
        }
        assert status["write_guard.py"] == LANDED

    def test_unknown_bare_basename_still_owed(self):
        # The basename fallback must NOT manufacture false LANDED: a genuinely-new
        # file with no same-named tracked sibling stays OWED.
        status = {
            e.path: e.status
            for e in classify_against(
                "## Files touched\n- `nonexistent.py`\n", {"src/other.py"}, set()
            )
        }
        assert status["nonexistent.py"] == OWED

    def test_bare_basename_drift_keyed_to_resolved_path(self):
        # TP-191 W3 earn-the-red: a bare-basename token must report DRIFTED only
        # when ITS resolved tracked file changed — not when an UNRELATED
        # same-named file is in the diff. Token `config.py` resolves to the
        # tracked `espalier/config.py` (unmodified); the modified set holds a
        # different `scripts/config.py`. Pre-fix the basename-blind modified
        # check reported DRIFTED; it must be LANDED.
        status = {
            e.path: e.status
            for e in classify_against(
                "## Files touched\n- `config.py`\n",
                {"espalier/config.py"},
                {"scripts/config.py"},
            )
        }
        assert status["config.py"] == LANDED

    def test_bare_basename_drift_when_resolved_path_modified(self):
        # Positive control: when the resolved tracked file IS modified, DRIFTED.
        status = {
            e.path: e.status
            for e in classify_against(
                "## Files touched\n- `config.py`\n",
                {"espalier/config.py"},
                {"espalier/config.py"},
            )
        }
        assert status["config.py"] == DRIFTED


class TestExtractPathTokens:
    def test_extracts_from_both_canonical_sections(self):
        toks = _extract_path_tokens(FIXTURE_PACK)
        assert "src/landed.py" in toks  # Files touched
        assert "src/*.py" in toks  # Pass criteria

    def test_skips_command_tokens_with_whitespace(self):
        toks = _extract_path_tokens(FIXTURE_PACK)
        assert all(not any(c.isspace() for c in t) for t in toks)
        assert 'grep -rn "x" src/*.py' not in toks

    def test_recognizes_legacy_section_names(self):
        # TP-183 predates W0: "Surfaces to touch" / "Earn-the-red proofs".
        legacy = (
            "## Surfaces to touch\n- `a/b.py` x\n\n"
            "## Earn-the-red proofs\n- `c/d.py` y\n"
        )
        toks = _extract_path_tokens(legacy)
        assert "a/b.py" in toks
        assert "c/d.py" in toks

    def test_tolerates_numbered_and_parenthetical_heading(self):
        assert "x/y.py" in _extract_path_tokens(
            "## 11. Files touched (anticipated, full set)\n- `x/y.py` z\n"
        )

    def test_no_claim_sections_returns_empty(self):
        assert _extract_path_tokens("# Pack\n\n## Motivation\n- `a/b.py`\n") == []

    def test_a_struck_claim_is_withdrawn_not_owed(self):
        """A `~~struck~~` claim is the record of a file the pack said it would
        no longer create; read as a claim it manufactured a fake OWED blocker
        (the failure-mode review of the §C7 lane drove it)."""
        toks = _extract_path_tokens(
            "## Files touched\n- `src/kept.py` x\n"
            "- ~~`espalier/never_created_xyz.py`~~ -- withdrawn, the\n  sub-task was dropped\n"
        )
        assert toks == ["src/kept.py"]

    def test_code_fence_does_not_drop_later_tokens(self):
        # A fenced code block between two path bullets must not swallow the
        # second token's backticks (W3 adversarial — the `[^`\n]+` fix). Pre-fix,
        # `src/after.py` was lost because backtick pairing spanned the fence.
        text = (
            "## Files touched\n"
            "- `src/before.py` first\n"
            "```python\n"
            "x = 1\n"
            "```\n"
            "- `src/after.py` second\n"
        )
        toks = _extract_path_tokens(text)
        assert "src/before.py" in toks
        assert "src/after.py" in toks

    def test_dedupes_repeated_tokens(self):
        text = (
            "## Files touched\n- `a/b.py` once\n- `a/b.py` again\n"
            "## Pass criteria\n- `a/b.py` thrice\n"
        )
        assert _extract_path_tokens(text) == ["a/b.py"]

    def test_sibling_subsection_tokens_do_not_bleed(self):
        # TP-191 W3 earn-the-red: a `###` subsection sitting between a claim
        # section and the next `##` must NOT bleed its path tokens into the claim
        # section. Pre-fix the end-anchor was `^## ` (level-2 only), so
        # `bleed/note.py` under the `### Notes` subsection was captured as a
        # Files-touched claim.
        text = (
            "## Files touched\n"
            "- `real/claim.py` the actual claim\n"
            "### Notes\n"
            "- `bleed/note.py` not a claim, just a note\n"
            "## Motivation\n"
            "- `other/x.py` also not a claim\n"
        )
        toks = _extract_path_tokens(text)
        assert "real/claim.py" in toks
        assert "bleed/note.py" not in toks
        assert "other/x.py" not in toks

    def test_drops_ellipsis_placeholder_tokens(self):
        # TP-186: `task-packs/TP-...` / `espalier/assets/.../` are prose ellipses
        # (they pass _looks_like_path via the '/'), not file claims. Earn-the-red:
        # pre-fix they were extracted and then mis-classified OWED.
        text = (
            "## Files touched\n"
            "- `task-packs/TP-...` placeholder\n"
            "- `espalier/assets/claude/...` mirror\n"
            "- `src/real.py` the actual file\n"
        )
        assert _extract_path_tokens(text) == ["src/real.py"]

    def test_drops_slash_command_and_absolute_tokens(self):
        # A repo-relative claim never starts with '/'; slash-commands and absolute
        # paths are prose, not claims.
        text = (
            "## Files touched\n"
            "- run `/scope-check` then `/preflight`\n"
            "- `/tmp` scratch\n"
            "- `src/real.py`\n"
        )
        assert _extract_path_tokens(text) == ["src/real.py"]

    def test_drops_degenerate_dot_slash_tokens(self):
        # Dots-and-slashes bypass examples (`.//`, `.///`) have no name char.
        text = "## Files touched\n- the `.//` and `.///` examples\n- `src/real.py`\n"
        assert _extract_path_tokens(text) == ["src/real.py"]


class TestClassifyLandingEndToEnd:
    def test_real_repo_one_of_each(self, tmp_path):
        # The pack's prescribed earn-the-red: one LANDED + one DRIFTED + one OWED.
        repo = _seed_repo(tmp_path)
        status = {e.path: e.status for e in classify_landing(FIXTURE_PACK, repo)}
        assert status["src/landed.py"] == LANDED
        assert status["src/drifted.py"] == DRIFTED
        assert status["src/owed.py"] == OWED

    def test_non_git_directory_degrades_not_crashes(self, tmp_path):
        # git calls fail in a non-repo -> empty sets -> everything OWED, no raise.
        entries = classify_landing(FIXTURE_PACK, tmp_path)
        assert entries and all(e.status == OWED for e in entries)

    def test_cli_subcommand_json(self, tmp_path):
        repo = _seed_repo(tmp_path)
        pack = tmp_path / "pack.md"
        pack.write_text(FIXTURE_PACK, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "espalier", "verify-landing",
             str(pack), "--repo", str(repo), "--json"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        status = {d["path"]: d["status"] for d in json.loads(result.stdout)}
        assert status["src/landed.py"] == LANDED
        assert status["src/drifted.py"] == DRIFTED
        assert status["src/owed.py"] == OWED

    def test_cli_non_utf8_pack_exits_1_cleanly(self, tmp_path):
        # A present-but-undecodable pack exits 1 with a clean message, not a
        # traceback (W3 adversarial — the read-failure contract).
        repo = _seed_repo(tmp_path)
        pack = tmp_path / "bad.md"
        pack.write_bytes(b"## Files touched\n- `src/x.py`\n\xff\xfe not utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "espalier", "verify-landing", str(pack), "--repo", str(repo)],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        assert result.returncode == 1
        assert "cannot read pack file" in result.stdout
        assert "Traceback" not in result.stderr


class TestRenderTable:
    def test_table_has_rows_and_summary(self):
        out = render_table(
            [
                LandingEntry("a/b.py", "tracked", LANDED),
                LandingEntry("c/d.py", "absent", OWED),
            ]
        )
        assert "a/b.py" in out and "LANDED" in out
        assert "1 landed | 0 drifted | 1 owed" in out

    def test_empty_message(self):
        assert "No path tokens" in render_table([])

    def test_empty_message_names_all_claim_sections(self):
        # TP-191 W3: the empty message must name ALL recognized claim sections
        # (derived from _CLAIM_SECTIONS), not just the two that were hardcoded.
        from espalier.verify_landing import _CLAIM_SECTIONS
        out = render_table([])
        for header in _CLAIM_SECTIONS:
            assert header in out, f"claim section {header!r} missing from message"
