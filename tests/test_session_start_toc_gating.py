"""The banner's optional sections are gated on THEIR ARTIFACT, not on repo identity.

Was TP-120a, "the SHARP_EDGES TOC is gated on is_self_host_repo". That gate was a
proxy: it asked "am I the harness's own repo?" when the question it needed
answered was "does THIS tree have the thing I am about to show?". `init` deploys
`docs/FAILURE_MODES.md` in full and `ESPALIER_MEMORY.md` with a Session Log, so
the identity test computed real content for an adopter and threw it away.

Each class below therefore pins BOTH arms of an artifact oracle -- present when
the artifact is, absent when it is not. A one-armed version of these tests is how
the original defect stayed green for so long: the adopter fixtures seeded the
catalog, so "omit it" passed for the wrong reason.

Sister-shape: TestSessionStartFreshnessBanner -- both drive session_start.py via
subprocess and assert on the joined additionalContext block. The per-helper unit
arms live in test_session_banner.py::TestFootgunPointerContentOracle.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


HOOK = (
    Path(__file__).resolve().parent.parent
    / "tools" / "cc" / "hooks" / "session_start.py"
)
REPO = Path(__file__).resolve().parent.parent


def _run_session_start(repo: Path) -> dict:
    """Invoke session_start.py against a synthetic repo; parse the
    additionalContext JSON it prints.

    Env preserves os.environ (session_start spawns git + python3
    subprocesses; stripping PATH would break them) and overrides
    CLAUDE_PROJECT_DIR.
    """
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    out = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=repo,
        input=json.dumps({"session_id": "test"}),
        capture_output=True, text=True, env=env, encoding="utf-8",
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(
            f"session_start failed: rc={out.returncode} "
            f"stderr={out.stderr!r} stdout={out.stdout!r}"
        )
    return json.loads(out.stdout)


def _context(result: dict) -> str:
    return result.get("hookSpecificOutput", {}).get("additionalContext", "")


def _flat(text: str) -> str:
    """Whitespace-flattened view of the banner.

    The orientation constants are WRAPPED source literals, so a phrase that
    reads as one sentence spans a newline in the emitted text. Asserting the
    unflattened phrase silently never matches -- which is how the negative arm
    below first shipped vacuous, passing against the very revert it exists to
    catch.
    """
    return " ".join(text.split())


def _adopter_tree(tmp_path: Path) -> Path:
    """A repo with no espalier/, no tools/cc/, no bench/ -> is_self_host_repo False."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# placeholder\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


class TestFootgunPointerGating:
    """The /recall footgun pointer rides the CATALOGS it names, not the repo."""

    def test_adopter_repo_with_a_catalog_receives_the_pointer(self, tmp_path):
        """An adopter owning a real catalog gets the pointer to it.

        The seeded catalog stays in this fixture deliberately: removing it would
        green this test against the fixed AND the unfixed hook, which is exactly
        how the original gate hid.
        """
        repo = _adopter_tree(tmp_path)
        (repo / "docs").mkdir()
        (repo / "docs" / "SHARP_EDGES.md").write_text(
            "## Section\n\nbody\n", encoding="utf-8"
        )
        ctx = _context(_run_session_start(repo))
        assert "FOOTGUNS & FAILURE MODES" in ctx, (
            "an adopter who owns a footgun catalog was denied the pointer to it. "
            f"Context excerpt: {ctx[:300]!r}"
        )
        assert "SHARP_EDGES TOC" not in ctx  # the old TOC wall must be gone everywhere

    def test_adopter_repo_without_catalogs_omits_the_pointer(self, tmp_path):
        """The negative arm: nothing to point at, so no pointer."""
        repo = _adopter_tree(tmp_path)
        ctx = _context(_run_session_start(repo))
        assert "FOOTGUNS & FAILURE MODES" not in ctx, (
            f"pointer shipped with no catalog behind it. Excerpt: {ctx[:300]!r}"
        )
        # ... and the orientation line that TEACHES /recall for footguns must go
        # with it. Reverting the tail to `if self_host: ... else: ...` ships this
        # line to a tree with no catalog at all, and left the suite green.
        assert "Footguns/failure-modes: pull the relevant entry" not in _flat(ctx), (
            "the orientation tail advertised pulling footguns on a tree that "
            f"has none. Excerpt: {ctx[:400]!r}"
        )

    def test_adopter_repo_with_only_the_seeded_scaffold_omits_the_pointer(self, tmp_path):
        """`init` seeds docs/SHARP_EDGES.md near-empty. Presence is not content:
        naming it would send the reader to pull an empty file."""
        repo = _adopter_tree(tmp_path)
        (repo / "docs").mkdir()
        (repo / "docs" / "SHARP_EDGES.md").write_text(
            (REPO / "espalier" / "assets" / "seed" / "SHARP_EDGES.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        ctx = _context(_run_session_start(repo))
        assert "FOOTGUNS & FAILURE MODES" not in ctx, (
            f"the seeded scaffold was advertised as a catalog. Excerpt: {ctx[:300]!r}"
        )

    def test_seeded_adopter_is_still_taught_recall(self, tmp_path):
        """POSITIVE arm. `init` seeds real docs/sharp-edges/ files, so /recall
        works on a fresh adopter tree even though their docs/SHARP_EDGES.md is
        the suppressed scaffold.

        The tail line was briefly gated on the POINTER's wording, which made it
        vanish on exactly that tree: the banner said "/recall does not index it"
        and never mentioned /recall again. Only-negative arms could not see it --
        `if False:` left them all green.
        """
        repo = _adopter_tree(tmp_path)
        (repo / "docs" / "sharp-edges").mkdir(parents=True)
        (repo / "docs" / "sharp-edges" / "hook-exit-codes.md").write_text(
            "# Hook exit codes\n\nexit 0 with JSON XOR exit 2 with stderr.\n",
            encoding="utf-8",
        )
        (repo / "docs" / "SHARP_EDGES.md").write_text(
            (REPO / "espalier" / "assets" / "seed" / "SHARP_EDGES.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        ctx = _flat(_context(_run_session_start(repo)))
        assert "Footguns/failure-modes: pull the relevant entry" in ctx, (
            "an adopter whose /recall corpus is non-empty was never taught "
            f"/recall. Banner: {ctx[:600]!r}"
        )

    def test_self_host_repo_includes_footgun_pointer(self):
        """Run inside the live self-host repo; the /recall footgun pointer
        must appear (and NOT the old TOC wall)."""
        ctx = _context(_run_session_start(REPO))
        assert "FOOTGUNS & FAILURE MODES" in ctx, (
            "Self-host session is missing the footgun pointer — "
            "gating predicate may have flipped."
        )
        assert "--- SHARP_EDGES TOC" not in ctx, "the old TOC wall must be gone"


class TestMemoryDigestGating:
    """The MEMORY Session-Log digest rides the SESSION LOG, not the repo.

    TP-236 gated this on is_self_host_repo. `init` deploys ESPALIER_MEMORY.md
    with a Session Log table, so an adopter who has run /handoff has their own
    recency -- which the identity gate computed and discarded.
    """

    def test_adopter_repo_with_dated_rows_receives_the_digest(self, tmp_path):
        """An adopter's OWN session history reaches their OWN banner.

        The dated row stays in this fixture deliberately -- same trap as above.
        """
        repo = _adopter_tree(tmp_path)
        (repo / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n| 2026-06-28 a recent adopter session | note |\n",
            encoding="utf-8",
        )
        ctx = _context(_run_session_start(repo))
        assert "MEMORY (recent sessions" in ctx, (
            "an adopter's own Session Log was withheld from their own banner. "
            f"Context excerpt: {ctx[:300]!r}"
        )
        assert "a recent adopter session" in ctx, "the headline itself must render"
        # The no-digest fallback is the ELSE of the digest, not of repo identity.
        # Reverting to `if self_host: ... else: ...` renders BOTH the digest and
        # the line claiming no digest arrived -- and left the suite green.
        assert "no recent-session digest reached this banner" not in _flat(ctx), (
            "the banner rendered a digest AND the line saying none arrived; the "
            "two conditions have been collapsed back into one identity fork"
        )

    def test_repo_without_dated_rows_omits_the_digest(self, tmp_path):
        """The negative arm: a Session Log with no dated rows renders nothing."""
        repo = _adopter_tree(tmp_path)
        (repo / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n\n_No sessions recorded yet._\n", encoding="utf-8"
        )
        ctx = _context(_run_session_start(repo))
        assert "MEMORY (recent sessions" not in ctx, (
            f"digest rendered with no dated rows behind it. Excerpt: {ctx[:300]!r}"
        )

    # pins: claim:claude-core-rule-4-memory-state
    def test_self_host_repo_includes_memory_digest(self):
        """Run inside the live self-host repo; the digest must appear.

        This is the mechanical backing for Core Rule #4's "loaded every session"
        clause (CLAUDE.md), cited as the second `<!-- canon: -->` alongside the
        line-cap. The `# pins:` slug above binds it to that claim-id.
        """
        ctx = _context(_run_session_start(REPO))
        assert "MEMORY (recent sessions" in ctx, (
            "Self-host session is missing the MEMORY digest — "
            "gating predicate may have flipped."
        )


class TestAdopterBannerVocabulary:
    """An adopter banner must not name concepts that exist only on this repo.

    The fallback line that exists BECAUSE the reader is not self-host used to
    name "the self-host recent-session digest" -- an internal concept with no
    referent on the tree it was written for. This pins the class, not the string.
    """

    def test_adopter_banner_never_says_self_host(self, tmp_path):
        repo = _adopter_tree(tmp_path)
        (repo / "docs").mkdir()
        (repo / "docs" / "SHARP_EDGES.md").write_text(
            "## Section\n\nbody\n", encoding="utf-8"
        )
        ctx = _context(_run_session_start(repo))
        lowered = ctx.lower()
        for token in ("self-host", "self host", "selfhost"):
            assert token not in lowered, (
                f"adopter banner leaks harness-internal vocabulary {token!r}: "
                f"{ctx[max(0, lowered.find(token) - 120):lowered.find(token) + 120]!r}"
            )
