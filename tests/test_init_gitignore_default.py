"""TP-119: ``espalier init`` defaults to writing harness-managed
entries into ``.gitignore`` unless the adopter explicitly passes
``--no-write-gitignore``.

Pins the default-on behavior introduced in v0.7.9 (breaking change
relative to v0.7.8 and earlier, where the gitignore write was
opt-in via ``--write-gitignore``).

Sister-class to ``test_init_gitignore_protection.py`` (TP-30): that
file exercises the EXPLICIT flag branches (``--write-gitignore`` vs
``--no-write-gitignore``) and the post-write ``git add -A``
contract. This file pins the DEFAULT — a bare ``espalier init .``
with no flag.

Failure mode prevented: adopters following QUICKSTART literally
ran ``espalier init .`` then ``git add -A`` and committed
``.claude/settings.json`` + ``reports/*.json`` +
``.espalier/integrity.json``. The opt-in default left the
``.gitignore`` write to operator discipline, which the SHARP_EDGES
"Init Suggestions Gated on File Existence Miss the Fresh-Repo
Flow" class predicts will fail half the time. Pinning the default
catches an accidental reversion of the flip.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from espalier import cli
from espalier.cli import REQUIRED_GITIGNORE, _gitignore_key
from tests._git_oracle import require_is_gitignored


REQUIRED_IGNORE_PATHS = (
    ".claude/settings.json",
    ".espalier/",
    ".espalier-state/",
    "/reports/",
    "cc/blueprints/",
    "cc/_cold/",
    "cc/_working_summary.md",
    "cc/GOAL.md",
    "cc/execution_plan.json",
    "cc/execution_plan.json.lock",
    "cc/discard_snapshots.log",
    "__pycache__/",
    "*.pyc",
    ".claude/*.new",
    ".claude/*.bak",
    ".claude/*.bak.*",
    "/task-packs/*",
)


def test_required_ignore_paths_match_cli_source() -> None:
    """Durable drift guard (TP-214..219 follow-up): this fixture's
    REQUIRED_IGNORE_PATHS must mirror ``cli.REQUIRED_GITIGNORE`` exactly.
    Without it, a new managed-gitignore entry added to cli.py could land
    without ever updating this fixture, leaving the entry unpinned -- the exact
    gap the TP-214..219 verification pass surfaced for ``cc/_working_summary.md``.
    """
    assert set(REQUIRED_IGNORE_PATHS) == set(REQUIRED_GITIGNORE)


#: The one runtime-generated file the block must NOT ignore, and why.
#: ``install-ci`` parks it beside a workflow the host already tracks and tells
#: the operator to diff and merge it; an ignore rule would hide the file that
#: warning sends them to read.
_RUNTIME_GENERATED_LEFT_VISIBLE = {".github/workflows/harness-guard.yml.new"}


def test_every_runtime_generated_file_is_ignored_by_the_rendered_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The roster of files deployed code creates on an adopter's tree is the
    derive source; the block ``init`` appends must cover every member.

    Before this pin the two were typed separately and had drifted: the roster
    named the plan file as runtime state while the block left it out, so the
    shipped commit command staged an ``in_progress`` plan, and the plan gate
    in every fresh clone of that repository was open before any session had
    opened a plan.

    What this holds: every file ON THE ROSTER is ignored. What it cannot
    hold: that a new runtime file reaches the roster. Nothing derives the
    roster from the code's write sites, so that step is still a person's.

    Git is asked, in a repository whose only ignore rules are the rendered
    block: the operator's global excludes commonly carry ``*.log``, which
    would green the snapshot log on that machine alone. Every place git reads
    a global ignore list from is pointed at an empty directory (the config
    file's ``core.excludesFile``, and the default file under the XDG config
    home), and the precondition asks about the WHOLE roster, so an ignore
    rule this isolation missed reds here and not as a false green below.
    """
    from espalier import surface_contract

    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    roster = set(surface_contract.ADOPTER_RUNTIME_GENERATED)
    already = sorted(rel for rel in roster if require_is_gitignored(repo, rel))
    assert not already, (
        f"the scratch repository ignores {already} before any block was "
        "written, so a green below would prove nothing about the block"
    )

    cli._handle_gitignore(repo, write_gitignore=True)

    assert _RUNTIME_GENERATED_LEFT_VISIBLE <= roster, (
        "an exemption for a path the roster no longer names: delete it"
    )
    unignored = sorted(
        rel for rel in roster - _RUNTIME_GENERATED_LEFT_VISIBLE
        if not require_is_gitignored(repo, rel)
    )
    assert not unignored, (
        f"deployed code creates {unignored} on an adopter's tree and the block "
        "init appends does not ignore it: add it to cli.REQUIRED_GITIGNORE"
    )
    hidden = sorted(
        rel for rel in _RUNTIME_GENERATED_LEFT_VISIBLE
        if require_is_gitignored(repo, rel)
    )
    assert not hidden, f"meant to stay visible, and the block ignores it: {hidden}"


def test_a_committed_runtime_file_is_told_to_be_untracked_not_kept(
    fresh_repo: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """An entry is withheld when the repository already tracks the path, and
    the message closed with "Otherwise keep them as they are -- the harness
    will not manage a path you already own". That is right for a settings
    file the adopter wrote, and wrong for a file the harness rewrites while it
    runs: the adopter who committed the plan tracker's state (the population
    the new entry exists for) was told keeping it was fine, and every `mark`
    from then on changed a tracked file."""
    (fresh_repo / "cc").mkdir()
    (fresh_repo / "cc" / "execution_plan.json").write_text("{}\n", encoding="utf-8")
    (fresh_repo / ".claude").mkdir()
    (fresh_repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "cc/execution_plan.json", ".claude/settings.json"],
                   cwd=fresh_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "committed before the entries existed"],
                   cwd=fresh_repo, check=True)
    capsys.readouterr()

    cli._handle_gitignore(fresh_repo, write_gitignore=True)

    out = capsys.readouterr().out
    assert "git rm --cached -- cc/execution_plan.json" in out
    assert "git rm --cached -- .claude/settings.json" in out
    keep = [ln for ln in out.splitlines() if "keep" in ln.lower()]
    assert keep, "the adopter's own settings file may still be kept"
    assert not any("execution_plan" in ln for ln in keep), keep
    assert any(".claude/settings.json" in ln for ln in keep), keep
    runtime = [ln for ln in out.splitlines() if "while it runs" in ln]
    assert runtime and "cc/execution_plan.json" in " ".join(runtime), out


def _terminators(data: bytes) -> tuple[int, int]:
    """``(crlf, bare_lf)``: how many lines end each way."""
    crlf = data.count(b"\r\n")
    return crlf, data.count(b"\n") - crlf


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_the_append_keeps_the_files_own_line_ending(tmp_path: Path, eol: bytes) -> None:
    """The block is appended in the ending the file already uses. It was
    written through a text-mode append, so on Windows every appended line
    landed as CRLF under an LF file, and on a POSIX host every one landed as
    LF under a CRLF file: a mixed-ending ``.gitignore`` on day one, which git
    commits silently unless the repository normalises."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"node_modules/" + eol + b"dist/" + eol)

    cli._handle_gitignore(tmp_path, write_gitignore=True)

    data = gitignore.read_bytes()
    assert data.count(cli.GITIGNORE_BLOCK_HEADER.encode("utf-8")) == 1, (
        "the block was not appended, so the endings below prove nothing"
    )
    crlf, bare_lf = _terminators(data)
    if eol == b"\n":
        assert crlf == 0, f"{crlf} CRLF line(s) appended to an LF file"
    else:
        assert bare_lf == 0, f"{bare_lf} bare-LF line(s) appended to a CRLF file"


def test_the_append_follows_the_dominant_ending_of_a_mixed_file(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"a/\r\nb/\r\nc/\n")

    cli._handle_gitignore(tmp_path, write_gitignore=True)

    appended = gitignore.read_bytes()[len(b"a/\r\nb/\r\nc/\n"):]
    crlf, bare_lf = _terminators(appended)
    assert crlf and bare_lf == 0, (crlf, bare_lf)


@pytest.mark.parametrize("seed", [None, b"node_modules/"], ids=["no-file", "no-terminator"])
def test_a_file_with_no_ending_of_its_own_gets_lf(tmp_path: Path, seed: bytes | None) -> None:
    """Nothing to follow, so LF: what git writes on every platform, and what
    this repository's own attributes pin for text."""
    gitignore = tmp_path / ".gitignore"
    if seed is not None:
        gitignore.write_bytes(seed)

    cli._handle_gitignore(tmp_path, write_gitignore=True)

    data = gitignore.read_bytes()
    assert cli.GITIGNORE_BLOCK_HEADER.encode("utf-8") in data
    crlf, _bare_lf = _terminators(data)
    assert crlf == 0, f"{crlf} CRLF line(s) in a file that had no ending to follow"
    if seed is not None:
        assert data.startswith(seed + b"\n"), "the block must not join the last line"


@pytest.fixture
def fresh_repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# placeholder\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)],
                   check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"],
                   cwd=tmp_path, check=True)
    return tmp_path


def _run_init(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(repo), *extra],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )


def test_init_defaults_to_writing_gitignore(fresh_repo: Path) -> None:
    """A bare ``espalier init .`` writes the required entries to
    ``.gitignore`` without prompting the operator."""
    result = _run_init(fresh_repo)
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    gitignore = fresh_repo / ".gitignore"
    assert gitignore.exists(), (
        "Default init should have created .gitignore.\n"
        f"stdout:\n{result.stdout}"
    )
    gi_text = gitignore.read_text(encoding="utf-8")
    for required in REQUIRED_IGNORE_PATHS:
        assert required in gi_text, (
            f"Missing {required!r} in default-init .gitignore.\n"
            f".gitignore contents:\n{gi_text}"
        )


def test_init_no_write_gitignore_suppresses(fresh_repo: Path) -> None:
    """``--no-write-gitignore`` restores the pre-v0.7.9 warn-only
    behavior: no .gitignore is written, but the entries appear in
    stdout for copy-paste."""
    result = _run_init(fresh_repo, "--no-write-gitignore")
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    gitignore = fresh_repo / ".gitignore"
    if gitignore.exists():
        body = gitignore.read_text(encoding="utf-8")
        for required in REQUIRED_IGNORE_PATHS:
            assert required not in body, (
                f"--no-write-gitignore should not write {required!r} "
                f"into .gitignore, but found it.\n"
                f".gitignore contents:\n{body}"
            )
    # Each required entry should still appear in stdout (copy-paste
    # block) so the operator can act manually.
    for required in REQUIRED_IGNORE_PATHS:
        assert required in result.stdout, (
            f"Suggest-only init should print {required!r} in stdout."
        )


def test_init_legacy_write_gitignore_flag_still_accepted(fresh_repo: Path) -> None:
    """``--write-gitignore`` continues to work as a no-op flag (the
    flip made it the default, but explicit pass should not raise)."""
    result = _run_init(fresh_repo, "--write-gitignore")
    assert result.returncode == 0, (
        f"--write-gitignore (legacy explicit) should still succeed.\n"
        f"stderr:\n{result.stderr}"
    )
    gitignore = fresh_repo / ".gitignore"
    assert gitignore.exists(), (
        "Explicit --write-gitignore should still create the file."
    )


def test_init_mutually_exclusive_flags(fresh_repo: Path) -> None:
    """Passing both ``--write-gitignore`` and ``--no-write-gitignore``
    fails per argparse mutex-group semantics."""
    result = _run_init(
        fresh_repo, "--write-gitignore", "--no-write-gitignore"
    )
    assert result.returncode != 0, (
        "argparse should reject both flags at once.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "not allowed with" in result.stderr.lower() or "mutually" in result.stderr.lower()


def test_narrower_subpath_does_not_satisfy_broad_ignore(fresh_repo: Path) -> None:
    """TP-148 148-E: a pre-existing ``.gitignore`` that ignores only a
    narrower sub-path (``reports/sub/``) must NOT be treated as already
    covering the broad ``reports/`` entry. The bare ``entry not in gi_text``
    substring check counted ``reports/`` as present (it is a substring of
    ``reports/sub/``) and silently dropped the broad-ignore suggestion;
    line-exact membership must still surface ``reports/`` as needed while
    leaving the other (exactly-present) entries un-suggested.
    """
    # Seed every required entry EXACTLY, except `/reports/` which is present
    # only as the narrower `reports/sub/`.
    seeded = [
        p if p != "/reports/" else "reports/sub/"
        for p in REQUIRED_IGNORE_PATHS
    ]
    (fresh_repo / ".gitignore").write_text("\n".join(seeded) + "\n", encoding="utf-8")

    result = _run_init(fresh_repo, "--no-write-gitignore")
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    # The suggestion block prints each still-needed entry on its own line.
    suggested = {
        ln.strip() for ln in result.stdout.splitlines()
        if ln.strip() in REQUIRED_IGNORE_PATHS
    }
    assert "/reports/" in suggested, (
        "Broad '/reports/' must still be suggested when only 'reports/sub/' "
        f"is ignored.\nstdout:\n{result.stdout}"
    )
    # The exactly-present entries must NOT be re-suggested.
    assert suggested == {"/reports/"}, (
        f"Only '/reports/' should be suggested; got {suggested}.\n"
        f"stdout:\n{result.stdout}"
    )


def test_preexisting_unanchored_entry_is_not_re_suggested(fresh_repo: Path) -> None:
    """DEF-429 upgrade path: anchoring must not re-suggest entries the
    harness already wrote in their unanchored form.

    Every tree initialized before the anchor carries the bare ``reports/``,
    ``.espalier/`` and ``.espalier-state/``. Those patterns are strictly
    BROADER than the anchored ones -- they ignore the repo-root directory
    the harness needs ignored, and more besides -- so they genuinely satisfy
    the requirement. A membership check that compares the anchored literal
    only would report all three as missing and grow the adopter's .gitignore
    by three duplicate lines on every re-init.
    """
    (fresh_repo / ".gitignore").write_text(
        "\n".join(p.lstrip("/") for p in REQUIRED_IGNORE_PATHS) + "\n",
        encoding="utf-8",
    )
    result = _run_init(fresh_repo, "--no-write-gitignore")
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    suggested = {
        ln.strip() for ln in result.stdout.splitlines()
        if ln.strip() in REQUIRED_IGNORE_PATHS
    }
    assert not suggested, (
        "An unanchored pre-existing entry is broader than the anchored form "
        "and already satisfies it, but init re-suggested: "
        f"{sorted(suggested)}.\nstdout:\n{result.stdout}"
    )


# Entries that float to EVERY depth on purpose. The discriminator is whether
# the NAME could collide with adopter-owned content: bytecode cannot, and
# `.espalier*` is the harness's own namespace, so for those any-depth costs
# nothing and protects more (a hook whose root mis-resolves, an extracted
# archive inside the tree). Anything else single-segment is the DEF-429 shape
# -- a generic name an adopter may own -- and must be anchored.
_ANY_DEPTH_BY_DESIGN = frozenset({
    "__pycache__/", "*.pyc", ".espalier/", ".espalier-state/",
})


def test_required_entry_shapes_are_covered() -> None:
    """Every entry must use a shape ``cli._ignore_pattern_matches`` handles,
    and must be anchored unless any-depth is deliberate.

    This is the gate ``_ignore_pattern_matches``'s docstring names. Without
    it, a maintainer adding a bare ``logs/`` reproduces DEF-429 exactly --
    silently excluding an adopter's ``src/**/logs/`` -- against a fully green
    suite, because ``test_ignore_matcher_agrees_with_git`` only compares the
    entries against a hand-written probe list and no probe would mention
    ``logs``. That test proves the matcher AGREES with git; this one proves
    the entry SAYS what the harness means.
    """
    for entry in REQUIRED_GITIGNORE:
        assert "**" not in entry, (
            f"{entry!r} uses `**`, which cli._ignore_pattern_matches does not "
            "handle -- it would report 'no conflict' for every path and the "
            "ownership check would silently pass."
        )
        assert not entry.startswith("!"), (
            f"{entry!r} is a negation; the matcher has no inversion arm."
        )
        assert "[" not in entry, (
            f"{entry!r} uses a character class, which the matcher does not "
            "handle."
        )
        assert "?" not in entry, (
            f"{entry!r} uses a single-character wildcard; the matcher, the "
            "uninstall's witness walk and its derived planter "
            "(tests/test_cleanup.py::_plant_survivor) all read only `*`, and a "
            "`?` entry would green the planter's literal file by matching it."
        )
        core = entry.strip("/")
        if "/" not in core and not entry.startswith("/"):
            assert entry in _ANY_DEPTH_BY_DESIGN, (
                f"{entry!r} carries no leading or embedded separator, so git "
                f"matches it at EVERY depth -- it would also exclude an "
                f"adopter's own src/**/{core}/ (DEF-429). Anchor it as "
                f"'/{core}/', or add it to _ANY_DEPTH_BY_DESIGN with a reason."
            )


def test_ignore_matcher_agrees_with_git(tmp_path: Path) -> None:
    """The ownership check's matcher must agree with real git on every
    pattern in ``REQUIRED_GITIGNORE``.

    ``cli._ignore_pattern_matches`` is a hand-written approximation of
    gitignore semantics, scoped to the shapes this tuple contains. Reading
    the man page is not evidence that it matches git, and getting the
    anchoring rule wrong is exactly the DEF-429 defect it exists to prevent
    -- so git itself is the oracle. Each pattern is written to a throwaway
    ``.gitignore`` ALONE (git resolves overlaps by last-match-wins, which
    would make a combined comparison ambiguous), then ``git check-ignore
    --no-index`` is asked about every probe path.

    This doubles as the shape-coverage guard: a future entry using a shape
    the matcher does not handle (``**``, negation, a character class) reds
    here instead of silently going unchecked in the ownership report.
    """
    probes = (
        ".claude/settings.json",
        ".claude/sub/settings.json",
        ".claude/x.new",
        ".claude/x.bak",
        # Directory inheritance: when a pattern matches a path COMPONENT and
        # that component is a directory, git excludes everything beneath it.
        # A leaf-only matcher reports "no conflict" here and writes the entry
        # over a tracked path -- the DEF-11 state, from the DEF-11 check.
        ".claude/x.new/y",
        ".claude/x.bak/deep/z",
        ".claude/settings.json/y",
        "src/foo.pyc/bar",
        "reports/sub/deep/x.json",
        ".espalier/integrity.json",
        "src/.espalier/integrity.json",
        ".espalier-state/flag",
        "src/.espalier-state/flag",
        "reports/repo_fingerprint.json",
        "src/analytics/reports/q4.md",
        "reportsx/a.md",
        "cc/blueprints/latest.json",
        "src/cc/blueprints/latest.json",
        "cc/_working_summary.md",
        "__pycache__/x.pyc",
        "src/pkg/__pycache__/x.pyc",
        "src/pkg/mod.pyc",
        "src/main.py",
        "docs/reports.md",
        # Case-varied: git is case-INSENSITIVE on macOS/Windows checkouts, so
        # on those hosts these ARE matches and a case-blind matcher misses the
        # conflict, silently creating the state the ownership check prevents.
        "Reports/q4.md",
        ".Claude/settings.json",
        "src/__PYCACHE__/x.pyc",
    )
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    gitignore = tmp_path / ".gitignore"
    # Ask THIS repo what git will do rather than guessing from the platform;
    # git sets core.ignorecase at init time by probing the filesystem.
    case_proc = subprocess.run(
        ["git", "config", "--type=bool", "core.ignorecase"],
        cwd=tmp_path, capture_output=True, text=True, check=False, encoding="utf-8",
    )
    fold = case_proc.stdout.strip() == "true"

    disagreements = []
    for entry in REQUIRED_GITIGNORE:
        gitignore.write_text(entry + "\n", encoding="utf-8")
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", "--", *probes],
            cwd=tmp_path, capture_output=True, text=True, check=False, encoding="utf-8",
        )
        assert proc.returncode in (0, 1), (
            f"git check-ignore errored for {entry!r}: {proc.stderr}"
        )
        git_says = {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}
        for probe in probes:
            ours = cli._ignore_pattern_matches(entry, probe, fold=fold)
            theirs = probe in git_says
            if ours != theirs:
                disagreements.append(
                    f"  pattern {entry!r} vs path {probe!r}: "
                    f"matcher={ours}, git={theirs}"
                )
    assert not disagreements, (
        "cli._ignore_pattern_matches disagrees with git:\n"
        + "\n".join(disagreements)
    )


def test_preexisting_unanchored_entry_gets_an_advisory(fresh_repo: Path) -> None:
    """The upgrade path must not be silent.

    ``_gitignore_key`` treats the bare ``reports/`` an older ``init`` wrote as
    satisfying ``/reports/`` -- correct, because it is strictly broader, and
    it is what stops re-init appending duplicates. But "satisfies the harness"
    and "is what the adopter wants" are different claims: the bare form also
    excludes their own ``src/analytics/reports/``. Without a word at re-init,
    the entire pre-fix installed base keeps DEF-429 forever, and nothing will
    ever mention it again.
    """
    (fresh_repo / ".gitignore").write_text(
        "\n".join(p.lstrip("/") for p in REQUIRED_IGNORE_PATHS) + "\n",
        encoding="utf-8",
    )
    result = _run_init(fresh_repo)
    assert result.returncode == 0, (
        f"init failed (stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    assert "matches at EVERY depth" in result.stdout, (
        "Re-init on a pre-fix .gitignore said nothing about the unanchored "
        f"entries.\nstdout:\n{result.stdout}"
    )
    for bare in ("reports",):
        assert f"{bare}/  -- also excludes" in result.stdout, (
            f"advisory did not name {bare!r}.\nstdout:\n{result.stdout}"
        )
    # And it still must not rewrite their file.
    body = (fresh_repo / ".gitignore").read_text(encoding="utf-8")
    assert "/reports/" not in body, (
        "init rewrote the adopter's .gitignore instead of advising.\n" + body
    )


def test_quickstart_block_equals_the_canon() -> None:
    """QUICKSTART's copy-paste fence must be the WHOLE of ``REQUIRED_GITIGNORE``,
    rendered the way ``init`` writes it (``cli.render_gitignore_entries``: the
    ``!`` re-includes directly under ``/task-packs/*``, or they re-include nothing).

    **This was a subset check, and the subset was wrong.** The previous
    docstring justified showing five of ten on the grounds that *"the
    ``__pycache__``/``*.pyc`` hygiene pair and the ``.claude/*.new`` render
    artifacts are noise in a quickstart."* That judgement contradicted
    ``cli.REQUIRED_GITIGNORE``'s own comment on the very same two entries --
    *"else an adopter commits hook bytecode on day one"* -- so the repo carried
    two sources of truth with opposite verdicts, and the doc followed the
    wrong one.

    Measured before overturning it, on a throwaway tree with ``init`` driven
    and the hooks run once: pasting the five-entry fence stages **8** bytecode
    files on the next ``git add -A``; pasting the ten-entry block stages **0**.
    The block is the documented remedy for ``--no-write-gitignore``, so its
    whole job is to leave the adopter where ``init`` would have -- and five
    entries did not.

    Equality, not subset, because both failure directions are now real: an
    entry in the doc that is not in the canon sends adopters to paste a line
    the code never writes, and an entry in the canon absent from the doc is
    the day-one bytecode commit above. The fence is generated by
    ``scripts/generate_doc_regions.py``, so the fix for a red here is to run
    that script, not to retype the block.
    """
    body = (Path(__file__).resolve().parents[1]
            / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    # Read the header from its single owner rather than restating it: this
    # test was the fifth hand-copy of that literal.
    assert cli.GITIGNORE_BLOCK_HEADER in body, (
        "QUICKSTART's gitignore fence header moved; re-point this test."
    )
    after = body.split(cli.GITIGNORE_BLOCK_HEADER, 1)[1]
    fence = after.split("```", 1)[0]
    listed = [ln.strip() for ln in fence.splitlines() if ln.strip()]
    canon = cli.render_gitignore_entries(REQUIRED_GITIGNORE)
    assert listed == canon, (
        "QUICKSTART's gitignore fence no longer equals cli.REQUIRED_GITIGNORE.\n"
        f"  fence : {listed}\n"
        f"  canon : {canon}\n"
        "  Run `python3 scripts/generate_doc_regions.py` -- the fence is a "
        "generated region, not a hand-typed copy."
    )


# ---------------------------------------------------------------------------
# DEF-445 / DEF-524: task-packs/ is local-only state
# ---------------------------------------------------------------------------


def test_init_does_not_leave_the_adopter_committing_task_packs(
    fresh_repo: Path,
) -> None:
    """`init` seeds `task-packs/`; the adopter commits its ledger, never a draft.

    DEF-445, driven rather than read: before the fix, `init` created
    `task-packs/` in every adopter repo whose sole content was a router
    CLAUDE.md, `git check-ignore` returned rc=1 on it, and `git add -A`
    staged it -- so every adopter committed a bare directory they never
    asked for, while the deployed `.claude/commands/implement-pack.md` told
    them their pack drafts were gitignored local state.

    Since 2026-09-30 the folder is ignored by its CONTENTS (`/task-packs/*`)
    with three files re-included beneath it: the forward ledger `init` now
    seeds, its probes file and the router -- the operator's decision that the
    ledger is the adopter's tracked work record. The drafts stay local. So the
    staged set is pinned EXACTLY: every re-included file that exists, and not
    one other path under `task-packs/` -- a planted draft and a landed pack
    included."""
    result = _run_init(fresh_repo)
    assert result.returncode == 0, result.stderr

    router = fresh_repo / "task-packs" / "CLAUDE.md"
    ledger = fresh_repo / "task-packs" / "FORWARD_LEDGER.md"
    assert router.is_file() and ledger.is_file(), (
        "init no longer seeds the task-packs router and ledger; this test is "
        "pinned to the tracked-ledger arrangement and must be revisited"
    )
    (fresh_repo / "task-packs" / "TP-1-a-draft.md").write_text("draft\n", encoding="utf-8")
    (fresh_repo / "task-packs" / "Done").mkdir()
    (fresh_repo / "task-packs" / "Done" / "TP-0-landed.md").write_text("done\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=fresh_repo, check=True,
                   capture_output=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=fresh_repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.split()
    in_packs = sorted(p for p in staged if p.startswith("task-packs/"))
    expected = sorted(p for p in cli.REINCLUDED_PATHS if (fresh_repo / p).is_file())
    # An independent side: `expected` is derived from the constant, so a path
    # dropped from it would shrink both sides and pass.
    assert {"task-packs/CLAUDE.md", "task-packs/FORWARD_LEDGER.md"} <= set(in_packs), in_packs
    assert in_packs == expected, (
        f"`git add -A` staged {in_packs} under task-packs/; the block re-includes "
        f"exactly {expected}. A draft staging is the adopter committing the local "
        "state the deployed docs call gitignored; a re-included file missing is "
        "the ledger left untracked."
    )


def test_the_adopters_own_nested_task_packs_still_stages(
    fresh_repo: Path,
) -> None:
    """The entry must be ANCHORED -- the un-anchored form eats adopter source.

    Driven against real git before choosing the spelling: a bare
    `task-packs/` matches at EVERY depth, so an adopter with their own
    `src/vendor/task-packs/` silently loses it from `git add -A`. That is
    DEF-429 reintroduced under a new name, and it is invisible without this
    arm because the harness's own directory is ignored either way.
    """
    own = fresh_repo / "src" / "vendor" / "task-packs"
    own.mkdir(parents=True)
    (own / "engine.py").write_text("# the adopter's own code\n", encoding="utf-8")

    result = _run_init(fresh_repo)
    assert result.returncode == 0, result.stderr

    subprocess.run(["git", "add", "-A"], cwd=fresh_repo, check=True,
                   capture_output=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=fresh_repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.split()
    assert "src/vendor/task-packs/engine.py" in staged, (
        "the adopter's OWN nested task-packs/ was excluded -- the required "
        "entry is un-anchored and is swallowing their source (DEF-429). "
        f"staged: {staged}"
    )


def _stale_the_deployed_stamp(repo: Path) -> None:
    """Rewrite the deployed version stamp so `upgrade` takes the STALE path.

    Without this the test exercises only the version-current early return --
    and that is the wrong population entirely. The fix's own reason is "an
    adopter who installed once and thereafter runs `upgrade`", and that
    adopter's deployment is by definition stale. Proven necessary: with the
    stamp left current, removing the main-flow `_handle_gitignore` call is a
    mutation that SURVIVES.
    """
    manifest = repo / "cc" / "PACK_MANIFEST.txt"
    lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    for line in lines:
        if line.startswith("# espalier-version:"):
            out.append("# espalier-version: 0.8.0a1\n")
        else:
            out.append(line)
    manifest.write_text("".join(out), encoding="utf-8")


@pytest.mark.parametrize("stale", [False, True],
                         ids=["version-current", "version-stale"])
def test_upgrade_delivers_required_gitignore_entries_to_the_installed_base(
    fresh_repo: Path, stale: bool,
) -> None:
    """`upgrade` must reach the gitignore, or no existing adopter ever gets it.

    Found while landing the entry above, and it is wider than that entry:
    `_handle_gitignore` had exactly ONE call site (`_print_init_summary`,
    reached only from `cmd_init`), so an adopter who installed once and
    thereafter runs `upgrade` -- the verb the CLI itself recommends when the
    deployed version is stale -- received NONE of the required entries added
    since their install. Every one of them, not just this fix.

    This is the DEF-428 lesson one layer deeper: the CLAUDE.md nudge was
    repaired to fire on `upgrade` for exactly this reason, and
    `cmd_upgrade` calls it -- while the gitignore path beside it was left
    on the init-only route.
    """
    result = _run_init(fresh_repo, "--no-write-gitignore")
    assert result.returncode == 0, result.stderr
    gitignore = fresh_repo / ".gitignore"
    assert not gitignore.exists() or "task-packs" not in gitignore.read_text(encoding="utf-8"), (
        "fixture precondition failed: the entry is already present before "
        "upgrade ran, so this test could not observe upgrade delivering it"
    )

    if stale:
        _stale_the_deployed_stamp(fresh_repo)
    upgraded = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "upgrade", str(fresh_repo),
         "--execute"],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )
    assert upgraded.returncode == 0, (
        f"upgrade failed (stdout={upgraded.stdout!r}, "
        f"stderr={upgraded.stderr!r})"
    )
    # Assert on the ARTIFACT, not the message. The first cut of this test
    # grepped stdout for the entry name and failed while the fix was working
    # -- the write path reports a COUNT, not the names. What the installed
    # base actually needs is the entry on disk.
    assert gitignore.is_file(), (
        "`upgrade` did not create .gitignore at all, so the installed base "
        f"gets no protection.\nstdout:\n{upgraded.stdout}"
    )
    written = gitignore.read_text(encoding="utf-8")
    missing = [e for e in REQUIRED_GITIGNORE if _gitignore_key(e) not in
               {_gitignore_key(ln) for ln in written.splitlines()}]
    assert not missing, (
        f"`upgrade` left required entries out of the adopter's .gitignore: "
        f"{missing}. Every REQUIRED_GITIGNORE row added after an adopter's "
        "install is invisible to them unless upgrade delivers it.\n"
        f"stdout:\n{upgraded.stdout}\n.gitignore:\n{written}"
    )
    # ...and the operator must be TOLD, not silently written to.
    combined = upgraded.stdout + upgraded.stderr
    assert "gitignore" in combined.lower(), (
        "`upgrade` changed the adopter's .gitignore without saying so.\n"
        f"stdout:\n{upgraded.stdout}"
    )


def test_an_uncommitted_pack_draft_is_disclosed_not_silently_hidden(
    fresh_repo: Path,
) -> None:
    """The accepted cost must be DISCLOSED, never silent.

    `_tracked_conflicts` answers from `git ls-files`, so it already covers an
    adopter who COMMITTED packs -- driven, it prints the `git add -f` note for
    free. It is blind to the common mid-flight state: a draft written and not
    yet committed. Measured before this arm existed, that adopter got no
    message at all, the draft stopped staging on the next `git add -A`, and
    the entry responsible never appeared in the output (the append reports a
    count, not names).
    """
    subprocess.run(["git", "add", "-A"], cwd=fresh_repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=fresh_repo,
                   check=True, capture_output=True)
    (fresh_repo / "task-packs").mkdir()
    (fresh_repo / "task-packs" / "TP-9-draft.md").write_text("# wip\n", encoding="utf-8")

    result = _run_init(fresh_repo)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "task-packs/TP-9-draft.md" in combined, (
        "init hid the adopter's uncommitted pack without naming it. The "
        "operator accepted this cost as a DISCLOSED one; reachable in "
        f"silence it is a different decision.\nstdout:\n{result.stdout}"
    )


def test_the_disclosure_stays_silent_on_a_fresh_install(
    fresh_repo: Path,
) -> None:
    """It must not report the harness's OWN freshly-written files back.

    Calibration against the live corpus, not a guess: the first cut used the
    harness's write inventory incompletely and named five of its own
    artifacts (`integrity.json`, `repo_fingerprint.json`, ...) as "your
    uncommitted work" on a first install. An advisory that cries wolf on
    every install is one nobody reads (§C19).

    Deliberately NOT keyed on `surface_contract.is_local_only`: that answers
    "must this never ship?", which is True for an adopter's own pack, so it
    would suppress exactly the file the arm above exists to name.
    """
    subprocess.run(["git", "add", "-A"], cwd=fresh_repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=fresh_repo,
                   check=True, capture_output=True)

    result = _run_init(fresh_repo)
    assert result.returncode == 0, result.stderr
    # Assert on the PREDICATE, not on message prose: keying the negative on a
    # literal sentence means a reword turns this test permanently green
    # instead of red -- the only-negative trap this repo has already logged.
    leaked = cli._untracked_conflicts(fresh_repo, list(REQUIRED_GITIGNORE))
    assert not leaked, (
        "init would report its OWN generated files as the adopter's "
        f"uncommitted work on a fresh install: {leaked}"
    )
    noisy = [
        ln for ln in (result.stdout + result.stderr).splitlines()
        if "you have uncommitted" in ln
    ]
    assert not noisy, (
        "init printed an uncommitted-work note on a fresh install:\n  "
        + "\n  ".join(noisy)
    )


def test_upgrade_dry_run_never_touches_the_gitignore(fresh_repo: Path) -> None:
    """Dry-run is `upgrade`'s DEFAULT and its core contract.

    Nothing pinned this before, and the pull toward breaking it is real: the
    sibling `_print_claude_md_nudge` five lines above is deliberately NOT
    gated on `execute` and says so in a comment, so simplifying
    `write_gitignore=execute` to `write_gitignore=True` reads as consistency.
    Measured against that mutation, a documented preview silently rewrote the
    adopter's .gitignore.
    """
    result = _run_init(fresh_repo, "--no-write-gitignore")
    assert result.returncode == 0, result.stderr
    assert not (fresh_repo / ".gitignore").exists()

    dry = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "upgrade", str(fresh_repo)],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )
    assert dry.returncode == 0, dry.stderr
    assert not (fresh_repo / ".gitignore").exists(), (
        "`upgrade` with no --execute WROTE the adopter's .gitignore. Dry-run "
        "is the documented default; a preview that mutates the tree is the "
        f"worst failure this command has.\nstdout:\n{dry.stdout}"
    )


# ── DEF-635: coverage is git's question, so git answers it ──────────────────


def _status_for(tmp_path: Path, gitignore_text: str) -> cli.GitignoreStatus:
    """``gitignore_status`` on a bare tree carrying exactly this ``.gitignore``.

    No ``git init`` here on purpose: the coverage oracle must answer BEFORE the
    adopter's tree is a repository (``espalier init`` on a fresh directory is
    that moment), and ``_tracked_conflicts`` degrades to empty without one.
    """
    (tmp_path / ".gitignore").write_text(gitignore_text, encoding="utf-8")
    return cli.gitignore_status(tmp_path)


def test_a_broader_glob_covers_the_required_entry(tmp_path: Path) -> None:
    """GitHub's stock Python template ignores ``*.py[cod]`` and never spells
    ``*.pyc``. Before DEF-635 every adopter carrying it was told by ``doctor``
    that ``*.pyc`` was missing, forever, and ``init`` appended the redundant
    line on the strength of the false reading."""
    status = _status_for(tmp_path, "__pycache__/\n*.py[cod]\n")
    assert status.oracle == "git"
    assert "*.pyc" not in status.missing
    assert "__pycache__/" not in status.missing
    # The entries the template does NOT cover are still reported.
    assert ".espalier/" in status.missing
    assert "/reports/" in status.missing


def test_a_wildcard_line_covers_a_required_file(tmp_path: Path) -> None:
    """This repo's own ``cc/_working_summary*`` covers the required
    ``cc/_working_summary.md``; the spelling compare said it did not."""
    status = _status_for(tmp_path, "cc/_working_summary*\n")
    assert "cc/_working_summary.md" not in status.missing


def test_a_trailing_comment_is_pattern_text_so_the_line_covers_nothing(
    tmp_path: Path,
) -> None:
    """gitignore has no trailing comments: ``*.pyc  # note`` is a pattern
    matching files literally named that, so reading it as absent is what git
    does -- the self-host repo carried exactly this dead line until DEF-635
    (DEF-551 found it). The row that filed DEF-635 called this half a false
    positive; it is not, and this pins that the fix did not "correct" it."""
    status = _status_for(tmp_path, "*.pyc  # explicit\n")
    assert "*.pyc" in status.missing


def test_a_later_negation_reads_as_not_covered(tmp_path: Path) -> None:
    """Last match wins in git; a spelling compare that finds ``/reports/`` on
    line one cannot see line two take it back."""
    status = _status_for(tmp_path, "/reports/\n!reports/\n")
    assert "/reports/" in status.missing


def test_a_root_anchored_spelling_does_not_cover_an_any_depth_entry(
    tmp_path: Path,
) -> None:
    """``/__pycache__/`` ignores only the root directory. The requirement is
    bytecode ANYWHERE -- the hooks compile under ``tools/cc/hooks/__pycache__``
    -- so ``src/pkg/__pycache__/`` would still be committed."""
    status = _status_for(tmp_path, "/__pycache__/\n/*.pyc\n")
    assert "__pycache__/" in status.missing
    assert "*.pyc" in status.missing


def test_the_contents_form_with_a_negated_child_still_covers(
    tmp_path: Path,
) -> None:
    """``task-packs/*`` plus ``!task-packs/CLAUDE.md`` was this repo's own
    shape until 2026-09-21 (it now re-includes the ledger and the active packs the
    same way); the contents form keeps the directory's contents out of git, which
    IS the requirement, and the re-included router is not the harness's
    state."""
    status = _status_for(tmp_path, "task-packs/*\n!task-packs/CLAUDE.md\n")
    assert cli.REINCLUDED_UNDER not in status.missing


def test_the_bare_pre_anchoring_spelling_still_covers(tmp_path: Path) -> None:
    """A tree initialized before DEF-429 carries ``reports/``; git agrees with
    ``_gitignore_key`` that it satisfies ``/reports/`` (and more besides), so
    the ``unanchored`` advisory still fires and nothing is re-appended."""
    status = _status_for(tmp_path, "reports/\n")
    assert "/reports/" not in status.missing
    assert "/reports/" in status.unanchored


def test_every_required_entry_covers_its_own_probes(tmp_path: Path) -> None:
    """Each entry written ALONE reads as covered, and covers nothing else.

    The shape-coverage guard for ``_entry_probe_paths``: probes are derived
    from the entry's shape, so an entry of a shape the derivation does not
    model (a ``?``, a character class, ``**``) reds here instead of silently
    reading as missing on every adopter tree. The second half pins that the
    probe set tells entries apart -- a required entry broad enough to cover
    another is a redundancy in ``REQUIRED_GITIGNORE`` itself.
    """
    for entry in REQUIRED_GITIGNORE:
        status = _status_for(tmp_path, entry + "\n")
        assert status.oracle == "git"
        assert entry not in status.missing, (
            f"{entry!r} written alone does not cover its own derived probes "
            f"{cli._entry_probe_paths(entry)}"
        )
        also_covered = [
            other for other in REQUIRED_GITIGNORE
            if other != entry and other not in status.missing
        ]
        assert not also_covered, (entry, also_covered)


def test_the_oracle_is_blind_to_global_excludes_and_info_exclude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pattern in the operator's global excludes file or in the repo's
    ``.git/info/exclude`` protects only this machine; a collaborator's clone
    still commits the state. Both must read as NOT covering."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    info = tmp_path / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "exclude").write_text("*.pyc\n__pycache__/\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / "global-excludes").write_text(".espalier/\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        f"[core]\n\texcludesFile = {(home / 'global-excludes').as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    # Sanity: git, asked in the adopter's own repo, says all three ARE ignored
    # -- the answer that is right for this machine and wrong for the clone.
    # (`require_is_gitignored` consults info/exclude and the global excludes
    # on purpose; that is exactly the machine-local reading this test needs.)
    for rel in ("x.pyc", "__pycache__/x", ".espalier/x"):
        assert require_is_gitignored(tmp_path, rel), rel
    status = _status_for(tmp_path, "")
    assert status.oracle == "git"
    for entry in ("*.pyc", "__pycache__/", ".espalier/"):
        assert entry in status.missing, entry


def test_the_oracle_ignores_an_inherited_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside a git hook git exports ``GIT_DIR``/``GIT_WORK_TREE``. Left in the
    environment, ``git init <scratch>`` re-inits the ADOPTER's repository and
    ``check-ignore`` consults its ``.git/info/exclude`` -- the per-machine
    file the hermetic check exists to keep out of the verdict."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    info = tmp_path / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "exclude").write_text("*.pyc\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    status = _status_for(tmp_path, "")
    assert status.oracle == "git"
    assert "*.pyc" in status.missing


def test_a_missing_gitignore_reads_as_nothing_covered(tmp_path: Path) -> None:
    status = cli.gitignore_status(tmp_path)
    assert not status.exists
    assert status.oracle == "git"
    assert set(status.missing) == set(REQUIRED_GITIGNORE)


def test_git_unavailable_falls_back_to_the_spelling_compare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No git on PATH: the verdict degrades to line-exact and SAYS so through
    ``oracle``, so ``doctor`` can qualify it. The compare still sees a spelled
    entry and still misses a broader one -- the pre-DEF-635 behaviour, now
    labelled."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.delenv("GIT_EXEC_PATH", raising=False)
    import shutil
    assert shutil.which("git") is None, "the fallback needs git absent"
    status = _status_for(tmp_path, "*.py[cod]\n__pycache__/\n")
    assert status.oracle == "line-exact"
    assert "__pycache__/" not in status.missing
    assert "*.pyc" in status.missing


# ── DEF-635, the failure-mode pass's findings, each pinned ───────────────────


def test_a_glob_on_the_product_name_gets_gits_answer_not_the_tokens(
    tmp_path: Path,
) -> None:
    """An adopter of a tool named espalier plausibly ignores ``*espalier*``.
    The first probe token carried that word, and under this one line eight
    of twelve required entries read as covered -- the DEF-635 defect
    inverted, into the direction where state gets committed. The token is
    synthetic now, so git's real answer comes through: the two entries this
    line genuinely covers, and no other."""
    status = _status_for(tmp_path, "*espalier*\n*probe*\n")
    assert status.oracle == "git"
    assert ".espalier/" not in status.missing
    assert ".espalier-state/" not in status.missing
    for entry in ("/reports/", "cc/blueprints/", "__pycache__/", "*.pyc",
                  ".claude/*.new", ".claude/*.bak", ".claude/*.bak.*",
                  cli.REINCLUDED_UNDER):
        assert entry in status.missing, entry


def test_a_file_that_swallows_arbitrary_paths_makes_the_oracle_decline(
    tmp_path: Path,
) -> None:
    """``*`` (and ``zq*``) excludes the control probe too, so the probes'
    answers say nothing about coverage; the oracle declines and the labelled
    fallback stands in rather than every glob entry reading as covered."""
    for text in ("*\n", "zq*\n"):
        status = _status_for(tmp_path, text)
        assert status.oracle == "line-exact", text
        assert "/reports/" in status.missing, text


def test_the_fallback_is_disclosed_where_init_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """``doctor`` qualifying a spelling verdict is not enough: ``init`` is the
    path that APPENDS on it. With git absent, the redundant `*.pyc` lands
    beside `*.py[cod]` -- and the operator is told why."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    (tmp_path / ".gitignore").write_text("*.py[cod]\n", encoding="utf-8")
    still_missing = cli._handle_gitignore(tmp_path, write_gitignore=True)
    out = capsys.readouterr().out
    assert "matched by spelling" in out, out
    assert "*.pyc" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert not still_missing


def test_an_entry_negated_after_its_bare_spelling_is_missing_not_unanchored(
    tmp_path: Path,
) -> None:
    """``missing`` is git's and ``unanchored`` is the spelling's; they must
    stay disjoint, or init prints "Nothing was rewritten" and appends
    ``/reports/`` in one breath."""
    status = _status_for(tmp_path, "reports/\n!reports/\n")
    assert "/reports/" in status.missing
    assert "/reports/" not in status.unanchored
    assert not set(status.missing) & set(status.unanchored)


def test_case_folding_follows_the_adopters_repo_not_the_scratch_dir(
    tmp_path: Path,
) -> None:
    """``git init`` sets ``core.ignorecase`` off the filesystem it inits on --
    the scratch directory's, not the adopter's. Pinned both ways through the
    adopter repo's own config so the test is portable: on a Mac the scratch
    default is case-insensitive, and without the fix ``REPORTS/`` read as
    covering ``/reports/`` for a repo whose volume is case-sensitive."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    text = "REPORTS/\n.ESPALIER/\n*.PYC\n"
    subprocess.run(["git", "config", "core.ignorecase", "false"],
                   cwd=tmp_path, check=True)
    strict = _status_for(tmp_path, text)
    subprocess.run(["git", "config", "core.ignorecase", "true"],
                   cwd=tmp_path, check=True)
    folded = _status_for(tmp_path, text)
    assert strict.oracle == folded.oracle == "git"
    for entry in ("/reports/", ".espalier/", "*.pyc"):
        assert entry in strict.missing, entry
        assert entry not in folded.missing, entry


def test_the_verdict_must_name_its_oracle() -> None:
    """No default: a fixture copied from a test that omits ``oracle`` would
    silently claim git answered."""
    with pytest.raises(TypeError):
        cli.GitignoreStatus(  # type: ignore[call-arg]
            exists=True, missing=(), unanchored=(), withheld={}, shared={},
        )


# ---------------------------------------------------------------------------
# The forward ledger is tracked: `/task-packs/*` with three re-includes
# ---------------------------------------------------------------------------


class TestTaskPacksIgnoreMigration:
    """A tree initialised with the directory form ``/task-packs/`` -- every
    adopter before 2026-09-30 -- cannot track the forward ledger: git cannot
    re-include a child of an excluded directory. And nothing asked it to: the
    required-state check reads the old line as satisfying ``/task-packs/*``
    (one ``_gitignore_key``, and git agrees the folder is covered). So a
    re-init rewrites the harness block's OWN line, re-asks git, and names --
    never edits -- a rule of the operator's own."""

    @staticmethod
    def _old_block(*, footer: bool = True, eol: str = "\n") -> str:
        entries = [("/task-packs/" if e == cli.REINCLUDED_UNDER else e)
                   for e in REQUIRED_GITIGNORE]
        lines = [cli.GITIGNORE_BLOCK_HEADER, *entries]
        if footer:
            lines.append(cli.GITIGNORE_BLOCK_FOOTER)
        return "node_modules/" + eol + eol + eol.join(lines) + eol

    @staticmethod
    def _ignored(repo: Path, rel: str) -> bool:
        return require_is_gitignored(repo, rel)

    def test_the_old_block_blocks_all_three_and_still_reads_covered(self, tmp_path: Path) -> None:
        status = _status_for(tmp_path, self._old_block())
        assert status.reincludes_blocked == cli.GITIGNORE_REINCLUDES
        assert cli.REINCLUDED_UNDER not in status.missing
        assert not status.ok

    def test_the_rendered_block_blocks_nothing(self, tmp_path: Path) -> None:
        text = "\n".join(cli.render_gitignore_entries(REQUIRED_GITIGNORE)) + "\n"
        assert _status_for(tmp_path, text).reincludes_blocked == ()

    def test_a_file_with_no_task_packs_rule_blocks_nothing(self, tmp_path: Path) -> None:
        status = _status_for(tmp_path, "node_modules/\n")
        assert status.reincludes_blocked == ()
        assert cli.REINCLUDED_UNDER in status.missing

    def test_a_reinit_rewrites_the_blocks_own_line(self, fresh_repo: Path, capsys) -> None:
        """Pass criterion 3, driven through real git: after the re-init the
        ledger is not ignored and a pack draft still is."""
        (fresh_repo / ".gitignore").write_text(self._old_block(), encoding="utf-8")
        assert self._ignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        lines = (fresh_repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert "/task-packs/" not in lines
        at = lines.index(cli.REINCLUDED_UNDER)
        assert tuple(lines[at + 1:at + 4]) == cli.GITIGNORE_REINCLUDES
        assert "Rewrote /task-packs/ as /task-packs/*" in capsys.readouterr().out
        for rel in cli.REINCLUDED_PATHS:
            assert not self._ignored(fresh_repo, rel), rel
        assert not self._ignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")   # independent of the constant
        assert self._ignored(fresh_repo, "task-packs/TP-1-a-draft.md")
        assert cli.gitignore_status(fresh_repo).ok

    def test_a_crlf_file_stays_crlf(self, fresh_repo: Path) -> None:
        (fresh_repo / ".gitignore").write_bytes(self._old_block(eol="\r\n").encode("utf-8"))
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        data = (fresh_repo / ".gitignore").read_bytes()
        assert b"\r\n/task-packs/*\r\n!/task-packs/CLAUDE.md\r\n" in data
        assert data.count(b"\n") == data.count(b"\r\n"), "a bare LF crept into a CRLF file"

    def test_a_block_written_before_the_footer_is_rewritten_too(self, fresh_repo: Path) -> None:
        (fresh_repo / ".gitignore").write_text(self._old_block(footer=False), encoding="utf-8")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        assert not self._ignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")

    def test_an_operators_own_line_is_named_never_edited(self, fresh_repo: Path, capsys) -> None:
        (fresh_repo / ".gitignore").write_text("# mine\n/task-packs/\n", encoding="utf-8")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        text = (fresh_repo / ".gitignore").read_text(encoding="utf-8")
        assert text.startswith("# mine\n/task-packs/\n"), "the operator's own line was edited"
        out = capsys.readouterr().out
        assert "outside the harness block" in out and "!/task-packs/FORWARD_LEDGER.md" in out
        assert self._ignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")
        assert cli.gitignore_status(fresh_repo).reincludes_blocked == cli.GITIGNORE_REINCLUDES

    def test_no_write_gitignore_edits_nothing_and_says_so(self, fresh_repo: Path, capsys) -> None:
        (fresh_repo / ".gitignore").write_text(self._old_block(), encoding="utf-8")
        before = (fresh_repo / ".gitignore").read_bytes()
        cli._handle_gitignore(fresh_repo, write_gitignore=False)
        assert (fresh_repo / ".gitignore").read_bytes() == before
        assert "so the forward ledger cannot be committed" in capsys.readouterr().out

    def test_a_tracked_router_is_not_reported_as_a_collision(self, fresh_repo: Path) -> None:
        """A tree that committed its router before the ledger shipped: the block
        re-includes that file, so ``/task-packs/*`` shares nothing with it."""
        (fresh_repo / "task-packs").mkdir()
        (fresh_repo / "task-packs" / "CLAUDE.md").write_text("router\n", encoding="utf-8")
        subprocess.run(["git", "add", "task-packs/CLAUDE.md"], cwd=fresh_repo, check=True)
        status = cli.gitignore_status(fresh_repo)
        assert cli.REINCLUDED_UNDER in status.missing
        assert cli.REINCLUDED_UNDER not in status.shared
        assert cli.REINCLUDED_UNDER not in status.withheld

    def test_the_migration_prints_no_false_unanchored_note(self, fresh_repo: Path, capsys) -> None:
        """``/task-packs/`` and ``/task-packs/*`` share a key, and every tree
        carrying the old anchored line was told it "matches at EVERY depth"
        beside "Rewrote" (failure-mode review, 2026-09-30)."""
        (fresh_repo / ".gitignore").write_text(self._old_block(), encoding="utf-8")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        assert "EVERY depth" not in capsys.readouterr().out

    def test_a_bom_file_is_rewritten_and_keeps_its_bom(self, fresh_repo: Path) -> None:
        """The header on the FIRST line, where a BOM sits in front of it: kept
        in the text, it hid the header and the rewrite was skipped."""
        text = "\n".join([cli.GITIGNORE_BLOCK_HEADER, "/task-packs/", cli.GITIGNORE_BLOCK_FOOTER, ""])
        (fresh_repo / ".gitignore").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        assert (fresh_repo / ".gitignore").read_bytes().startswith(b"\xef\xbb\xbf")
        assert not self._ignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")

    def test_a_crlf_file_ending_on_the_rule_stays_crlf(self, fresh_repo: Path) -> None:
        """The rule as the LAST line, no newline after it: the replaced line has
        no carriage return of its own, so the inserted lines take the file's ending."""
        text = "\r\n".join([cli.GITIGNORE_BLOCK_HEADER, ".espalier/", "/task-packs/"])
        (fresh_repo / ".gitignore").write_bytes(text.encode("utf-8"))
        assert cli._repair_task_packs_rule(fresh_repo / ".gitignore") == "rewrote"
        data = (fresh_repo / ".gitignore").read_bytes()
        body = data.rstrip(b"\r\n")
        assert body.count(b"\n") == body.count(b"\r\n"), "a bare LF crept into a CRLF file"
        assert data.endswith(b"!/task-packs/LEDGER_PROBES.json")

    def test_a_footer_block_with_a_blank_line_and_a_comment_is_still_rewritten(
        self, fresh_repo: Path
    ) -> None:
        text = "\n".join([cli.GITIGNORE_BLOCK_HEADER, ".espalier/", "", "# mine", "/task-packs/",
                          cli.GITIGNORE_BLOCK_FOOTER, ""])
        (fresh_repo / ".gitignore").write_text(text, encoding="utf-8")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        assert not self._ignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")

    def test_a_rule_edited_by_hand_inside_the_block_is_named_as_inside(
        self, fresh_repo: Path, capsys
    ) -> None:
        text = "\n".join([cli.GITIGNORE_BLOCK_HEADER, "task-packs/", cli.GITIGNORE_BLOCK_FOOTER, ""])
        (fresh_repo / ".gitignore").write_text(text, encoding="utf-8")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        out = capsys.readouterr().out
        assert "edited by hand (task-packs/)" in out and "outside the harness block" not in out
        assert "task-packs/\n" in (fresh_repo / ".gitignore").read_text(encoding="utf-8")

    def test_a_run_that_writes_nothing_says_a_writing_run_rewrites_it(
        self, fresh_repo: Path, capsys
    ) -> None:
        (fresh_repo / ".gitignore").write_text(self._old_block(), encoding="utf-8")
        cli._handle_gitignore(fresh_repo, write_gitignore=False)
        out = capsys.readouterr().out
        assert "upgrade --execute) repairs it to /task-packs/*" in out
        assert "outside the harness block" not in out


class TestLostReincludesAreRestored:
    """The block carries ``/task-packs/*`` but its ``!`` lines were deleted: the
    ledger is ignored, and init told the operator about a rule "outside the
    harness block" that did not exist -- and doctor's remedy (run init again)
    changed nothing (failure-mode review, driven 2026-09-30). The block is the
    installer's, so a re-init puts them back, the way a required entry deleted
    from it is re-appended."""

    @staticmethod
    def _stripped_block() -> str:
        return "\n".join([cli.GITIGNORE_BLOCK_HEADER, ".espalier/", cli.REINCLUDED_UNDER,
                          cli.GITIGNORE_REINCLUDES[0], cli.GITIGNORE_BLOCK_FOOTER, ""])

    def test_a_reinit_restores_them_under_the_rule(self, fresh_repo: Path, capsys) -> None:
        (fresh_repo / ".gitignore").write_text(self._stripped_block(), encoding="utf-8")
        assert require_is_gitignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")
        cli._handle_gitignore(fresh_repo, write_gitignore=True)
        out = capsys.readouterr().out
        assert "Restored the forward ledger's re-include lines" in out
        assert "outside the harness block" not in out
        assert not require_is_gitignored(fresh_repo, "task-packs/FORWARD_LEDGER.md")
        lines = (fresh_repo / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert lines.count("!/task-packs/FORWARD_LEDGER.md") == 1
        assert lines.index("!/task-packs/FORWARD_LEDGER.md") > lines.index(cli.REINCLUDED_UNDER)

    def test_a_run_that_writes_nothing_names_the_missing_lines(self, fresh_repo: Path, capsys) -> None:
        (fresh_repo / ".gitignore").write_text(self._stripped_block(), encoding="utf-8")
        before = (fresh_repo / ".gitignore").read_bytes()
        cli._handle_gitignore(fresh_repo, write_gitignore=False)
        out = capsys.readouterr().out
        assert "without all of its re-include lines" in out and "outside the harness block" not in out
        assert (fresh_repo / ".gitignore").read_bytes() == before


def test_the_deploy_inventory_calls_ignored_exactly_what_git_ignores(fresh_repo: Path) -> None:
    """README and QUICKSTART's inventory splits the seeds into "yours to edit"
    and "gitignored as local working state" through ``seed_is_ignored``; read
    without the re-includes, it put the tracked ledger in the second list the
    day it became tracked (failure-mode review, 2026-09-30). Held to git over
    the block ``init`` renders, seed by seed."""
    import importlib.util

    from espalier.managed_inventory import get_seed_docs

    spec = importlib.util.spec_from_file_location(
        "_gdr_truth", Path(__file__).resolve().parents[1] / "scripts" / "generate_doc_regions.py")
    gdr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gdr)
    (fresh_repo / ".gitignore").write_text(
        "\n".join(cli.render_gitignore_entries(REQUIRED_GITIGNORE)) + "\n", encoding="utf-8")
    wrong = [rel for rel in get_seed_docs()
             if gdr.seed_is_ignored(rel) != require_is_gitignored(fresh_repo, rel)]
    assert wrong == []
    assert gdr.seed_is_ignored("task-packs/FORWARD_LEDGER.md") is False   # independent side
