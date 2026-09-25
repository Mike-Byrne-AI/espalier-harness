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
import subprocess
import sys
from pathlib import Path

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
