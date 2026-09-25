"""Tests for the TP-RELEASE-08 release-readiness gate
(``scripts/release_check.py``).

Pins two responsibilities the gate must continuously satisfy:

1. **Live-repo PASS** — every individual check returns PASS on the
   current repo. If a check starts FAILing here, either a prior
   pack regressed or the gate's own logic drifted from reality.
2. **Fail-injection** — for at least the structural checks, prove
   the gate FAILs when fed a deliberately broken input (a
   ``tmp_path`` repo missing required files, containing forbidden
   patterns, etc.). A gate that always returns PASS isn't a gate.

Without the second invariant the gate could silently degrade into
an unconditional pass — every release would still "succeed" but
the gate's protective value would be zero, and the regression
would only surface the next time someone actually tries to break
the gate intentionally.

Marker: ``release`` (registered in ``tests/conftest.py::_MARKER_RULES``).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is dev tooling and is intentionally NOT included in the sdist
# (per MANIFEST.in). When tests run from a sdist install, scripts/ is
# absent and the release_check module can't be imported. Skip the entire
# file with a clear reason in that environment.
if not (REPO_ROOT / "scripts" / "release_check.py").is_file():
    pytest.skip(
        "scripts/release_check.py is dev tooling not shipped in sdist; "
        "this test file applies only to source-checkout / source-archive runs.",
        allow_module_level=True,
    )

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_check  # type: ignore[import-not-found]  # noqa: E402


# ── Live-repo PASS coverage ─────────────────────────────────────────


@pytest.mark.parametrize(
    "check_name",
    [
        "package_import",
        "cli_entrypoint",
        "tracked_noise",
        "docs_no_phantom_files",
        "docs_no_overclaim",
        "docs_count_claims",
        "hook_protocol_correct",
        "sharp_edges_correct",
        "sessionstart_no_block_claim",
        "live_surface_clean",
        "security_policy_private",
        "claude_agent_frontmatter",
        "version_consistent",
        "license_present",
        "security_present",
        "contributing_present",
        "changelog_present",
        "canonical_urls",
        "wheel_smoke",
    ],
)
def test_check_passes_on_live_repo(check_name, initialized_repo_root):
    """Every individual check returns PASS or SKIP against an initialized
    self-host repo.

    TP-37: ``wheel_smoke`` and ``tests_pass`` return ``SKIP`` without their
    opt-in env vars set; both are acceptable on the live repo because the
    opt-in path is itself the publish-gate escalation. ``FAIL`` is the
    only outcome that signals a regression here.
    """
    fn = getattr(release_check, f"check_{check_name}")
    result = fn(initialized_repo_root)
    assert result.status in ("PASS", "SKIP"), (
        f"{check_name} FAILED on initialized repo: {result.detail!r}. "
        "Either a prior pack regressed, or the gate's own logic drifted."
    )


_EXPECTED_CHECK_NAMES = frozenset({
    "canonical_urls",
    "changelog_present",
    "claude_agent_frontmatter",
    "cli_entrypoint",
    "contributing_present",
    "docs_count_claims",
    "docs_no_overclaim",
    "docs_no_phantom_files",
    "hook_protocol_correct",
    "license_present",
    "live_surface_clean",
    "package_import",
    "release_archive_builds",
    "release_archive_clean",
    "security_policy_private",
    "security_present",
    "sessionstart_no_block_claim",
    "sharp_edges_correct",
    "tests_pass",
    "tracked_noise",
    "version_consistent",
    "wheel_smoke",
})


def test_run_all_checks_covers_every_declared_check(initialized_repo_root):
    """Membership, not just cardinality: the aggregator must run exactly this
    named set. A swap (drop one check, add another) keeps the count at 22 but
    changes the set -- a bare ``len(results) == 22`` stays green through that
    regression, which is why the set assertion is the real guard.
    ``check_release_archive_builds_and_clean`` expands to two results, so the 21
    check functions in ``ALL_CHECKS`` yield these 22 result names.
    """
    results = release_check.run_all_checks(initialized_repo_root)
    got = {r.name for r in results}
    assert got == _EXPECTED_CHECK_NAMES, (
        f"check set drifted: missing {_EXPECTED_CHECK_NAMES - got}, "
        f"extra {got - _EXPECTED_CHECK_NAMES}"
    )
    # Keep the explicit result count too: it is the live cross-surface SoT pinned
    # against README's "22 individual gates" by the 'release_check result count'
    # NumericContract (tests/test_documented_claims.py). The set assert above is the
    # strengthening; this line stays so that contract keeps a surface to read.
    #
    # LOAD-BEARING ANCHOR: scripts/release_check.py::check_docs_count_claims and
    # tests/test_documented_claims.py both SCRAPE this exact single-line
    # `assert len(results) == <literal digit>` shape and FAIL LOUD if it drifts
    # (a renamed variable, a wrapped multi-line form, or a named constant in
    # place of the digit all break the scrape). Keep it literal, one line, and
    # digit-valued -- do not substitute a named constant for 22.
    assert len(results) == 22
    failures = [r for r in results if r.status == "FAIL"]
    assert not failures, (
        f"initialized repo has {len(failures)} failing check(s): "
        + "; ".join(f"{r.name}: {r.detail}" for r in failures)
    )


# ── Fail-injection ──────────────────────────────────────────────────


def _scaffold_minimal_passing_repo(root: Path) -> None:
    """Build the smallest synthetic repo that satisfies file-existence checks."""
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
    (root / "SECURITY.md").write_text(
        "# Security\n\nReport a vulnerability privately via the Security tab.\n"
        "Please do not open a public GitHub issue with vulnerability details.\n"
        "Use the private vulnerability reporting flow.\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] — 2026-05-01\n- init\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "README.md").write_text(
        "# X\n\nNot a sandbox. 2 governance agents and 3 slash commands.\n",
        encoding="utf-8",
    )
    (root / ".claude" / "agents").mkdir(parents=True)
    for i in range(2):
        (root / ".claude" / "agents" / f"a{i}.md").write_text(
            f"---\nname: a{i}\ndescription: agent {i}\n---\n# {i}\n",
            encoding="utf-8",
        )
    (root / ".claude" / "commands").mkdir()
    for i in range(3):
        (root / ".claude" / "commands" / f"c{i}.md").write_text(
            f"# command {i}\n", encoding="utf-8"
        )


def test_license_present_fails_when_missing(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "LICENSE").unlink()
    result = release_check.check_license_present(tmp_path)
    assert result.status == "FAIL"
    assert "LICENSE" in result.detail


def test_security_present_fails_when_missing(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "SECURITY.md").unlink()
    result = release_check.check_security_present(tmp_path)
    assert result.status == "FAIL"


def test_contributing_present_fails_when_missing(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CONTRIBUTING.md").unlink()
    assert release_check.check_contributing_present(tmp_path).status == "FAIL"


def test_changelog_present_fails_on_undated_file(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\nNo dated sections.\n", encoding="utf-8"
    )
    result = release_check.check_changelog_present(tmp_path)
    assert result.status == "FAIL"
    assert "dated" in result.detail.lower()


def test_security_policy_private_fails_on_public_routing(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    # Include the private-disclosure phrase so the check progresses past
    # the missing-phrase guard and into the public-routing branch.
    (tmp_path / "SECURITY.md").write_text(
        "# Security\n\n"
        "Use private vulnerability reporting via the Security tab.\n"
        "Or, alternatively, please open a public issue with the details.\n",
        encoding="utf-8",
    )
    result = release_check.check_security_policy_private(tmp_path)
    assert result.status == "FAIL"
    assert "public" in result.detail.lower()


def test_security_policy_private_fails_when_missing_phrase(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "SECURITY.md").write_text(
        "# Security\n\nWe take security seriously.\n", encoding="utf-8"
    )
    result = release_check.check_security_policy_private(tmp_path)
    assert result.status == "FAIL"


def test_security_policy_gate_parity_with_pre_release(tmp_path):
    """TP-171 §4.2 gate credibility: for a SECURITY.md that EXISTS, the
    release_check SECURITY gate and the espalier.pre_release SoT agree on every
    fixture — they share one implementation (_check_security_policy), so a policy
    that one accepts the other cannot reject. The gate's own missing-file branch
    is not shared with the SoT and is pinned separately below."""
    from espalier.pre_release import _check_security_policy

    fixtures = {
        "good": (
            "# Security\n\nReport a vulnerability privately via the Security tab.\n"
            "Please do not open a public GitHub issue with vulnerability details.\n"
            "Use the private vulnerability reporting flow.\n"
        ),
        "public_routing": (
            "# Security\n\nUse private vulnerability reporting via the Security tab.\n"
            "Or, alternatively, please open a public issue with the details.\n"
        ),
        "missing_concept": "# Security\n\nWe take security seriously.\n",
    }
    _scaffold_minimal_passing_repo(tmp_path)
    for name, body in fixtures.items():
        (tmp_path / "SECURITY.md").write_text(body, encoding="utf-8")
        gate_pass = (
            release_check.check_security_policy_private(tmp_path).status == "PASS"
        )
        sot_pass = not _check_security_policy(tmp_path)
        assert gate_pass == sot_pass, (
            f"SECURITY gate disagreement on {name!r}: "
            f"release_check pass={gate_pass}, pre_release pass={sot_pass}"
        )

    # --- Existence-guard branch: the gate's OWN logic, NOT shared with the SoT.
    # Every fixture above writes a SECURITY.md, so the gate's "file missing ->
    # FAIL" branch never fired and the parity loop only ever compared two calls
    # that share _check_security_policy. Delete the file to exercise that branch.
    # Here the two INTENTIONALLY diverge: the gate reports the missing file as
    # FAIL (its historical, standalone behaviour), while the SoT defers the
    # missing-file case to _check_required_files and returns [] (pass). Pin each
    # side to its own documented outcome — independent provenance the parity
    # self-comparison above could never reach.
    (tmp_path / "SECURITY.md").unlink()
    assert (
        release_check.check_security_policy_private(tmp_path).status == "FAIL"
    ), "gate must FAIL when SECURITY.md is missing (existence-guard branch)"
    assert _check_security_policy(tmp_path) == [], (
        "SoT _check_security_policy defers the missing-file case to "
        "_check_required_files and must report no CONTENT failures"
    )


def test_docs_count_claims_fails_on_drift(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    # README claims 2 governance agents — scaffold has 2 — passes.
    # Now add a third agent on disk so README's claim is stale.
    (tmp_path / ".claude" / "agents" / "extra.md").write_text(
        "---\nname: extra\ndescription: x\n---\n", encoding="utf-8"
    )
    result = release_check.check_docs_count_claims(tmp_path)
    assert result.status == "FAIL"
    assert "agents" in result.detail.lower()


def test_docs_count_claims_ignores_stray_non_canonical_hook(tmp_path):
    """TP-175 R3 earn-the-red: a stray non-canonical .py (a refactor backup) in
    tools/cc/hooks/ must NOT inflate release_check's hook-script count and trip
    a false-positive docs_count_claims FAIL when the docs state the canonical
    count. Third sister-site of doctor._check_doc_drift +
    audit_accuracy._live_count_hooks (the TP-174a S1 unification missed it).
    Against pre-R3 HEAD this FAILS (counts N+1)."""
    from espalier.surface_contract import get_canonical_hook_scripts

    _scaffold_minimal_passing_repo(tmp_path)
    canonical = get_canonical_hook_scripts()
    hooks_dir = tmp_path / "tools" / "cc" / "hooks"
    hooks_dir.mkdir(parents=True)
    for name in canonical:
        (hooks_dir / name).write_text("# hook\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + f"\nShips {len(canonical)} hook scripts.\n",
        encoding="utf-8",
    )
    # A stray, non-canonical file (e.g. left by a refactor) — must be ignored.
    (hooks_dir / "write_guard_backup.py").write_text("# stray\n", encoding="utf-8")

    result = release_check.check_docs_count_claims(tmp_path)
    # Offenders read "...claims N hooks (live: M)"; the stray must not inflate M.
    assert "hooks (live:" not in (result.detail or ""), (
        f"stray non-canonical hook inflated the count: {result.detail!r}"
    )
    assert result.status == "PASS", result.detail


def test_docs_count_claims_fails_loud_on_drifted_check_anchor(tmp_path):
    """TP-344 1-A earn-the-red: the live check count is scraped from the
    `assert len(results) == N` anchor in tests/test_release_check.py. If that
    anchor drifts, the scrape must FAIL LOUD, not silently fall back to 0.

    Pre-fix: the scrape returns 0 on no-match and check_docs_count_claims does
    NOT raise -> RED. Post-fix: present-but-drifted anchor raises RuntimeError.
    """
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    # Variable renamed -> the `len(results) == N` anchor no longer matches.
    (tmp_path / "tests" / "test_release_check.py").write_text(
        "def test_count():\n    assert len(all_results) == 22\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="anchor"):
        release_check.check_docs_count_claims(tmp_path)


def test_docs_count_claims_absent_test_file_is_benign(tmp_path):
    """Guardrail on the 1-A fix: a repo with NO tests/test_release_check.py must
    NOT raise -- actual_checks stays a benign 0 and the checks claim is simply
    not exercised (the scaffold makes no 'N checks' claim)."""
    _scaffold_minimal_passing_repo(tmp_path)
    assert release_check.check_docs_count_claims(tmp_path).status == "PASS"


def test_docs_count_claims_fails_loud_on_oversized_test_file(tmp_path):
    """TP-344 1-A sibling earn-the-red: a present-but-oversized (>= 500 KB)
    tests/test_release_check.py must ALSO fail loud, not silently skip the
    scrape. Skipping would leave actual_checks at 0 -- resurrecting the exact
    silent-0 the fail-loud fix exists to kill, now hidden behind the size guard.

    Pre-fix: `if size < 500_000` is False -> block skipped -> no raise -> RED.
    Post-fix: present-but-oversized raises RuntimeError before reading the file.
    The fixture file DOES carry a valid anchor, so this isolates the oversized
    path from the drifted-anchor path.
    """
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    padding = "# pad\n" * 90_000  # 540 KB > the 500 KB guard
    (tmp_path / "tests" / "test_release_check.py").write_text(
        "def test_count():\n    assert len(results) == 22\n" + padding,
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="large"):
        release_check.check_docs_count_claims(tmp_path)


def test_docs_no_overclaim_fails_on_unqualified_claim(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "README.md").write_text(
        "# X\n\nThis is a sandbox that protects you completely.\n"
        "2 governance agents and 3 slash commands.\n",
        encoding="utf-8",
    )
    result = release_check.check_docs_no_overclaim(tmp_path)
    assert result.status == "FAIL"
    assert "sandbox" in result.detail.lower()


def test_docs_no_overclaim_passes_on_calibrated_negation(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    # Already contains "Not a sandbox." — must pass.
    assert release_check.check_docs_no_overclaim(tmp_path).status == "PASS"


def test_version_consistent_fails_on_drift(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    # pyproject says 0.1.0; CHANGELOG mentions [0.1.0]; passes.
    # Now bump pyproject without updating CHANGELOG.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    result = release_check.check_version_consistent(tmp_path)
    assert result.status == "FAIL"
    assert "9.9.9" in result.detail


def test_version_consistent_reads_column0_not_indented_decoy(tmp_path):
    """TP-174b R05: routing the canonical version read through the registry
    (column-0 anchored) means an INDENTED decoy ``version = ...`` in an
    earlier [tool.*] table no longer shadows the real [project].version.
    Pre-fix the leading-\\s*-tolerant inline regex matched the decoy (which
    appears first), spuriously reading 9.9.9."""
    _scaffold_minimal_passing_repo(tmp_path)
    real = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.example]\n    version = "9.9.9"\n' + real, encoding="utf-8"
    )
    result = release_check.check_version_consistent(tmp_path)
    # Post-fix reads the column-0 0.1.0; the indented 9.9.9 decoy is ignored
    # and must not surface as a drift complaint.
    assert "9.9.9" not in result.detail, result.detail


def test_version_consistent_fails_on_dated_but_empty_section(tmp_path):
    """DEF-457/DEF-591 — the release-cut slip this gate exists to catch.

    The operator bumps the version and mints the dated header but never moves
    the notes. Pre-fix this returned PASS: the check looked at [Unreleased]
    for `### Heading` lines, CHANGELOG.md has never had one, so it matched
    nothing and reported success while the section that ships was empty.
    """
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "**Fixed**\n"
        "- the work that should have been folded\n\n"
        "## [0.2.0] — 2026-05-02\n\n"
        "## [0.1.0] — 2026-05-01\n\n"
        "- init\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.2.0"\n', encoding="utf-8"
    )
    result = release_check.check_version_consistent(tmp_path)
    assert result.status == "FAIL", result.detail
    assert "0.2.0" in result.detail


def test_version_consistent_counts_stranded_entries_in_the_bold_shape(tmp_path):
    """The stranded-entry count must see the shape the file actually uses.

    An h3-keyed counter scores the live `**Fixed**` shape at zero, which is
    the exact blindness that silenced this gate — so the failure message
    would drop the clause naming what was left behind.
    """
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "**Fixed**\n"
        "- one\n"
        "- two\n\n"
        "## [0.2.0] — 2026-05-02\n\n"
        "## [0.1.0] — 2026-05-01\n\n"
        "- init\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.2.0"\n', encoding="utf-8"
    )
    result = release_check.check_version_consistent(tmp_path)
    assert result.status == "FAIL", result.detail
    # 1 bold label + 2 bullets, all three visible to a shape-agnostic counter.
    assert "3 entries" in result.detail, result.detail


def test_version_consistent_passes_on_a_prose_release_section(tmp_path):
    """Every dated section in this project's CHANGELOG is a prose summary with
    zero bullets. An entry-only emptiness test would call a perfectly good
    release section empty and red the live tree."""
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [0.1.0] — 2026-05-01\n\n"
        "Release-readiness hardening. No bullets anywhere in this section.\n",
        encoding="utf-8",
    )
    assert release_check.check_version_consistent(tmp_path).status == "PASS"


def test_version_consistent_ignores_a_populated_unreleased_section(tmp_path):
    """Anti-regression pin: [Unreleased] carrying work is NORMAL between
    releases, and this gate runs on every push to main (the release-check job
    in release.yml has no `if:`). Re-introducing a "[Unreleased] must be
    empty" assertion here reds main for the whole pre-release period — which
    is why repointing the old `^###` detector at bullets was refuted rather
    than shipped. Uses the h3 shape deliberately: that is what the pre-fix
    detector looked for, so this case is exactly the one it would fail."""
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Fixed\n"
        "- a large staged backlog\n"
        "- that is not owed a fold until the cut\n\n"
        "## [0.1.0] — 2026-05-01\n\n"
        "Shipped notes for the current version.\n",
        encoding="utf-8",
    )
    result = release_check.check_version_consistent(tmp_path)
    assert result.status == "PASS", result.detail


def test_version_consistent_section_ends_at_a_non_bracket_header(tmp_path):
    """CHANGELOG.md carries a `## Pre-0.8 alpha — …` section that matches no
    bracket form. An extractor stopping only at `## [` would swallow it and
    the compare-link block below it, so an empty release section would read
    as populated and the gate would pass on the very slip it guards."""
    _scaffold_minimal_passing_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [0.1.0] — 2026-05-01\n\n"
        "## Pre-0.1 history — 2025\n\n"
        "Condensed early history that must not count as 0.1.0's notes.\n\n"
        "---\n\n"
        "[0.1.0]: https://example.invalid/releases/tag/v0.1.0\n",
        encoding="utf-8",
    )
    result = release_check.check_version_consistent(tmp_path)
    assert result.status == "FAIL", result.detail
    assert "0.1.0" in result.detail


def test_claude_agent_frontmatter_fails_on_missing_field(tmp_path):
    _scaffold_minimal_passing_repo(tmp_path)
    # Replace one agent with bare content (no frontmatter).
    (tmp_path / ".claude" / "agents" / "a0.md").write_text(
        "no frontmatter here\n", encoding="utf-8"
    )
    result = release_check.check_claude_agent_frontmatter(tmp_path)
    assert result.status == "FAIL"
    assert "no frontmatter" in result.detail or "missing" in result.detail


def test_aggregator_returns_failures_on_broken_repo(tmp_path):
    """run_all_checks should surface multiple FAILs on a clearly-broken repo."""
    # Empty tmp_path — almost everything will fail.
    results = release_check.run_all_checks(tmp_path)
    failures = [r for r in results if r.status == "FAIL"]
    assert len(failures) >= 5, (
        f"expected many failures on empty repo, got {len(failures)}"
    )


def test_main_exit_zero_on_passing_repo(initialized_repo_root, monkeypatch):
    """The script's main() returns 0 against an initialized self-host repo."""
    # main() reads module-global REPO_ROOT — patch it to the fixture so
    # the script runs against a properly-initialized tree (the live
    # source tree on a fresh clone lacks the gitignored runtime
    # artifacts every check depends on).
    monkeypatch.setattr(release_check, "REPO_ROOT", initialized_repo_root)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # TP-37: main() now uses argparse; pass [] explicitly so it
        # doesn't try to parse pytest's own argv from sys.argv.
        rc = release_check.main([])
    assert rc == 0, (
        f"main() returned {rc} on initialized repo. Output:\n{buf.getvalue()}"
    )


# ── canonical_urls publish-time gate (TP-189 PUBINT-1) ──────────────


import urllib.error  # noqa: E402


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self) -> int:
        return self.status


def _urlopen_returning(status: int):
    def _open(req, timeout=None):
        return _FakeResp(status)
    return _open


def _urlopen_http_error(code: int):
    def _open(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, f"err {code}", {}, None)
    return _open


def _urlopen_offline(req, timeout=None):
    raise urllib.error.URLError("Name or service not known")


def test_canonical_urls_skips_without_optin(monkeypatch):
    """Default (no opt-in env var) is SKIP and must not touch the network."""
    monkeypatch.delenv("ESPALIER_RELEASE_CHECK_WITH_URLS", raising=False)

    def _boom(req, timeout=None):  # network must not be reached
        raise AssertionError("network probed despite opt-in being off")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    result = release_check.check_canonical_urls(REPO_ROOT)
    assert result.status == "SKIP"


def test_canonical_urls_pass_on_200(monkeypatch):
    monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_URLS", "1")
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(200))
    result = release_check.check_canonical_urls(REPO_ROOT)
    assert result.status == "PASS", result.detail


def test_canonical_urls_fail_on_404(monkeypatch):
    """A URL that RESOLVES to a non-200 (the unpublished-repo state) FAILs."""
    monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_URLS", "1")
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_http_error(404))
    result = release_check.check_canonical_urls(REPO_ROOT)
    assert result.status == "FAIL"
    assert "404" in result.detail


def test_canonical_urls_skip_when_offline(monkeypatch):
    """No network (URLError) is SKIP, never FAIL — offline dev stays green."""
    monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_URLS", "1")
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_offline)
    result = release_check.check_canonical_urls(REPO_ROOT)
    assert result.status == "SKIP"
    assert "unreachable" in result.detail.lower()


# ── canonical_urls transient/transport hardening (TP-189 PUBINT-1 adversarial) ──


import http.client  # noqa: E402


def _urlopen_transport_error(exc):
    def _open(req, timeout=None):
        raise exc
    return _open


def test_probe_url_transient_5xx_is_offline_not_failure():
    """A transient 5xx/429 must classify offline (-> SKIP), never http_error
    (-> FAIL): a release cut bursts traffic to GitHub and must not fail on a
    rate-limit/blip. A stable client error (404/410/451) stays a real failure."""
    for code in (429, 500, 502, 503, 504, 408):
        assert release_check._classify_http_status(code)[0] == "offline", code
    for code in (404, 410, 451):
        assert release_check._classify_http_status(code)[0] == "http_error", code
    for code in (200, 204, 301, 302):
        assert release_check._classify_http_status(code)[0] == "ok", code


def test_canonical_urls_skip_on_transient_503(monkeypatch):
    monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_URLS", "1")
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_http_error(503))
    result = release_check.check_canonical_urls(REPO_ROOT)
    assert result.status == "SKIP", result.detail


def test_canonical_urls_skip_on_http_client_exception(monkeypatch):
    """http.client.HTTPException (IncompleteRead/BadStatusLine) is NOT an
    OSError subclass; it must be caught as a transport error (-> SKIP), not
    escape as an uncaught 'raised:' FAIL."""
    monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_URLS", "1")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _urlopen_transport_error(http.client.IncompleteRead(b"")),
    )
    result = release_check.check_canonical_urls(REPO_ROOT)
    assert result.status == "SKIP", result.detail


def test_probe_url_non_raising_non_2xx_is_not_ok(monkeypatch):
    """If urlopen returns a response without raising (e.g. a mock or odd
    transport), a non-2xx/3xx status must not be reported as ok(200)."""
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(500))
    assert release_check._probe_url("https://example.com")[0] == "offline"  # 500 transient
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(404))
    assert release_check._probe_url("https://example.com")[0] == "http_error"  # 404 dead


# ── The not-slow leg's bound ─────────────────────────────────────────


class TestNotSlowLegBound:
    """``check_tests_pass`` and the release matrix's stage 01 run the same
    ``pytest -m "not slow"`` leg, serially; both bound it from ONE recorded
    measurement here, at twice the leg (the matrix's own rule for its archive
    stages). The bare ``timeout=600`` both carried sat below the 604 s the leg
    had already measured and killed the matrix's leg at 97 % on 2026-09-23
    with no red in it; this module had no ``TimeoutExpired`` handler at all,
    so the same event here read ``raised: ...`` with the reason lost."""

    def test_the_bound_is_twice_the_recorded_leg(self):
        assert release_check.NOT_SLOW_LEG_BOUND_S == 2 * release_check.NOT_SLOW_LEG_MEASURED_S
        # never below a completed reading (604 s on 2026-09-23); a re-measure
        # moves the figure up or, on a faster box, is a deliberate re-record
        assert release_check.NOT_SLOW_LEG_MEASURED_S >= 604

    def test_check_tests_pass_hands_the_child_the_derived_bound(self, monkeypatch):
        monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_TESTS", "1")
        seen: dict = {}

        class _Done:
            returncode = 0
            stdout = "1 passed in 0.1s\n"
            stderr = ""

        def recording_run(cmd, **kwargs):
            seen.update(kwargs)
            return _Done()

        monkeypatch.setattr(release_check.subprocess, "run", recording_run)
        result = release_check.check_tests_pass(REPO_ROOT)
        assert result.status == "PASS", result
        assert seen["timeout"] == release_check.NOT_SLOW_LEG_BOUND_S, seen

    def test_a_timed_out_leg_reports_the_bound_not_an_exception(self, monkeypatch):
        monkeypatch.setenv("ESPALIER_RELEASE_CHECK_WITH_TESTS", "1")

        def raising_run(cmd, **kwargs):
            raise release_check.subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        monkeypatch.setattr(release_check.subprocess, "run", raising_run)
        result = release_check.check_tests_pass(REPO_ROOT)
        assert result.status == "FAIL", result
        assert "TIMED OUT" in result.detail and "NOT_SLOW_LEG_MEASURED_S" in result.detail, result
        assert "raised" not in result.detail


# ── The opt-in env census ───────────────────────────────────────────


class TestOptInEnvCensus:
    """``OPT_IN_ENV_FLAGS`` is the one home for the Tier-1 opt-in flag set.

    The defect these pin: ``check_tests_pass`` spawned a nested pytest with
    exactly ONE opt-in stripped, so a nested run still saw
    ``..._WITH_WHEEL_SMOKE`` -- which ``.github/workflows/release.yml`` sets at
    job scope alongside ``..._WITH_TESTS``, and which
    ``docs/RELEASE_CHECKLIST.md`` tells the maintainer to export locally. Two
    live tests in this very file then build a real wheel and provision a venv
    inside a pytest running ``--timeout 60``. The failure lands on the release
    maintainer at the one moment a red gate is most expensive, and its cause is
    the harness's own env plumbing rather than a regression.

    ``scripts/final_release_matrix.py`` kept a second, divergent copy of the set
    whose comment named ``check_tests_pass`` as its authority -- false in both
    directions: that function stripped one flag, and the copy omitted
    ``..._WITH_URLS``.
    """

    def _flags_read_by_source(self) -> set[str]:
        """Flag names the module actually reads, parsed from its own source.

        DERIVED, never a second hand-written list -- a hand-written expectation
        here would be the same defect one level up, and would go stale exactly
        when a fourth flag is added (STANDING_PRINCIPLES §14).
        """
        src = (REPO_ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8")
        # Every read IDIOM, not just the one in use today. Recognising only
        # `os.environ.get("LITERAL")` made this "derivation" a hand-written spec of
        # one spelling: a fourth flag read via os.getenv or os.environ[...] would be
        # invisible, the declared and read sets would still agree, and the leak would
        # ship with the suite green -- the same enumeration defect one level up.
        return set(re.findall(
            r"(?:os\.environ\.get\(\s*|os\.getenv\(\s*|os\.environ\[\s*)"
            r"[\"'](ESPALIER_RELEASE_CHECK_WITH_\w+)[\"']",
            src,
        ))

    def _flag_tokens_mentioned(self) -> set[str]:
        """EVERY such token in the file, however it appears.

        The backstop for a read idiom the scan above does not model at all (a
        module constant, an f-string, a getattr). A token present here but absent
        from the read set is either a new spelling or a genuinely non-read mention;
        either way it must be adjudicated rather than silently dropped.
        """
        src = (REPO_ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8")
        return set(re.findall(r"ESPALIER_RELEASE_CHECK_WITH_\w+", src))

    def test_census_equals_the_flags_the_module_reads(self):
        read = self._flags_read_by_source()
        assert read, (
            "the source scan found NO os.environ reads of an "
            "ESPALIER_RELEASE_CHECK_WITH_* flag. Either the read idiom changed "
            "-- re-point the regex -- or this test is checking nothing. Do not "
            "delete the assertion to make it green."
        )
        assert set(release_check.OPT_IN_ENV_FLAGS) == read, (
            "OPT_IN_ENV_FLAGS disagrees with the flags release_check actually "
            f"reads. Declared-only: {sorted(set(release_check.OPT_IN_ENV_FLAGS) - read)}. "
            f"Read-but-undeclared: {sorted(read - set(release_check.OPT_IN_ENV_FLAGS))}. "
            "A flag that is read but not declared LEAKS into every child process "
            "this module spawns."
        )

    def test_no_flag_token_escapes_the_census(self):
        """Backstop for a read idiom `_flags_read_by_source` does not model.

        Every ESPALIER_RELEASE_CHECK_WITH_* token in the module must be a declared
        census member. A token that is neither declared nor matched by the read
        scan is exactly the silent leak the census exists to prevent.
        """
        stray = self._flag_tokens_mentioned() - set(release_check.OPT_IN_ENV_FLAGS)
        assert not stray, (
            f"flag tokens present in release_check.py but not in OPT_IN_ENV_FLAGS: "
            f"{sorted(stray)}. If one is a real opt-in, declare it (it is currently "
            "leaking into every child process). If it is only a mention, this "
            "backstop needs an explicit, reasoned exclusion -- not deletion."
        )

    def test_every_recursion_capable_spawn_site_uses_the_stripped_env(self):
        """The census claims scope over "any child this module spawns" -- pin it.

        `test_child_env_strips_every_declared_flag` tests the HELPER. It passed
        while `check_wheel_smoke`'s `subprocess.run` inherited the full parent
        environment, all three flags included, because nothing checked the call
        SITES. Inert at the time (wheel_smoke.py never invoked pytest), but the
        next step added there would reintroduce the recursion with the suite green
        -- and the comment would still claim coverage.
        """
        src = (REPO_ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8")
        blocks = re.findall(r"subprocess\.run\((.*?)\n    \)", src, re.S)
        # Only children that can re-enter the gate matter: another interpreter
        # running repo code. A `git` or `ruff` child cannot recurse.
        risky = [b for b in blocks if "sys.executable" in b]
        assert len(risky) >= 3, (
            f"parsed only {len(risky)} sys.executable spawn sites from "
            f"release_check.py ({len(blocks)} subprocess.run blocks total). The call "
            "shape has changed and this test is checking little or nothing -- "
            "re-point the parse rather than lowering this floor."
        )
        unstripped = [b.strip().split("\n")[0][:70] for b in risky
                      if "env=child_env" not in b]
        assert not unstripped, (
            f"sys.executable spawn sites that inherit the opt-in flags: {unstripped}. "
            "Pass env=child_env_without_opt_ins() -- or narrow OPT_IN_ENV_FLAGS' "
            "stated scope, which currently claims every child this module spawns."
        )

    def test_child_env_strips_every_declared_flag(self, monkeypatch):
        for flag in release_check.OPT_IN_ENV_FLAGS:
            monkeypatch.setenv(flag, "1")
        env = release_check.child_env_without_opt_ins()
        leaked = [f for f in release_check.OPT_IN_ENV_FLAGS if f in env]
        assert not leaked, (
            f"opt-in flags leaked into the child environment: {leaked}. A child "
            "that still sees an opt-in re-enters the check that spawned it."
        )

    def test_child_env_is_a_strip_not_an_allow_list(self, monkeypatch):
        """Ordinary environment must survive.

        A minimal allow-list was the alternative shape and is the riskier one
        here: it would have to carry PATH/HOME/TMPDIR/VIRTUAL_ENV plus Windows'
        SYSTEMROOT/COMSPEC/PATHEXT, and an omission there is a cross-platform
        break rather than a leak. This pins the chosen shape so a later
        "tidy-up" to an allow-list has to argue with a red test first.
        """
        monkeypatch.setenv("ESPALIER_RELEASE_CHECK_UNRELATED_MARKER", "kept")
        env = release_check.child_env_without_opt_ins()
        assert env.get("ESPALIER_RELEASE_CHECK_UNRELATED_MARKER") == "kept"
        assert "PATH" in env

    def test_final_release_matrix_reads_the_census_rather_than_copying_it(self):
        """The sister site must IMPORT the set, not re-list it.

        Keyed on the source text, because an equality check on the imported
        value passes just as well against a hand-written copy that happens to
        agree today -- which is precisely the state this replaced.
        """
        src = (REPO_ROOT / "scripts" / "final_release_matrix.py").read_text(
            encoding="utf-8"
        )
        assert "from release_check import OPT_IN_ENV_FLAGS" in src, (
            "final_release_matrix.py no longer imports the census. If it "
            "re-lists the flags, the two copies drift -- which they already did "
            "once, in both directions at the same time."
        )
        literals = re.findall(r"[\"'](ESPALIER_RELEASE_CHECK_WITH_\w+)[\"']", src)
        assert not literals, (
            f"final_release_matrix.py hand-lists opt-in flag literals: {literals}. "
            "Read them from release_check.OPT_IN_ENV_FLAGS instead."
        )


# ── The required-content floor: one home for both validation paths ──────


def _scratch_archive(path: Path, rel_members: list[str]) -> Path:
    """A release-shaped ZIP: every member under the version-stamped root the
    builder writes, so the classifier reads repo-relative paths."""
    import zipfile

    with zipfile.ZipFile(path, "w") as zf:
        for rel in rel_members:
            zf.writestr(f"espalier-harness-0.0.0/{rel}", "x\n")
    return path


class TestRequiredContentFloor:
    """``--validate-archive`` ran only the three reject-scanners, so a
    near-empty ZIP passed it as clean (exit 0 at HEAD before these rows,
    recorded), while the built-archive check carried the floor inline. Both
    paths now read ``REQUIRED_ARCHIVE_MEMBERS``."""

    _NEAR_EMPTY_MISSING = [m for m in release_check.REQUIRED_ARCHIVE_MEMBERS if m != "README.md"]

    def test_validate_archive_fails_a_near_empty_zip_naming_the_missing_members(
        self, tmp_path, capsys
    ):
        zip_path = _scratch_archive(tmp_path / "near_empty.zip", ["README.md"])
        rc = release_check._validate_existing_archive(zip_path)
        out = capsys.readouterr().out.strip()
        assert rc == 1
        assert out == f"FAIL: {zip_path} missing required content: " + ", ".join(
            self._NEAR_EMPTY_MISSING
        )

    def test_validate_archive_passes_a_complete_zip(self, tmp_path, capsys):
        zip_path = _scratch_archive(
            tmp_path / "complete.zip",
            [*release_check.REQUIRED_ARCHIVE_MEMBERS, "CHANGELOG.md"],
        )
        rc = release_check._validate_existing_archive(zip_path)
        out = capsys.readouterr().out
        assert rc == 0 and out.startswith("PASS:") and "content floor" in out

    def test_the_cli_reads_the_floor_too(self, tmp_path, capsys):
        zip_path = _scratch_archive(tmp_path / "near_empty.zip", ["README.md"])
        assert release_check.main(["--validate-archive", str(zip_path)]) == 1
        assert "missing required content" in capsys.readouterr().out

    def test_both_paths_name_the_same_missing_members(self, tmp_path, monkeypatch, capsys):
        """The built-archive check, with the builder stubbed to hand back the
        same near-empty ZIP, reports the members the standalone validator
        does: one tuple, two readers."""
        import types

        zip_path = _scratch_archive(tmp_path / "near_empty.zip", ["README.md"])
        stub = types.ModuleType("build_release_archive")
        stub.build_release_archive = lambda repo_root, output_dir: zip_path
        monkeypatch.setitem(sys.modules, "build_release_archive", stub)
        builds, clean = release_check.check_release_archive_builds_and_clean(tmp_path)
        assert builds.status == "PASS", builds
        expected = release_check.missing_required_members(["espalier-harness-0.0.0/README.md"])
        assert expected == self._NEAR_EMPTY_MISSING
        assert (clean.status, clean.detail) == (
            "FAIL", "missing required content: " + ", ".join(expected)
        )
        assert release_check._validate_existing_archive(zip_path) == 1
        assert capsys.readouterr().out.strip().endswith(", ".join(expected))

    def test_the_member_list_has_one_home(self):
        """Source-keyed: the built-archive check reads the shared tuple rather
        than carrying its own copy, which is the state this replaced, and the
        tuple itself derives from the pre-release gate's public-file census
        rather than re-listing it (a third copy had already dropped three)."""
        src = (REPO_ROOT / "scripts" / "release_check.py").read_text(encoding="utf-8")
        assert src.count('"espalier/__init__.py"') == 1
        assert src.count("missing_required_members(members)") == 2  # the two readers
        from espalier.pre_release import REQUIRED_PUBLIC_FILES

        assert set(REQUIRED_PUBLIC_FILES) < set(release_check.REQUIRED_ARCHIVE_MEMBERS)
        assert "*REQUIRED_PUBLIC_FILES," in src

    def test_the_floor_is_anchored_at_the_archive_root(self):
        """A required name under a wrong root (``docs/README.md``) does not
        satisfy the floor: the match strips the version-stamped root and
        nothing else, the same anchor the classifier reads."""
        required = list(release_check.REQUIRED_ARCHIVE_MEMBERS)
        under_docs = [f"espalier-harness-0.0.0/docs/{r}" for r in required]
        assert release_check.missing_required_members(under_docs) == required
        at_root = [f"espalier-harness-0.0.0/{r}" for r in required]
        assert release_check.missing_required_members(at_root) == []
        assert release_check.missing_required_members(required) == []  # no root at all
