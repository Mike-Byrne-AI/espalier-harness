"""Espalier's own standards must not be applied to an adopter's content.

Three CLI verbs were measured acting on a foreign repo as if it were the
Espalier-Harness source tree. They are hidden from ``espalier --help`` (their
subparsers carry no ``help=``) but fully dispatchable, so a deployed doc naming
one is the only discovery route -- and five deployed command bodies invoke
one (seven name one, counting the agent body).

The sharpest was ``provenance``. ``.claude/commands/commit.md`` -- deployed to
every adopter -- instructs ``python -m espalier provenance .`` and then says
"Do NOT stage until it exits 0". ``PROVENANCE_RE`` matches ``\\bTP-\\d``, which
is Espalier's internal task-pack vocabulary AND a perfectly ordinary Jira
project prefix, and ``path_is_scanned`` returns True for an adopter's own
source. So an adopter whose code says ``# see ticket TP-4821`` was told by the
harness's own commit command not to stage, with a remedy -- "add an entry to
``_ALLOWED_HITS``" -- naming a private constant inside the installed engine
that they cannot edit and that would not survive an upgrade.

The fix is at the VERB, not at the five carriers that invoke it: standing down
with exit 0 makes every carrier safe at once, including ones nobody remembers
to guard. ``/preflight`` guards ``pre-release`` behind ``is_self_host_repo``
while ``/implement-pack`` runs the identical command unguarded -- which is
precisely why a per-carrier fix is the wrong unit.

``release-pack`` is deliberately the exception: it exits 2 rather than 0,
because a human only ever types it deliberately and a silent success that
produces no artifact is worse than a refusal.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from espalier._safe_walk import visible

from _adopter_tree import assert_is_adopter_tree

REPO_ROOT = Path(__file__).resolve().parent.parent

# The `adopter_tree` fixture is the SESSION-scoped one in conftest.py -- one
# `git init` + `cmd_init` for the whole run. Deliberately not a module-local
# copy: a second fixture would pay the init cost again and, worse, could drift
# from `_adopter_tree.assert_is_adopter_tree`'s definition of what makes a tree
# genuinely foreign.


def _run(tree: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """Drive the real CLI in the adopter tree, as an adopter would.

    Maintenance mode is stripped: it is an operator escape hatch for harness
    self-edits, and leaving it set would mask exactly the adopter-facing
    behaviour these tests exist to pin.
    """
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    return subprocess.run(
        [sys.executable, "-m", "espalier", *argv],
        cwd=tree, capture_output=True, text=True, env=env, timeout=300, encoding="utf-8",
    )


class TestProvenanceStandsDownOnAnAdopterTree:
    """The commit-path wedge: `/commit` says don't stage until this exits 0."""

    def test_an_ordinary_ticket_reference_does_not_block_the_adopter(
        self, adopter_tree: Path
    ):
        assert_is_adopter_tree(adopter_tree)
        # A wholly ordinary line in the adopter's OWN source. `TP-` is a
        # common Jira project prefix; it is only "provenance" to Espalier.
        #
        # The `git add` is load-bearing, not housekeeping: the census walks
        # `list_tracked_or_walked_files`, so an UNTRACKED probe file is never
        # scanned and this test passes without ever exercising the defect —
        # measured, not theorized. That is the git-ls-files false-green this
        # repo has logged before, and it lands just as easily inside the test
        # written to catch the bug as in the code under test.
        src = adopter_tree / "src" / "demo" / "ticket.py"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("# see ticket TP-4821 for context\nX = 1\n", encoding="utf-8")
        rel = src.relative_to(adopter_tree).as_posix()
        subprocess.run(["git", "add", rel], cwd=adopter_tree, check=True,
                       capture_output=True)
        tracked = subprocess.run(
            ["git", "ls-files", rel], cwd=adopter_tree,
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout.strip()
        assert tracked == rel, (
            "probe file is not tracked, so the census would skip it and this "
            "test would pass vacuously"
        )
        try:
            result = _run(adopter_tree, "provenance", ".")
        finally:
            # check=True, deliberately: `adopter_tree` is SESSION-scoped and
            # shared, and the other consumer walks the whole tree for marker
            # liveness. A cleanup that fails silently would leave a probe file
            # behind that can only ever FALSE-GREEN that neighbour, so a failed
            # cleanup must be loud here rather than a mystery there.
            subprocess.run(["git", "rm", "-f", "--quiet", rel], cwd=adopter_tree,
                           check=True, capture_output=True)
            src.unlink(missing_ok=True)

        assert result.returncode == 0, (
            "`espalier provenance` exited "
            f"{result.returncode} on an adopter repo whose only offence is an "
            "ordinary ticket reference in its own source. The deployed "
            "commit.md instructs this command and says 'Do NOT stage until it "
            "exits 0', so a non-zero exit here wedges the adopter's commit "
            f"path.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_the_stand_down_says_why_rather_than_claiming_clean(
        self, adopter_tree: Path
    ):
        result = _run(adopter_tree, "provenance", ".")
        combined = " ".join((result.stdout + " " + result.stderr).split())
        assert "Espalier-Harness source tree" in combined, (
            "the stand-down must name WHY it did nothing. Reporting a bare "
            f"'clean' would claim a check that never ran.\ngot: {combined}"
        )

    def test_it_does_not_report_a_clean_census_it_never_ran(
        self, adopter_tree: Path
    ):
        result = _run(adopter_tree, "provenance", ".")
        combined = " ".join((result.stdout + " " + result.stderr).split())
        assert "census: clean" not in combined.lower(), (
            "standing down must not borrow the vocabulary of a passing check — "
            f"that is a false all-clear.\ngot: {combined}"
        )


class TestPreReleaseStandsDownOnAnAdopterTree:
    """/preflight guards this call; /implement-pack runs it unguarded."""

    def test_it_does_not_grade_the_adopter_against_espaliers_release_rules(
        self, adopter_tree: Path
    ):
        assert_is_adopter_tree(adopter_tree)
        result = _run(
            adopter_tree, "pre-release", ".", "--skip-tests", "--skip-parity"
        )
        assert result.returncode == 0, (
            "`espalier pre-release` failed on an adopter repo — it was grading "
            "their tree against Espalier's OWN release requirements (LICENSE, "
            "CONTRIBUTING.md, ...). /implement-pack runs this command "
            f"unguarded.\nstdout: {result.stdout[:800]}"
        )
        combined = result.stdout + result.stderr
        assert "missing required file" not in combined, (
            "the adopter is still being told their repo is missing files that "
            f"only Espalier's own release needs.\n{combined[:800]}"
        )
        # The two arms below are the ones `provenance` already had and this
        # verb did not. Measured: replacing the skip payload with
        # `{"status": "pass", "failures": [], "checks": []}` -- a false
        # all-clear borrowing a passing gate's vocabulary -- left the whole
        # file GREEN. That mutation is not exotic: the obvious future edit is
        # to normalize this 2-key payload to the full report schema so
        # consumers stop KeyError-ing, and "pass" is the shape one reaches for.
        # /implement-pack calls this verb "the release gate ... the contract",
        # and its contract IS this JSON.
        assert '"skipped"' in result.stdout, (
            "the stand-down must report a status it earned. Claiming `pass` "
            "here would tell an adopter a release gate approved their repo "
            f"when it never ran.\nstdout: {result.stdout[:800]}"
        )
        assert "Espalier-Harness source tree" in result.stdout, (
            f"the skip must say why.\nstdout: {result.stdout[:800]}"
        )


class TestReleasePackRefusesOnAnAdopterTree:
    """Deliberately a REFUSAL, not a silent stand-down: a human typed it."""

    def test_it_does_not_bundle_the_adopters_source_into_an_espalier_zip(
        self, adopter_tree: Path
    ):
        assert_is_adopter_tree(adopter_tree)
        out = adopter_tree / "dist" / "espalier-harness.zip"
        if out.exists():
            out.unlink()
        result = _run(adopter_tree, "release-pack", ".")

        assert not out.exists(), (
            "`espalier release-pack` wrote an Espalier-branded archive "
            "containing the ADOPTER's own source into their tree."
        )
        # `== 2`, not `!= 0`: docs/CHEAT-SHEET.md ships the literal claim
        # "release-pack refuses at exit 2" to every adopter, and nothing else in
        # the suite pinned the value. Normalizing this to `return 1` ("a refusal
        # is not a usage error") is a plausible tidy that would leave the suite
        # green and the shipped doc false.
        assert result.returncode == 2, (
            "release-pack must REFUSE on an adopter tree at exit 2, not exit 0 "
            "having "
            "produced nothing — the user typed this verb deliberately and is "
            "owed an answer."
        )
        combined = " ".join((result.stdout + " " + result.stderr).split())
        assert "Espalier-Harness source tree" in combined, (
            f"the refusal must say why.\ngot: {combined}"
        )


class TestTheGateIsNotVacuousOnSelfHost:
    """Anti-vacuity floor (§C5).

    `is_self_host_repo` needs 5 signals including a content-hash pin on
    write_guard.py. If that pin ever goes stale, every gate above silently
    flips to "stand down" ON THIS REPO and the census stops running where it
    matters. These assert the self-host arm is live, so a false-negative
    oracle reds here instead of quietly disabling the checks.
    """

    def test_this_repo_is_still_recognized_as_self_host(self):
        from espalier import surface_contract

        assert surface_contract.is_self_host_repo(REPO_ROOT), (
            "is_self_host_repo() no longer recognizes this checkout, so every "
            "adopter stand-down above would now fire HERE — disabling the "
            "provenance census on the one tree it exists for. Refresh the pin "
            "with `espalier _refresh-self-host-pin .`."
        )

    def test_the_census_still_runs_here_rather_than_standing_down(self):
        """The stand-down must not be what makes `provenance` green at home."""
        import os

        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        result = subprocess.run(
            [sys.executable, "-m", "espalier", "provenance", "."],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env, timeout=300, encoding="utf-8",
        )
        combined = result.stdout + result.stderr
        assert "Espalier-Harness source tree" not in combined, (
            "`provenance` stood DOWN on the self-host repo — the census is no "
            f"longer running where it is the actual gate.\n{combined[:400]}"
        )
        assert result.returncode == 0, (
            f"self-host provenance census is failing: {combined[:800]}"
        )


class TestHarmfulVerbsAreDeclaredAgainstTheHiddenCanon:
    """Bind the gated set to the existing 12-name SoT rather than a new list.

    `tests/test_cli_commands.py::TestArgparseErrorCuration.HIDDEN` already
    enumerates every subcommand withheld from `--help`. Deriving from it means
    a NEW hidden verb forces a decision here instead of silently joining the
    ungated majority.
    """

    #: Hidden verbs measured to act on adopter content as if it were
    #: Espalier's own. Each is gated in `espalier/cli.py`.
    GATED = frozenset({"provenance", "pre-release", "release-pack"})

    #: Hidden verbs measured SAFE on an adopter tree, with the reason. Kept
    #: explicit so a reader sees the whole hidden set accounted for, not just
    #: the gated three. `blueprint`, `reflect-deep` and `worktree-plan` were
    #: here as ungated adopter verbs until 2026-09-12, when DEF-772 listed
    #: them in `--help`; a verb that is listed is not hidden, so they left.
    UNGATED_REASONS = {
        "self-host": "has a real REPO_MODE_INITIALIZED_CONSUMER branch",
        "verify-landing": "pack-shaped; task-packs/ is deployed",
        "surface-handoff": "reports on the adopter's own deployed surface",
        "scaffolding-bench": "adopter-applicable; its unbounded-write defect "
                             "is a separate mechanism (write hygiene, not a "
                             "self-host gate) — filed as DEF-567, not fixed here",
        "_refresh-self-host-pin": (
            "stands down with the scope clause when the pin carrier is absent; "
            "it must NOT consult `_off_self_host`, whose fifth signal is the "
            "write_guard pin this verb refreshes (a stale pin would lock the "
            "remedy out of the source tree) -- pinned below"
        ),
        "refresh-externals": "stands down already (no frontmatter to read)",
    }

    def test_every_hidden_verb_is_accounted_for(self):
        from test_cli_commands import TestArgparseErrorCuration

        hidden = set(TestArgparseErrorCuration.HIDDEN)
        accounted = self.GATED | set(self.UNGATED_REASONS)
        unaccounted = hidden - accounted
        assert not unaccounted, (
            f"hidden CLI verb(s) {sorted(unaccounted)} joined the withheld set "
            "without anyone deciding whether they act on ADOPTER content as if "
            "it were Espalier's own. Drive each on an adopter tree, then add it "
            "to GATED (with a gate in cli.py) or to UNGATED_REASONS (with the "
            "measured reason)."
        )
        stale = accounted - hidden
        assert not stale, (
            f"{sorted(stale)} is listed here but is no longer a hidden verb — "
            "re-derive against TestArgparseErrorCuration.HIDDEN."
        )

    def test_every_gated_verb_is_actually_gated_in_the_cli(self):
        """Floor that reads the CODE, not this file's own constant.

        The tautological spelling of this guard -- `assert len(self.GATED) >= 3`
        -- reads a frozenset declared 30 lines above it, so deleting
        `_off_self_host` from all three commands leaves it green while its
        message claims it would catch exactly that. That is the same
        shipped-in-a-guard tautology this repo caught one commit earlier; the
        message is the defect, so make the assertion true instead of softening
        the message.
        """
        import ast

        source = (REPO_ROOT / "espalier" / "cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        bodies = {
            node.name: ast.get_source_segment(source, node) or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        ungated = []
        for verb in sorted(self.GATED):
            func = "cmd_" + verb.replace("-", "_")
            body = bodies.get(func)
            if body is None or "off_self_host" not in body:
                ungated.append(f"{verb} -> {func}")
        assert not ungated, (
            "these verbs are declared GATED but their cli.py command does not "
            f"consult `off_self_host`: {ungated}. Either the gate was unwired "
            "or the declaration is stale."
        )

    def test_the_pin_refresh_verb_never_consults_the_predicate_its_pin_feeds(self):
        """`_refresh-self-host-pin` is the remedy for a stale write_guard pin,
        and `is_self_host_repo` -- what `_off_self_host` negates -- returns
        False on a stale pin (its fifth signal). Gate the remedy on the
        predicate and the source tree cannot refresh its own pin: written,
        driven and refuted at TP-456 4-C-2. The verb stands down on the pin
        carrier's absence instead, with the siblings' scope clause; this row
        reds if anyone routes it through the predicate again."""
        import ast

        source = (REPO_ROOT / "espalier" / "cli.py").read_text(encoding="utf-8")
        body = next(
            ast.get_source_segment(source, node) or ""
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "cmd_refresh_self_host_pin"
        )
        # The CALL, not the token: the verb's own comment names the predicate
        # to say why it is not consulted, and a source segment carries comments.
        assert "off_self_host(" not in body, (
            "cmd_refresh_self_host_pin consults off_self_host: on a stale pin "
            "that predicate reads adopter, and the verb that refreshes the pin "
            "would refuse on the source tree. Stand down on the carrier's absence."
        )
        assert "_SELF_HOST_SCOPE_CLAUSE" in body, (
            "the adopter-tree stand-down must name the reason with the shared "
            "scope clause, not print an internal path"
        )

    def test_hidden_ness_is_not_the_canon_for_this_class(self):
        """The class is "applies an Espalier-only standard to adopter content".

        Hidden-ness is neither necessary nor sufficient for membership, and
        keying on it hid a real member: `surface-impact` is a VISIBLE verb that
        runs `PROVENANCE_RE` and `surface_hygiene.self_host_vocab_hits` over an
        adopter's own files and exits 2, and `/implement-pack` step 0-D invokes
        it. The accounting above (over `HIDDEN`) could never have seen it.

        So pin the real canon: every module consulting the shared predicate is
        a member, and a new consumer must be declared here rather than joining
        silently.
        """
        consumers = set()
        for path in sorted((REPO_ROOT / "espalier").rglob("*.py")):
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            if rel.startswith("espalier/_vendor/"):
                continue  # verbatim mirror, governed by its source tree
            text = path.read_text(encoding="utf-8", errors="replace")
            if "off_self_host" in text and "def off_self_host" not in text:
                consumers.add(rel)

        declared = {"espalier/cli.py", "espalier/surface_impact.py"}
        assert consumers == declared, (
            "the set of modules standing down off the self-host tree changed.\n"
            f"  new (gate it, then add it here): {sorted(consumers - declared)}\n"
            f"  gone (drop it here):             {sorted(declared - consumers)}\n"
            "Membership is 'applies an Espalier-only standard to adopter "
            "content' — NOT 'is a hidden command'."
        )


class TestRefreshPinStandsDownOnAnAdopterTree:
    """`_refresh-self-host-pin` is a harness-developer verb: the pin it rewrites
    lives in the source tree only. Driven on an adopter tree it used to print
    `error: <tree>/espalier/_self_host_fingerprint.py not found` -- an internal
    path the adopter cannot act on -- while its three siblings name the reason.
    Behavioural, not a source read: the structural row above pins WHICH
    predicate the verb may not consult; this row pins what the adopter sees
    (a `return 0` or a raw path would pass that row and red here)."""

    def test_names_the_reason_at_exit_2_and_no_internal_path(self, adopter_tree):
        assert_is_adopter_tree(adopter_tree)
        result = _run(adopter_tree, "_refresh-self-host-pin", ".")
        # `== 2`, like release-pack: the verb did not do its job, and nothing
        # here is a commit-path wedge (the provenance verb's reason for 0).
        assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
        assert "applies only to the Espalier-Harness source tree" in result.stderr, result.stderr
        assert "_self_host_fingerprint.py" not in result.stderr + result.stdout, (
            "the stand-down leaked the internal pin path again"
        )


#: The body an adopter gets: the packaged copy `init` deploys, not the source
#: under `.claude/` (the mirror parity test holds the two equal).
_COMMIT_BODY = REPO_ROOT / "espalier" / "assets" / "claude" / "commands" / "commit.md"
_HANDOFF_BODY = REPO_ROOT / "espalier" / "assets" / "claude" / "commands" / "handoff.md"

#: A stage wider than a path list: every untracked file that is not ignored
#: rides along. The spellings are the ones git documents for "everything".
_BROAD_STAGE_RE = re.compile(
    r"^[ \t]*git[ \t]+add[ \t]+(?:[^\n]*[ \t])?(?:-A|--all|\.|\*|:/)[ \t]*$"
    # ...and the commit that stages for itself: `-a`, `--all`, or an `a` in a
    # short-flag cluster (`-am`), which is the idiom a tidy-up would write.
    r"|^[ \t]*git[ \t]+commit\b[^\n]*[ \t](?:--all\b|-[b-zA-Z]*a[a-zA-Z]*\b)",
    re.M,
)


def _fenced_bash_blocks(text: str) -> list[str]:
    """Every fenced shell block (bash, sh, shell, zsh), dedented. A fence
    inside a numbered list item is indented to the item's text
    (`/implement-pack` step 10), and a reader anchored at column zero walks
    straight past it."""
    blocks = []
    for m in re.finditer(r"^([ \t]*)```(?:bash|sh|shell|zsh)\n(.*?)^\1```", text,
                         flags=re.M | re.S):
        indent = m.group(1)
        blocks.append("".join(
            ln[len(indent):] if ln.startswith(indent) else ln
            for ln in m.group(2).splitlines(keepends=True)
        ))
    return blocks


#: Where the shipped bodies live: the packaged copies `init` deploys.
_SHIPPED_BODIES = REPO_ROOT / "espalier" / "assets" / "claude"

#: Every shipped body whose fenced lines commit, and the slice of it that
#: holds its staging fence (start marker, end marker). The census below reds
#: when a body grows a fenced commit line and is not listed here, so a new
#: committing body is driven by the real-git pin from the day it lands.
_COMMITTING_BODIES: dict[str, tuple[str, str]] = {
    "commands/commit.md": ("\n## Step 4", "\n## Step 5"),
    "commands/handoff.md": ("\n## 5.", "\n## 6."),
    "commands/implement-pack.md": ("\n10. **Commit.**", "\n11. "),
}

#: The head of a git command a body could spell: environment assignments
#: before it, `-C <dir>` / `-c <key=value>` between `git` and the verb.
_GIT_VERB_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*git(?:\s+-[Cc]\s+\S+)*\s+(?=(?:add|commit)\b)"
)


def _shell_commands(line: str) -> list[str]:
    """One shell line split on `&&`, `||` and `;` outside quotes and `<...>`
    placeholders, its trailing comment dropped: the original bug fits on one
    line as `git add -- X && git commit -m y`."""
    out: list[str] = []
    cur: list[str] = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            cur.append(ch)
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == "<" and ">" in line[i:]:
            end = line.index(">", i) + 1
            cur.append(line[i:end])
            i = end
            continue
        elif line.startswith(("&&", "||"), i):
            out.append("".join(cur))
            cur = []
            i += 2
            continue
        elif ch == ";":
            out.append("".join(cur))
            cur = []
        elif ch == "#" and (not cur or cur[-1].isspace()):
            break
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _staging_lines(text: str) -> list[str]:
    """Every `git add` and `git commit` in the fenced shell of ``text``, each
    with its backslash continuations joined, split out of a chained line and
    normalised to start `git add` / `git commit`."""
    lines = []
    for block in _fenced_bash_blocks(text):
        for ln in block.replace("\\\n", " ").splitlines():
            for cmd in _shell_commands(ln):
                m = _GIT_VERB_RE.match(cmd)
                if m:
                    lines.append("git " + cmd[m.end():])
    return lines


def _tokens(line: str) -> list[str]:
    """shlex tokens with each `<...>` placeholder kept whole (spaces inside it
    become NULs, which `_fill` turns back)."""
    import shlex

    masked = re.sub(r"<[^<>]*>", lambda m: m.group(0).replace(" ", "\0"), line)
    return shlex.split(masked, comments=True)


def _takes_more_than_its_paths(line: str) -> bool:
    """True for a commit that can take something its line does not name: no
    path list after `--` (except a message-only `--amend --only`), a flag that
    stages for itself (`-a`, `--all`, `-i`, `--include`, `-am`), or a path
    list that is the whole tree (`.`, `:/`, `*`)."""
    argv = _tokens(line)
    head, tail = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])
    if any(t in ("--all", "--include") or re.fullmatch(r"-[b-zA-Z]*[ai][a-zA-Z]*", t) for t in head):
        return True
    if any(t in (".", "./", ":/", ":", "*") for t in tail):
        return True
    return not tail and not ("--amend" in head and "--only" in head)


def _fill(line: str, *, paths: list[str], message_file: Path) -> list[str]:
    """A body's git line as an argv. A `<...>` placeholder after `--` stands
    for ``paths``; one in a `-m` value is message text; the one after `-F` is
    ``message_file``. Any other placeholder is a shape this driver cannot
    fill, and it fails loudly rather than guessing."""
    toks = _tokens(line)
    argv: list[str] = []
    after_dashdash = False
    for i, raw in enumerate(toks):
        tok = raw.replace("\0", " ")
        prev = toks[i - 1] if i else ""
        if after_dashdash and re.fullmatch(r"<[^<>]*>", tok):
            argv.extend(paths)
        elif "<" in tok and prev == "-m":
            argv.append(re.sub(r"<[^<>]*>", "x", tok))
        elif "<" in tok and prev == "-F":
            argv.append(str(message_file))
        elif "<" in tok:
            raise AssertionError(f"a placeholder the driver cannot fill: {tok!r} in {line!r}")
        else:
            after_dashdash = after_dashdash or tok == "--"
            argv.append(tok)
    return argv


def _git_in(repo: Path):
    def git(*argv: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", "-c", "core.editor=true",
             *argv],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False,
            input=stdin,
        )
    return git


def _write(path: Path, text: str) -> None:
    """LF bytes, so a blob read back through `git show` compares equal on
    every host (a text-mode write emits CRLF on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


class TestCommitStagesOnlyWhatWasReviewed:
    """The deployed `/commit` reviewed with `git diff`, which lists modified
    tracked files only, and then staged everything: the approval covered the
    message, never a path list. An adopter's first `/commit` on a dirty tree
    committed an owner's work in progress, a parallel session's files and the
    harness's own runtime state under a message approved for one change.

    The contract reads FENCED blocks only. The body's prose names the
    spellings it forbids, and a contract that read prose would red on the
    sentence that teaches the rule.
    """

    @pytest.mark.parametrize("line,broad", [
        ("git add -A", True),
        ("git add --all", True),
        ("git add .", True),
        ("git add -A .", True),
        ("git add *", True),
        ("git add :/", True),
        ("  git add -A", True),
        ("git add -- <approved paths>", False),
        ("git add -- src/app.py docs/guide.md", False),
        ("git add -N src/new_file.py", False),
        ("git add ./src/app.py", False),
        ("git add .gitignore", False),
        ('git commit -am "<approved message>"', True),
        ('git commit -a -m "<approved message>"', True),
        ('git commit --all -m "<approved message>"', True),
        ('git commit -m "<approved message>" -- <approved paths>', False),
        ('git commit -m "<approved message>"', False),
        ("git commit --amend", False),
    ])
    def test_the_detector_knows_a_broad_stage_from_a_path_list(self, line, broad):
        """Both verdicts, so the contract below cannot pass by matching nothing
        or red by matching a path that merely begins with a dot."""
        assert bool(_BROAD_STAGE_RE.search(line)) is broad, line

    def test_no_fenced_block_stages_broadly(self):
        blocks = _fenced_bash_blocks(_COMMIT_BODY.read_text(encoding="utf-8"))
        assert blocks, "the body has no fenced bash block: nothing was read"
        offenders = [m.group(0).strip() for b in blocks for m in _BROAD_STAGE_RE.finditer(b)]
        assert not offenders, (
            f"the deployed /commit stages wider than it reviewed: {offenders}"
        )

    def test_the_review_step_lists_untracked_files(self):
        text = _COMMIT_BODY.read_text(encoding="utf-8")
        step_one = text.split("## Step 2", 1)[0]
        blocks = "\n".join(_fenced_bash_blocks(step_one))
        assert re.search(r"git[ \t]+status\b[^\n]*(?:--untracked-files=all|-uall)", blocks), (
            "step 1 does not show untracked files, so the review cannot see "
            "what a path list must leave out"
        )

    @pytest.mark.parametrize("line,more", [
        ('git commit -m "<m>" -- <approved paths>', False),
        ("git commit -F <message file> -- <the paths the pack touched>", False),
        ("git commit --amend --only", False),
        ("git commit --amend --only -F <file>", False),
        ("git commit --amend --no-edit -- <the paths this step changed>", False),
        ('git commit -m "<m>"', True),
        ("git commit --amend", True),
        ("git commit --no-edit --amend", True),
        ("git commit --amend --no-edit -- .", True),
        ('git commit -m "<m>" -- :/', True),
        ('git commit -i -m "<m>" -- a.py', True),
        ('git commit -am "<m>" -- a.py', True),
        ("git commit --only", True),
    ])
    def test_the_census_rule_knows_a_narrow_commit_from_a_wide_one(self, line, more):
        assert _takes_more_than_its_paths(line) is more, line

    @pytest.mark.parametrize("text,expected", [
        ("```bash\ngit add -- a.py && git commit -m x\n```\n", ["git add -- a.py", "git commit -m x"]),
        ("```sh\nGIT_DIR=x git -C . commit -m x  # note\n```\n", ["git commit -m x"]),
        ('```bash\ngit commit -m "a; b" -- <p q>\n```\n', ['git commit -m "a; b" -- <p q>']),
        ("   ```bash\n   git commit -m x \\\n     -- a.py\n   ```\n", ["git commit -m x -- a.py"]),
    ])
    def test_the_census_reader_sees_chained_prefixed_and_indented_lines(self, text, expected):
        """Each shape was invisible to the first reader (driven by the
        failure-mode review): a chained line, an env-prefixed or `git -C`
        commit, an sh fence, an indented fence with a continuation."""
        assert [ln.split() for ln in _staging_lines(text)] == [e.split() for e in expected]

    @pytest.mark.parametrize("body", sorted(_COMMITTING_BODIES))
    def test_the_commit_fence_commits_exactly_the_approved_paths(self, body, tmp_path):
        """Driven: each committing body's own staging and commit lines, in
        order, on a tree holding the task's edit, its new file and the file it
        deleted, beside an owner's tracked edit, an owner's untracked file, a
        change the owner had ALREADY STAGED, an untrack the owner had staged
        (`git rm --cached`, the file kept on disk), and the plan tracker's
        state. The placeholder on each line's path list stands for the task's
        three paths, one of them with a space in its name; a path the body
        names literally (the handoff's ESPALIER_MEMORY.md) is the body's own
        write.

        `/commit` was the only body driven; `/handoff` step 5 staged its memory
        file by path and then ran a bare `git commit`, which took the owner's
        staged change into a memory commit nobody reviewed and step 8 pushed
        (reproduced 2026-10-01), and `/implement-pack` step 10 said "a plain
        `git commit`" in prose."""
        start, end = _COMMITTING_BODIES[body]
        text = (_SHIPPED_BODIES / body).read_text(encoding="utf-8")
        assert start in text and end in text.split(start, 1)[1], (body, start, end)
        section = text.split(start, 1)[1].split(end, 1)[0]
        fence = _staging_lines(section)
        assert [ln.split()[1] for ln in fence] == ["add", "commit"], (
            f"{body}: expected one staging line and then one commit line, found {fence}"
        )

        repo = tmp_path / "repo"
        repo.mkdir()
        message_file = tmp_path / "message.txt"
        _write(message_file, "change the task\n")
        task = ["src/task.py", "src/new.py", "src/old module.py"]
        add_argv, commit_argv = (_fill(ln, paths=task, message_file=message_file) for ln in fence)
        for argv in (add_argv, commit_argv):
            assert "--" in argv and argv[argv.index("--") + 1:], (
                f"{body}: takes no path list after `--`: {argv}"
            )
        named = add_argv[add_argv.index("--") + 1:]
        assert commit_argv[commit_argv.index("--") + 1:] == named, (
            f"{body}: the commit line names other paths than the add line staged"
        )

        git = _git_in(repo)
        assert git("init", "-q", "-b", "main").returncode == 0
        for rel, content in (("src/task.py", "x = 1\n"), ("src/old module.py", "gone = 1\n"),
                             ("owner.py", "y = 1\n"), ("owner_staged.py", "s = 1\n"),
                             ("keep.db", "k\n"), ("ESPALIER_MEMORY.md", "# memory\n")):
            _write(repo / rel, content)
        assert git("add", "--", ".").returncode == 0      # the scratch baseline only
        assert git("commit", "-q", "-m", "init").returncode == 0

        _write(repo / "src" / "task.py", "x = 2\n")                              # the task: edit
        _write(repo / "src" / "new.py", "n = 1\n")                               # the task: new
        (repo / "src" / "old module.py").unlink()                               # the task: delete
        _write(repo / "ESPALIER_MEMORY.md", "# memory\nrow\n")
        _write(repo / "owner.py", "y = 2\n")                                    # owner, tracked
        _write(repo / "scratch_test.py", "z = 1\n")                             # owner, untracked
        _write(repo / "owner_staged.py", "s = 2\n")
        assert git("add", "--", "owner_staged.py").returncode == 0              # owner, staged
        assert git("rm", "-q", "--cached", "--", "keep.db").returncode == 0     # owner, untrack staged
        _write(repo / "cc" / "execution_plan.json", "{}\n")

        for argv in (add_argv, commit_argv):
            assert argv[0] == "git", argv
            ran = git(*argv[1:])
            assert ran.returncode == 0, (body, argv, ran.stderr)

        committed = sorted(git("show", "--name-only", "--format=", "HEAD").stdout.strip().splitlines())
        assert committed == sorted(set(named)), (body, committed)
        assert git("diff", "--cached", "--name-only").stdout.split() == ["keep.db", "owner_staged.py"], (
            f"{body}: a change the owner had staged was committed, or was unstaged"
        )
        assert git("ls-files", "--", "keep.db").stdout == "", (
            f"{body}: the owner's staged untrack was undone (the file is tracked again)"
        )
        still_dirty = git("status", "--short", "--untracked-files=all").stdout
        theirs = ["owner.py", "scratch_test.py", "cc/execution_plan.json"]
        theirs += [] if "ESPALIER_MEMORY.md" in named else ["ESPALIER_MEMORY.md"]
        for path in theirs:
            assert path in still_dirty, (body, path, still_dirty)

    def test_every_shipped_body_that_commits_is_driven(self):
        """The census that keeps the pin above whole: every fenced commit line
        in every shipped body commits only what it names, and every body
        carrying one is in `_COMMITTING_BODIES`."""
        found: dict[str, list[str]] = {}
        for path in visible(_SHIPPED_BODIES.rglob("*.md"), _SHIPPED_BODIES):
            rel = path.relative_to(_SHIPPED_BODIES).as_posix()
            commits = [ln for ln in _staging_lines(path.read_text(encoding="utf-8"))
                       if ln.startswith("git commit ")]
            if commits:
                found[rel] = commits
        assert found, "no shipped body carries a fenced commit line: nothing was read"
        assert sorted(found) == sorted(_COMMITTING_BODIES), (
            "a shipped body commits in a fenced line the real-git pin does not drive "
            f"(or a listed body no longer commits): {sorted(found)}"
        )
        wide = [(rel, ln) for rel, lines in found.items() for ln in lines
                if _takes_more_than_its_paths(ln)]
        assert not wide, f"a fenced commit line that can take what it does not name: {wide}"

    def test_no_shipped_body_teaches_a_wide_commit_in_prose(self):
        """`/implement-pack` step 10 taught the bug in prose ("a plain
        `git commit`"), where no fence census looks. Every inline `git commit`
        span outside the fences commits only what it names, unless the
        sentence is forbidding it ("never `git commit -a`")."""
        span_re = re.compile(
            r"`((?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*git(?:\s+-[Cc]\s+\S+)*\s+commit\b[^`]*)`")
        seen, wide = 0, []
        for path in visible(_SHIPPED_BODIES.rglob("*.md"), _SHIPPED_BODIES):
            rel = path.relative_to(_SHIPPED_BODIES).as_posix()
            text = path.read_text(encoding="utf-8")
            prose = re.sub(r"^([ \t]*)```.*?^\1```", "", text, flags=re.M | re.S)
            for m in span_re.finditer(prose):
                seen += 1
                before = prose[max(0, m.start() - 80):m.start()].lower()
                if "never" in before:
                    continue
                line = "git " + m.group(1)[_GIT_VERB_RE.match(m.group(1)).end():]
                if _takes_more_than_its_paths(line):
                    wide.append((rel, m.group(1)))
        assert seen, "no shipped body names a commit in prose: nothing was read"
        assert not wide, f"prose that teaches a commit taking what it does not name: {wide}"

    def test_every_amend_a_body_teaches_leaves_a_staged_change_staged(self, tmp_path):
        """Driven: a bare `git commit --amend` takes the whole index into the
        commit, so after a by-path commit the change it left staged rides in on
        the fix-up (measured: a message-only bare amend swept it). Every amend
        a shipped body spells, prose included, is run on a tree where the
        owner's change is staged and a fix to the memory file is staged: the
        owner's change stays staged and out of HEAD, a path-limited amend
        lands the fix, a message-only one leaves it staged, and `-F` carries
        the new message."""
        spans = []
        for path in visible(_SHIPPED_BODIES.rglob("*.md"), _SHIPPED_BODIES):
            rel = path.relative_to(_SHIPPED_BODIES).as_posix()
            spans += [(rel, s) for s in re.findall(r"`(git commit --amend[^`]*)`",
                                                   path.read_text(encoding="utf-8"))]
        assert spans, "no shipped body teaches an amend: nothing was read"
        message_file = tmp_path / "message.txt"
        _write(message_file, "fixed message\n")
        for n, (rel, span) in enumerate(spans):
            repo = tmp_path / f"repo{n}"
            repo.mkdir()
            git = _git_in(repo)
            assert git("init", "-q", "-b", "main").returncode == 0
            _write(repo / "app.py", "a = 1\n")
            _write(repo / "ESPALIER_MEMORY.md", "# memory\n")
            assert git("add", "--", "app.py", "ESPALIER_MEMORY.md").returncode == 0
            assert git("commit", "-q", "-m", "init").returncode == 0
            _write(repo / "ESPALIER_MEMORY.md", "# memory\nrow\n")
            assert git("add", "--", "ESPALIER_MEMORY.md").returncode == 0
            assert git("commit", "-q", "-m", "docs(memory): row", "--", "ESPALIER_MEMORY.md").returncode == 0
            _write(repo / "app.py", "a = 2\n")
            assert git("add", "--", "app.py").returncode == 0                   # owner, staged
            _write(repo / "ESPALIER_MEMORY.md", "# memory\nrow, fixed\n")
            assert git("add", "--", "ESPALIER_MEMORY.md").returncode == 0       # the fix
            argv = _fill(span, paths=["ESPALIER_MEMORY.md"], message_file=message_file)
            ran = git(*argv[1:])
            assert ran.returncode == 0, (rel, span, ran.stderr)
            in_head = git("show", "--name-only", "--format=", "HEAD").stdout.split()
            assert "app.py" not in in_head, (rel, span, "the staged change rode into the amend")
            assert in_head == ["ESPALIER_MEMORY.md"], (rel, span, in_head)
            memory_in_head = git("show", "HEAD:ESPALIER_MEMORY.md").stdout
            staged = git("diff", "--cached", "--name-only").stdout.split()
            if "--" in argv:
                assert memory_in_head == "# memory\nrow, fixed\n", (rel, span, "the fix did not land")
                assert staged == ["app.py"], (rel, span, staged)
            else:
                assert memory_in_head == "# memory\nrow\n", (rel, span, memory_in_head)
                assert staged == ["ESPALIER_MEMORY.md", "app.py"], (rel, span, staged)
            subject = git("log", "-1", "--format=%s").stdout.strip()
            want = "fixed message" if "-F" in argv else "docs(memory): row"
            assert subject == want, (rel, span, subject)

    def test_handoff_no_longer_excuses_a_broad_stage_in_commit(self):
        """The handoff body forbade a broad stage for itself and excused
        `/commit` on the premise that its tree was just reviewed, which a
        tracked-only review did not satisfy. The two bodies state one rule."""
        text = _HANDOFF_BODY.read_text(encoding="utf-8")
        assert "does stage broadly" not in text
        assert "Stage by explicit path" in text
