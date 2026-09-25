"""CP-DISCARD's bare-`checkout <path>` arm + the pre-discard snapshot net.

Two defects, one incident. A real session ran `git checkout <path>` on a file
holding an uncommitted rewrite and destroyed it. `_DISCARD_RE` required
`checkout` to be followed by `--` or `.`, so the most-typed form passed
SILENTLY while `git checkout -- <same file>` fired. The omission was deliberate
(a blind arm false-fires on a branch switch whose name matches a directory) and
correct about the regex — but the ambiguity git itself resolves is resolvable
here, so the form did not have to stay uncovered.

The second half matters more. A speed-bump is deny-once-then-allow, so
re-issuing steps past it in one line; in the incident session the same guard was
re-issued past twice within minutes. A reminder is weak protection for content
with no reflog. `snapshot_discard` does not ask anyone to heed anything — it
turns an unrecoverable loss into a recoverable one.

"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _speedbump  # noqa: E402


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with one committed file, one branch, and one DIRTY file."""
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "file.py").write_text("committed\n", encoding="utf-8")
    (tmp_path / "clean.py").write_text("untouched\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    _git(tmp_path, "branch", "feature")
    # The uncommitted work the incident destroyed.
    (tmp_path / "file.py").write_text("UNCOMMITTED_REWRITE\n", encoding="utf-8")
    return tmp_path


class TestBareCheckoutArm:
    """`git checkout <path>` with no `--` — the form that was silent."""

    def test_fires_on_a_dirty_path(self, repo: Path):
        """The regression. This exact shape destroyed real work and said nothing."""
        assert _speedbump._pred_discard(
            "Bash", {"command": "git checkout file.py"}, repo
        )

    def test_silent_on_a_clean_path(self, repo: Path):
        """Against a clean path the checkout is a no-op, so firing would be noise.

        This is why the arm probes dirtiness rather than matching the shape:
        it makes the new arm STRICTLY more precise than the pre-existing
        `checkout .` arm, which fires even on a spotless tree.
        """
        assert not _speedbump._pred_discard(
            "Bash", {"command": "git checkout clean.py"}, repo
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            "git checkout feature",   # branch switch keeps working-tree changes
            "git checkout main",
            "git checkout -b brand-new",
        ],
    )
    def test_silent_on_branch_switches(self, repo: Path, cmd: str):
        """The false-fire the original omission was protecting against.

        A branch switch preserves working-tree changes, so it must stay silent
        even while `file.py` is dirty.
        """
        assert not _speedbump._pred_discard("Bash", {"command": cmd}, repo)

    def test_explicit_dash_dash_form_still_fires(self, repo: Path):
        """The pre-existing arm must keep working — this is additive."""
        assert _speedbump._pred_discard(
            "Bash", {"command": "git checkout -- file.py"}, repo
        )

    def test_silent_on_non_bash(self, repo: Path):
        assert not _speedbump._pred_discard(
            "Write", {"command": "git checkout file.py"}, repo
        )


class TestPowerShellToolDiscards:
    """DEF-747 (§C49): the discard snapshot was keyed on the Bash tool, so a
    discard typed on the PowerShell tool, or spelled behind `bash -c` there
    (the ordinary spelling where Git Bash is the git), destroyed uncommitted
    work with no stash -- every predicate opened with the Bash gate, and so
    did `snapshot_discard`. RED at HEAD by that gate: each firing row below
    returned False / None. The recovery half of the tool-keyed carve-out reads
    the PowerShell command's own scan text and every bash program it hands to
    `bash -c`; the friction checkpoints stay tool-keyed, pinned below."""

    @pytest.mark.parametrize("cmd", [
        "git reset --hard HEAD~3",                      # typed on the PowerShell tool
        "bash -c 'git reset --hard HEAD~3'",            # ... and behind Git Bash
        'sh -c "git checkout -- file.py"',
        "bash -c 'git stash drop'",
        "Get-Date; git restore file.py",                # a second statement
        "bash -c 'git checkout file.py'",               # the bare form behind bash (git probe arm)
    ])
    def test_the_predicate_fires_on_the_powershell_tool(self, repo: Path, cmd: str):
        assert _speedbump._pred_discard("PowerShell", {"command": cmd}, repo)

    def test_the_bare_checkout_typed_on_the_powershell_tool_is_snapshotted_not_bumped(self, repo: Path):
        """The bare `git checkout <path>` probe arm is Bash grammar; on the
        PowerShell tool's own text it stays silent, and the wider snapshot
        (which fires on any checkout) is the protection -- the recovery
        artifact, not the ceremony."""
        assert not _speedbump._pred_discard("PowerShell", {"command": "git checkout file.py"}, repo)
        assert _speedbump.snapshot_discard("PowerShell", {"command": "git checkout file.py"}, repo)

    @pytest.mark.parametrize("cmd", [
        "Write-Output 'bash -c \"git reset --hard\"'",     # a mention inside a literal
        'Write-Output "git reset --hard is destructive"',  # ... and inside an expandable span
        "bash -c 'echo git reset --hard'",                 # data inside the program
        "git status",
        "git checkout feature",                            # a branch switch
    ])
    def test_the_predicate_stays_silent_on_mentions(self, repo: Path, cmd: str):
        assert not _speedbump._pred_discard("PowerShell", {"command": cmd}, repo)

    def test_the_other_checkpoints_stay_tool_keyed(self, repo: Path):
        """The carve-out the module docstring records: only CP-DISCARD and its
        snapshot read the PowerShell tool; a force-push or a clean spelled
        there, bare or behind `bash -c`, is still not bumped."""
        for cmd in ("git push --force", "bash -c 'git push --force'"):
            assert not _speedbump._pred_forcepush("PowerShell", {"command": cmd}, repo)
        for cmd in ("git clean -fdx", "bash -c 'git clean -fdx'"):
            assert not _speedbump._pred_gitclean("PowerShell", {"command": cmd}, repo)

    @pytest.mark.parametrize("cmd", [
        "bash -c 'git checkout file.py'",
        "git reset --hard",
    ])
    def test_the_snapshot_covers_the_powershell_tool(self, repo: Path, cmd: str):
        original = (repo / "file.py").read_text(encoding="utf-8")
        sha = _speedbump.snapshot_discard("PowerShell", {"command": cmd}, repo)
        assert sha, "no snapshot taken for a dirty tree on the PowerShell tool"
        _git(repo, "checkout", "file.py")   # the destructive act
        assert _git(repo, "show", f"{sha}:file.py").stdout == original

    def test_the_snapshot_still_ignores_other_tools_and_other_commands(self, repo: Path):
        assert _speedbump.snapshot_discard("PowerShell", {"command": "Get-Date"}, repo) is None
        assert _speedbump.snapshot_discard("Write", {"command": "git reset --hard"}, repo) is None
        assert _speedbump.snapshot_discard(
            "PowerShell", {"command": 'Write-Output "git reset --hard"'}, repo) is None


class TestDiscardSnapshot:
    """The safety net: make the loss recoverable, not merely announced."""

    def test_snapshot_survives_the_destructive_command(self, repo: Path):
        """The whole point, end to end: destroy the file, then get it back."""
        original = (repo / "file.py").read_text(encoding="utf-8")
        sha = _speedbump.snapshot_discard(
            "Bash", {"command": "git checkout file.py"}, repo
        )
        assert sha, "no snapshot taken for a dirty tree"

        _git(repo, "checkout", "file.py")   # the destructive act
        assert (repo / "file.py").read_text(encoding="utf-8") != original

        recovered = _git(repo, "show", f"{sha}:file.py").stdout
        assert recovered == original, "snapshot did not round-trip the lost content"

    def test_snapshot_does_not_disturb_the_worktree_or_stash_list(self, repo: Path):
        """`git stash create` was chosen because it has no side effects.

        A snapshot that moved the worktree, or that pushed onto the operator's
        stash list, would be a new hazard rather than a net.
        """
        before = (repo / "file.py").read_text(encoding="utf-8")
        _speedbump.snapshot_discard("Bash", {"command": "git checkout file.py"}, repo)
        assert (repo / "file.py").read_text(encoding="utf-8") == before
        assert _git(repo, "stash", "list").stdout.strip() == ""

    def test_snapshot_logs_sha_and_command(self, repo: Path):
        sha = _speedbump.snapshot_discard(
            "Bash", {"command": "git checkout   file.py"}, repo
        )
        line = (repo / _speedbump.SNAPSHOT_LOG).read_text(encoding="utf-8").strip()
        assert sha in line
        # Whitespace-normalised so the log stays greppable.
        assert "git checkout file.py" in line

    def test_snapshot_is_a_noop_on_a_clean_tree(self, tmp_path: Path):
        """Nothing dirty means nothing to save — and no log noise."""
        _git(tmp_path, "init", "-q", ".")
        _git(tmp_path, "config", "user.email", "t@t")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-qm", "init")
        assert _speedbump.snapshot_discard(
            "Bash", {"command": "git checkout a.py"}, tmp_path
        ) is None
        assert not (tmp_path / _speedbump.SNAPSHOT_LOG).exists()

    @pytest.mark.parametrize(
        "cmd",
        [
            "git checkout file.py",
            "git checkout -- file.py",
            "git restore file.py",
            "git reset --hard",
            "git stash drop",
        ],
    )
    def test_snapshot_covers_every_discarding_verb(self, repo: Path, cmd: str):
        """Deliberately WIDER than the reminder's trigger.

        A snapshot is cheap and harmless, so it must not inherit the reminder's
        precision — including for forms the reminder has not learned.
        """
        assert _speedbump.snapshot_discard("Bash", {"command": cmd}, repo)

    def test_snapshot_ignores_unrelated_commands(self, repo: Path):
        assert _speedbump.snapshot_discard(
            "Bash", {"command": "git status"}, repo
        ) is None

    def test_snapshot_never_raises_outside_a_repo(self, tmp_path: Path):
        """A failed snapshot must never block the tool call it precedes."""
        assert _speedbump.snapshot_discard(
            "Bash", {"command": "git checkout x.py"}, tmp_path
        ) is None


class TestCpDiscardReadsTheStatementDirectory:
    """DEF-790: the bare `git checkout <pathspec>` probe asks git from the
    directory the statement runs in -- the payload cwd moved by the command's
    own cd chain, placed by the statement's offset -- so a dirty file named
    from a subdirectory draws the nudge it never drew when the pathspec was
    read against the root. A base OUTSIDE this checkout is skipped: the
    snapshot that backs the nudge's promise stashes this repo alone. Lives
    here, beside the snapshot, because it builds real repositories."""

    @staticmethod
    def _repo_with_dirty(root: Path, rel: str) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "x"], check=True)
        target.write_text("dirty\n", encoding="utf-8")

    def test_a_dirty_pathspec_named_from_its_own_directory_fires(self, tmp_path: Path):
        repo = tmp_path / "repo"
        self._repo_with_dirty(repo, "sub/file.txt")
        # read against the root, `file.txt` names nothing dirty; from `sub`, it does
        assert not _speedbump._pred_discard("Bash", {"command": "git checkout file.txt"}, repo)
        assert _speedbump._pred_discard(
            "Bash", {"command": "cd sub && git checkout file.txt"}, repo)
        assert _speedbump._pred_discard(
            "Bash", {"command": "git checkout file.txt"}, repo, repo / "sub")
        # a mention of the name in a statement elsewhere lends it no directory
        assert not _speedbump._pred_discard(
            "Bash", {"command": "cd sub && ls file.txt; cd ..; git checkout file.txt"}, repo)

    def test_another_checkouts_dirty_file_draws_no_nudge_here(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self._repo_with_dirty(tmp_path / "other", "file.txt")
        assert not _speedbump._pred_discard(
            "Bash", {"command": "cd ../other && git checkout file.txt"}, repo)


# ── DEF-802: the removal snapshot and the promise that names it ──────────────

DIRTY = "UNCOMMITTED_EDIT\n"

# The record `snapshot_discard` leaves for the bump is per process;
# `tests/conftest.py` resets it before every test in the suite, so a test
# here never inherits a promise another file's fire recorded.


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A checkout with a tracked directory holding one dirty file and one
    clean one, an untracked scratch directory, and a sibling checkout
    outside it -- every target class the removal arm must tell apart."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("committed\n", encoding="utf-8")
    (repo / "src" / "clean.py").write_text("untouched\n", encoding="utf-8")
    (repo / "lib").mkdir()
    (repo / "lib" / "mod.py").write_text("untouched\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    (repo / "src" / "app.py").write_text(DIRTY, encoding="utf-8")
    (repo / "scratch").mkdir()
    (repo / "scratch" / "notes.txt").write_text("never added\n", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", ".")
    (other / "file.txt").write_text("x\n", encoding="utf-8")
    # pre-register the stressor: the dirty line exists and git sees it
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == DIRTY
    assert _speedbump._git_rc(repo, "diff", "--quiet", "--", "src") == 1
    return repo


def _log_lines(repo: Path) -> list[str]:
    log = repo / _speedbump.SNAPSHOT_LOG
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


class TestRemovalSnapshot:
    """The walk-3 incident (leg 4-B): a recursive-force delete of a directory
    holding a dirty tracked line destroyed it unsnapshotted, and the later
    CP-DISCARD snapshot captured a tree that no longer had it. A delete whose
    target holds dirty tracked content inside this checkout is snapshotted
    first now, on both shells; a target that holds none, or that lies outside
    the checkout, takes no snapshot -- the net is `git stash create`'s, and
    the promise must be exactly as wide."""

    def test_a_delete_of_a_dirty_tracked_directory_is_snapshotted_and_recoverable(self, tree: Path):
        sha = _speedbump.snapshot_discard("Bash", {"command": "rm -rf src"}, tree)
        assert sha, "no snapshot for a dirty tracked directory"
        recovered = _git(tree, "show", f"{sha}:src/app.py").stdout
        assert recovered == DIRTY
        assert len(_log_lines(tree)) == 1 and sha in _log_lines(tree)[0]
        assert _speedbump._snapshot_taken_for("Bash", {"command": "rm -rf src"}, tree) == sha

    def test_a_plain_delete_of_a_dirty_file_is_the_same_loss(self, tree: Path):
        """Wider than CP-RMRF's trigger on purpose, as the discard arm is wider
        than CP-DISCARD's: a plain `rm` of a dirty file has no recovery either."""
        sha = _speedbump.snapshot_discard("Bash", {"command": "rm src/app.py"}, tree)
        assert sha and _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY

    @pytest.mark.parametrize("cmd", [
        "rm -rf scratch",            # untracked only: nothing stash create could hold
        "rm -rf lib",                # tracked and clean: a checkout restores it
        "rm src/clean.py",           # a clean file
        "rm -rf ../other",           # outside this checkout: not this repo's promise
        "rm -rf nonexistent",        # nothing there
        "rm -rf $DIR",               # an UNBOUND value: nothing to read
        "rm -rf ~/scratch",          # home, not the repo
        "echo rm -rf src",           # a mention -- the tokenizer masks it
        "ls src",                    # no delete verb at all
        "grep -ri src docs",         # `-ri` is a flag, not the alias (the gate's lookbehind)
    ])
    def test_targets_that_hold_no_dirty_tracked_content_take_none(self, tree: Path, cmd: str):
        assert _speedbump.snapshot_discard("Bash", {"command": cmd}, tree) is None
        assert _log_lines(tree) == []
        assert _speedbump._snapshot_taken_for("Bash", {"command": cmd}, tree) is None

    def test_the_targets_are_the_dirty_in_repo_ones_only(self, tree: Path):
        got = _speedbump._removal_snapshot_targets(
            "Bash", {"command": "rm -rf src scratch lib ../other"}, tree)
        assert got == [str(tree / "src")]

    @pytest.mark.parametrize("tool, cmd, expect", [
        # the deletes the glob relief now nudges keep their backup (the
        # review's item 10): a pattern is read as the directory it expands
        # in, a brace list as its expansions
        ("Bash", "rm -rf src/*", ["src"]),
        ("Bash", "rm -rf ./{src,lib}", ["src"]),
        ("Bash", "cd src && rm -rf *", ["src"]),
        ("PowerShell", "Remove-Item -Recurse src/*", ["src"]),
        # each element of a PowerShell array on its own, and a program the
        # PowerShell tool hands to bash read as the Bash arm reads it (the
        # lane's review)
        ("PowerShell", "Remove-Item -Recurse lib/*,src/*", ["src"]),
        ("PowerShell", "bash -c 'rm -rf src/*'", ["src"]),
        # a brace list is expanded up to `_SNAPSHOT_EXPANSION_CAP` results;
        # past it the operand is cut at the brace -- here onto the checkout
        # root, which earns no promise
        ("Bash", "rm -rf ./{" + ",".join([f"a{i}" for i in range(15)] + ["src"]) + "}", ["src"]),
        ("Bash", "rm -rf ./{" + ",".join([f"a{i}" for i in range(16)] + ["src"]) + "}", []),
        # a pattern at the checkout root may take the snapshot's own store
        # (`.git`): no promise, as for the root itself
        ("Bash", "rm -rf .*", []),
    ])
    def test_a_pattern_or_a_brace_list_is_read_as_what_it_takes(
        self, tree: Path, tool: str, cmd: str, expect: list,
    ):
        got = _speedbump._removal_snapshot_targets(tool, {"command": cmd}, tree)
        assert got == [str(tree / p) for p in expect], (cmd, got)

    def test_a_quoted_powershell_target_with_a_space_is_one_target(self, tree: Path):
        """The PowerShell arm split the remove's arguments on whitespace, so a
        quoted target holding a space named two paths and neither held the
        dirty file (the lane's review): the nudge fired with no promise."""
        spaced = tree / "my dir"
        spaced.mkdir()
        (spaced / "f.py").write_text("committed\n", encoding="utf-8")
        _git(tree, "add", "my dir")
        _git(tree, "commit", "-qm", "spaced")
        (spaced / "f.py").write_text(DIRTY, encoding="utf-8")
        got = _speedbump._removal_snapshot_targets(
            "PowerShell", {"command": 'Remove-Item -Recurse "my dir/*"'}, tree)
        assert got == [str(spaced)]

    def test_a_nudged_glob_delete_is_recoverable(self, tree: Path):
        sha = _speedbump.snapshot_discard("Bash", {"command": "rm -rf src/*"}, tree)
        assert sha and _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY

    @pytest.mark.parametrize("tool,cmd", [
        ("Bash", "DIR=src; rm -rf $DIR"),
        ("Bash", "F=src/app.py; rm $F"),
        # on the live hook the hard tier refuses the variable spelling before
        # the bump is reached; the arm still reads it, so its answer matches
        # the write leg's on the same text
        ("PowerShell", "$d='src'; Remove-Item -Recurse -Force $d"),
    ])
    def test_a_bound_variable_is_read_on_both_shells(self, tree: Path, tool: str, cmd: str):
        """The failure-mode review drove `DIR=src; rm -rf $DIR` to a CP-RMRF
        fire with no snapshot while `rm -rf src` took one: the arm now reads
        through the same pre-passes the write legs use."""
        sha = _speedbump.snapshot_discard(tool, {"command": cmd}, tree)
        assert sha and _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY

    def test_one_git_call_answers_for_every_candidate(self, tree: Path, monkeypatch):
        """The review measured one `git diff --quiet` per operand at 7.9 s for
        500 operands: the arm asks git once for the whole candidate list."""
        calls: list[list[str]] = []
        real_run = _speedbump.subprocess.run

        def counting_run(argv, *a, **k):
            if argv[:1] == ["git"]:
                calls.append(list(argv))
            return real_run(argv, *a, **k)
        monkeypatch.setattr(_speedbump.subprocess, "run", counting_run)
        operands = " ".join(f"a{i}" for i in range(500))
        got = _speedbump._removal_snapshot_targets(
            "Bash", {"command": f"rm -rf src {operands}"}, tree)
        assert got == [str(tree / "src")]
        assert len(calls) <= 2, [c[3:6] for c in calls]   # rev-parse, then ONE diff

    def test_candidates_past_the_cap_are_not_read(self, tree: Path):
        """The promise under-states past the cap -- the safe direction -- and
        the cap is the number the docstring names."""
        cap = _speedbump._REMOVAL_CANDIDATE_CAP
        operands = " ".join(f"a{i}" for i in range(cap))
        assert _speedbump._removal_snapshot_targets(
            "Bash", {"command": f"rm -rf {operands} src"}, tree) == []
        assert _speedbump._removal_snapshot_targets(
            "Bash", {"command": f"rm -rf src {operands}"}, tree) == [str(tree / "src")]

    def test_the_record_is_per_checkout(self, tree: Path, tmp_path: Path):
        """A snapshot recorded for this checkout lends no promise to a fire
        against another root with the same command text."""
        assert _speedbump.snapshot_discard("Bash", {"command": "rm -rf src"}, tree)
        assert _speedbump._snapshot_taken_for("Bash", {"command": "rm -rf src"}, tree)
        assert _speedbump._snapshot_taken_for("Bash", {"command": "rm -rf src"}, tmp_path / "elsewhere") is None

    @pytest.mark.parametrize("cmd,expect", [
        ("Remove-Item -Recurse -Force .\\src", True),
        ("Remove-Item -Recurse -Force src", True),
        ("Remove-Item src\\app.py", True),
        ("rm -r ./src", True),                          # the alias, as PowerShell reads it
        ("Remove-Item -Recurse -Force .\\scratch", False),
        ("Remove-Item -Recurse -Force .\\lib", False),
        ("Remove-Item -Recurse -Force $p", False),      # the hard tier's, never the bump's
        ("Write-Host 'Remove-Item -Recurse -Force src'", False),
        ('bash -c "rm -rf src"', True),                 # a bash program, read as bash receives it
        # DEF-842: a recursive remove without the force switch reaches the
        # nudge with an absolute target too (the force form walls it), so the
        # promise reads a plain absolute spelling inside the checkout
        ('Remove-Item -Recurse "{tree}/src"', True),
    ])
    def test_the_powershell_twin(self, tree: Path, cmd: str, expect: bool):
        cmd = cmd.replace("{tree}", str(tree))
        sha = _speedbump.snapshot_discard("PowerShell", {"command": cmd}, tree)
        assert (sha is not None) == expect, (cmd, sha)
        if sha:
            assert _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY

    def test_the_powershell_twin_reads_a_home_relative_target(self, tree: Path, monkeypatch):
        """DEF-842's review: the `~` branch of `_ps_absolute_parts` had no row
        (and on Windows it read the expansion's backslashes past the drive
        test). The home is pointed at the fixture's parent, so the target is
        this checkout's dirty directory spelled from the home."""
        monkeypatch.setenv("HOME", str(tree.parent))
        monkeypatch.setenv("USERPROFILE", str(tree.parent))
        cmd = f"Remove-Item -Recurse ~/{tree.name}/src"
        sha = _speedbump.snapshot_discard("PowerShell", {"command": cmd}, tree)
        assert sha is not None, cmd
        assert _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY

    def test_a_cd_chain_places_the_operand_in_its_own_statement(self, tree: Path):
        """DEF-790's rule, on this arm: the operand is read from the directory
        its statement runs in, by statement slice, so `cd src && rm app.py`
        names the dirty file and a bare `rm app.py` at the root names nothing."""
        assert _speedbump.snapshot_discard("Bash", {"command": "rm app.py"}, tree) is None
        assert _speedbump.snapshot_discard("Bash", {"command": "cd src && rm app.py"}, tree)
        assert _speedbump.snapshot_discard(
            "Bash", {"command": "rm app.py"}, tree, cwd=tree / "src")
        assert _speedbump.snapshot_discard(
            "PowerShell", {"command": "Set-Location src; Remove-Item app.py"}, tree)

    def test_a_nested_bash_program_is_read(self, tree: Path):
        assert _speedbump.snapshot_discard("Bash", {"command": 'bash -c "rm -rf src"'}, tree)

    def test_a_value_expanded_into_a_program_is_read(self, tree: Path):
        """DEF-848's lane (the failure-mode review): the program an interpreter
        receives carries a value the shell expanded into it before the
        interpreter started, so the nested-program list is read from every
        wall reading (`_bash_patterns._nested_shell_programs`) -- the nudge
        fired on this spelling and the snapshot did not."""
        assert _speedbump.snapshot_discard(
            "Bash", {"command": "v='rm -rf src'; python3 -c \"import os; os.system('$v')\""}, tree)

    def test_no_git_call_is_made_without_a_delete_verb(self, tree: Path, monkeypatch):
        """The gate: a command naming no delete verb costs no shell-out."""
        def _no_git(*a, **k):
            raise AssertionError(f"git was called for {a}")
        monkeypatch.setattr(_speedbump, "_git_rc", _no_git)
        assert _speedbump._removal_snapshot_targets("Bash", {"command": "echo hi; ls src"}, tree) == []
        assert _speedbump._removal_snapshot_targets(
            "PowerShell", {"command": "Get-ChildItem src"}, tree) == []

    def test_a_fault_in_the_arm_is_no_snapshot_and_no_wedge(self, tree: Path, monkeypatch):
        monkeypatch.setattr(_speedbump, "_removal_snapshot_targets",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert _speedbump.snapshot_discard("Bash", {"command": "rm -rf src"}, tree) is None

    def test_the_discard_arm_is_untouched(self, tree: Path):
        """The git-verb arm still snapshots on its own regex, before the
        removal arm is consulted."""
        assert _speedbump.snapshot_discard("Bash", {"command": "git reset --hard"}, tree)


class TestLoopRemovalSnapshot:
    """The loop carrier's removals are snapshotted as their direct twins are
    (DEF-837's lane, plan step 4). The body's remove takes the loop VARIABLE,
    which names nothing on disk, so the arm read `<root>/$f`, found nothing
    dirty under it, and took no snapshot -- the compensating control absent
    exactly where the loop drew only a nudge. The loop's ROOTS are what it
    removes: an enumerator's roots, or a word list's words, read by the loop
    reader and placed by the hard tier's own placement helper."""

    @pytest.mark.parametrize("cmd", [
        'for f in src; do rm -rf "$f"; done',                    # the word-list head
        'for f in lib src; do rm -rf "$f"; done',
        'for f in src/app.py; do rm "$f"; done',                 # a plain delete of a dirty file
        'find src | while read f; do rm "$f"; done',             # the enumerator heads
        'for f in $(find src); do rm -rf "$f"; done',
        'while read f; do rm -rf "$f"; done < <(find src)',
        'for f in src; do echo "$f" | xargs rm -rf; done',       # the carrier-fed body
        'cd src && for f in app.py; do rm "$f"; done',           # placed by the cd chain
    ])
    def test_a_loop_that_removes_a_dirty_tracked_root_is_snapshotted(self, tree: Path, cmd: str):
        sha = _speedbump.snapshot_discard("Bash", {"command": cmd}, tree)
        assert sha, f"no snapshot for {cmd!r}"
        assert _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY
        assert len(_log_lines(tree)) == 1 and sha in _log_lines(tree)[0]

    @pytest.mark.parametrize("cmd", [
        'for f in lib; do rm -rf "$f"; done',                    # tracked and clean
        'for f in scratch; do rm -rf "$f"; done',                # untracked only
        'for f in ../other; do rm -rf "$f"; done',               # outside this checkout
        'for f in src; do cat "$f"; done',                       # not a remove
        # a move keeps the content, as `mv` does -- with an unrelated remove
        # beside it so the delete-verb gate passes and the EFFECT filter is
        # what answers (the review: without it the row passed on the gate)
        'for f in src; do mv "$f" ../moved; done; rm -f nothing',
        'find src | while read f; do rm -rf build; done',        # a fixed operand, not the loop's roots
        "echo 'for f in src; do rm -rf \"$f\"; done'",           # a mention
        # the promise is exactly as wide as what the loop takes (the review's
        # regression): a narrowed head removes only what its predicate
        # selects, and an untracked-only listing takes no tracked content.
        # Rooted at `src`, which HOLDS the dirty file: rooted at `.`, these
        # rows passed on the store rule below while the narrowing filter was
        # mutated away (witnessed), so they gated nothing they were named for
        "find src -name '*.pyc' | while read f; do rm -rf \"$f\"; done",
        "for f in $(find src -name '*.pyc'); do rm -f \"$f\"; done",
        'git ls-files -o --exclude-standard src | while read f; do rm -f "$f"; done',
        'git ls-files -o --exclude-standard src | while read f; do rm -rf "$f"; done',
        # a delete that takes the snapshot's own store earns no promise: the
        # re-issue would destroy the net it names (loop and direct alike)
        'for f in .git src; do rm -rf "$f"; done',
        'rm -rf .git src',
        'for f in cc src; do rm -rf "$f"; done',
        'D=../repo; for f in $D; do rm -rf "$f"; done',
    ])
    def test_a_loop_whose_roots_hold_no_dirty_tracked_content_takes_none(self, tree: Path, cmd: str):
        assert _speedbump.snapshot_discard("Bash", {"command": cmd}, tree) is None
        assert _log_lines(tree) == []

    @pytest.mark.parametrize("cmd", [
        "find src | xargs rm -rf",
        "find src -print0 | xargs -0 rm -rf",
        "find src -delete",
        "find src -exec rm -rf {} +",
    ])
    def test_the_find_and_carrier_sweeps_are_a_declared_limit(self, tree: Path, cmd: str):
        """DECLARED, pinned exactly so the day they are read this reds on
        purpose (`DEF-845`): the same sweep the loop now snapshots, spelled
        as a find with a delete action or a pipeline into xargs, takes no
        snapshot -- `_removal_snapshot_targets` reads rm operands and a loop's
        whole roots only. The reach bit the loop reads (`_LoopRemoval.whole`)
        is not yet threaded through those two readers."""
        assert _speedbump.snapshot_discard("Bash", {"command": cmd}, tree) is None

    def test_placement_holds_past_the_scan_cap(self, tree: Path, tmp_path: Path):
        """The review drove a `cd` lost past the 32 KB cap: the loop's scan was
        uncapped while its placement chain capped, so EVERY loop fell back to
        the start directory. Capped as the wall's readers are now."""
        pad = "; echo " + "x" * 40000
        got = _speedbump._removal_snapshot_targets(
            "Bash", {"command": 'cd src && for f in app.py; do rm "$f"; done' + pad}, tree)
        assert got == [str(tree / "src" / "app.py")]
        got = _speedbump._removal_snapshot_targets(
            "Bash", {"command": 'cd ../other && for f in src; do rm -rf "$f"; done' + pad}, tree)
        assert got == []

    def test_a_loop_reader_fault_costs_the_direct_operands_nothing(self, tree: Path, monkeypatch):
        """The loop arm has its own fault boundary: before it did, a fault in
        the loop reader dropped the direct `rm -rf src` snapshot beside it."""
        import _bash_patterns

        def boom(*_a, **_k):
            raise RuntimeError("a loop reader fault")
        monkeypatch.setattr(_bash_patterns, "iter_placed_loop_removals", boom)
        sha = _speedbump.snapshot_discard(
            "Bash", {"command": 'rm -rf src; for f in a; do rm "$f"; done'}, tree)
        assert sha and _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY

    def test_the_loop_targets_are_the_dirty_in_repo_roots_only(self, tree: Path):
        got = _speedbump._removal_snapshot_targets(
            "Bash", {"command": 'for f in src scratch lib ../other; do rm -rf "$f"; done'}, tree)
        assert got == [str(tree / "src")]

    def test_the_hook_snapshots_before_the_loop_nudge_and_names_it(self, tree: Path):
        """The wiring, not only the arm (the DEF-498 lesson): write_guard takes
        the snapshot before the bump fires, so the loop's nudge names the net
        it cast and the log gains the line -- the plan step's own proof.
        Handed to the hook as a JSON payload; nothing is executed."""
        import json
        import os
        cmd = 'for f in src; do rm -rf "$f"; done'
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tree)}
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "write_guard.py")],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
            capture_output=True, text=True, timeout=30, env=env, encoding="utf-8",
        )
        assert "Speed-bump [CP-RMRF]" in result.stdout, (result.returncode, result.stdout, result.stderr)
        assert "snapshot just taken" in result.stdout, result.stdout
        lines = _log_lines(tree)
        assert len(lines) == 1 and cmd in lines[0], lines
        sha = lines[0].split("\t")[1]
        assert _git(tree, "show", f"{sha}:src/app.py").stdout == DIRTY


class TestConditionalPromise:
    """CP-RMRF names the snapshot only when one was taken for THIS command,
    and CP-DISCARD stops claiming one it did not take. The bump reads the
    record `snapshot_discard` leaves, exactly as write_guard sequences the
    two calls."""

    @staticmethod
    def _fire(tool: str, cmd: str, root: Path, cwd: Path | None = None) -> str:
        reason = _speedbump.check(tool, {"command": cmd}, root, cwd=cwd)
        assert reason is not None, (tool, cmd)
        return reason

    def test_rmrf_is_honest_when_nothing_was_snapshotted(self, tree: Path):
        reason = self._fire("Bash", "rm -rf scratch", tree)
        assert "CP-RMRF" in reason and "has no recovery;" in reason
        assert "snapshot" not in reason

    def test_rmrf_names_the_snapshot_it_took(self, tree: Path):
        sha = _speedbump.snapshot_discard("Bash", {"command": "rm -rf src"}, tree)
        assert sha
        reason = self._fire("Bash", "rm -rf src", tree)
        assert "CP-RMRF" in reason and "snapshot just taken" in reason
        assert _speedbump.SNAPSHOT_LOG in reason and "git show <sha>:<path>" in reason
        assert "has no recovery except" in reason

    def test_the_record_is_per_command(self, tree: Path):
        """A snapshot taken for one delete lends no promise to another."""
        assert _speedbump.snapshot_discard("Bash", {"command": "rm -rf src"}, tree)
        reason = self._fire("Bash", "rm -rf lib", tree)
        assert "snapshot" not in reason

    @pytest.mark.parametrize("tool,cmd", [
        ("Bash", "rm -rf src"), ("Bash", "rm -rf scratch"), ("Bash", "rm -rf lib"),
        ("Bash", 'bash -c "rm -rf src"'), ("Bash", "cd src && rm -rf ."),
        ("PowerShell", "Remove-Item -Recurse -Force .\\src"),
        ("PowerShell", "Remove-Item -Recurse -Force .\\scratch"),
        ("PowerShell", "Remove-Item -Recurse -Force .\\lib"),
    ])
    def test_the_promise_is_exactly_as_wide_as_the_snapshot(self, tree: Path, tool: str, cmd: str):
        """The coupling row: over every target class on both shells, the
        text says a snapshot exists iff `snapshot_discard` returned one."""
        sha = _speedbump.snapshot_discard(tool, {"command": cmd}, tree)
        reason = _speedbump.check(tool, {"command": cmd}, tree)
        if reason is None or "CP-RMRF" not in reason:
            pytest.skip(f"{cmd!r} draws no CP-RMRF nudge on this tool")
        assert ("snapshot just taken" in reason) == (sha is not None), (cmd, sha, reason)

    def test_the_nudge_at_the_hook_is_not_a_safety_verdict(self, tmp_path: Path):
        """DEF-837's lane, plan step 5, driven at the hook: a command that IS
        the repo in a spelling the guard cannot read draws the nudge, and the
        nudge's text says the hard tier blocks those targets only when it can
        read them. Spelled through a command substitution, a class the wall
        declares out of scope, so this row does not move when an open rm-tier
        row lands. Handed to the hook as JSON; nothing is executed."""
        import json
        import os
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "write_guard.py")],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": 'rm -rf "$(pwd)"'}}),
            capture_output=True, text=True, timeout=30, env=env, encoding="utf-8",
        )
        assert "Speed-bump [CP-RMRF]" in result.stdout, result.stdout
        assert "a spelling it cannot read" in result.stdout, result.stdout
        assert "if it can read them" in result.stdout, result.stdout

    def test_discard_no_longer_claims_a_snapshot_it_did_not_take(self, tmp_path: Path):
        """Outside a repo the discard bump still fires and git cannot answer:
        until 2026-09-15 the text said a snapshot was taken first."""
        assert _speedbump.snapshot_discard("Bash", {"command": "git reset --hard"}, tmp_path) is None
        reason = self._fire("Bash", "git reset --hard", tmp_path)
        assert "NO snapshot was taken" in reason and "snapshot was taken first" not in reason

    def test_discard_keeps_its_promise_when_it_took_one(self, tree: Path):
        assert _speedbump.snapshot_discard("Bash", {"command": "git reset --hard"}, tree)
        reason = self._fire("Bash", "git reset --hard", tree)
        assert "A snapshot was taken first" in reason and "NO snapshot" not in reason
