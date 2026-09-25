"""Contract-lock tests for the pack-chain driver (`scripts/run_pack_chain.sh`).

The driver is a dev-only unattended backlog-drainer. These tests shell it with
``--dry-run`` (so no ``claude -p`` ever fires) and hermetic env seams
(``PACK_CHAIN_PACKDIR`` / ``PACK_CHAIN_LEDGER`` / ``PACK_CHAIN_SCOPE_PAUSE``)
pointed at ``tmp_path`` fixtures, then assert the hardened behaviors:

* an ambiguous pack token HALTS (never silently runs one file),
* a malformed/missing pack HALTS in preflight before any per-pack banner,
* the built goal no longer names ``/context-load`` (auto-loaded at SessionStart),
* the resume ledger skips an already-landed pack (``--fresh`` resets it),
* the scope gate HALTS on a major gap (un-scopeable pack or a ``[HIGH-RISK]``
  guarded surface) and PROCEEDS on a minor one,
* a run-report table is printed.

scope-check walks the real repo (``repo_root`` defaults to the cwd), so the
subprocess runs with ``cwd=REPO_ROOT``; the guarded-surface and minor-gap
fixtures rely on stable repo content (the ``Compaction`` matrix row; the
driver's own ``verify_install_green`` function name).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_pack_chain.sh"

# scripts/run_pack_chain.sh is a POSIX shell driver and is self-host tooling --
# it is absent from espalier/fusion_manifest.py's HARNESS_INCLUDE, so no adopter
# receives it. On Windows `bash` resolves to WSL (which has no distribution
# installed on the CI runner), so these would exercise the runner's shell rather
# than the driver. Skip rather than fail.
#
# This is module-scoped deliberately, and the scope is load-bearing: it also
# skips the two tests here that do NOT shell bash --
# test_scope_gate_grep_recognizes_the_real_no_symbols_message_not_an_error and
# test_sentinel_marker_is_a_token_the_status_banner_emits, which read the .sh as
# text and regex it. Both would pass on Windows; per-test decorators on the
# other 44 were rejected as unmaintainable. That forfeit is stated, not silent.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX shell driver; self-host tooling not shipped to adopters",
)


def _write_pack(
    packdir: Path,
    token: str,
    slug: str = "fixture",
    *,
    symbol: str | None = "Zznonexistentfixturesym42",
    scope_in: str = "scripts/run_pack_chain.sh",
    state: str = "DRAFT",
    landing: bool = True,
    landing_state: str | None = None,
) -> Path:
    """Write a minimal parse_pack-valid fixture pack.

    ``symbol=None`` omits the ``## Affected symbols`` section entirely so
    scope-check exits 1 (un-scopeable). The default nonsense ``symbol`` has zero
    references anywhere in the tree, so scope-check finds no gap and exits 0.

    ``landing=False`` omits the ``## Landing`` stanza entirely (an older pack that
    predates it) -- the top ``## Status`` ``State:`` line still satisfies the
    preflight shape check, so the pack is runnable but has no stanza to stamp.
    ``landing_state`` overrides the Landing stanza's ``State:`` value (defaults to
    ``state``) so a pack can be authored ``State: SCRAPPED`` in Landing while the
    Status block reads DRAFT.
    """
    affected = ""
    if symbol is not None:
        affected = (
            "## Affected symbols\n\n"
            "### Changed-semantics\n"
            f"- `{symbol}` — fixture symbol.\n\n"
        )
    landing_section = ""
    if landing:
        landing_section = "## Landing\n\n" f"- State: {landing_state or state}\n"
    body = (
        f"# {token} {slug}\n\n"
        "## Status\n\n"
        f"- State: {state}\n\n"
        "## Scope (in)\n\n"
        f"- `{scope_in}`\n\n"
        f"{affected}"
        f"{landing_section}"
    )
    path = packdir / f"{token}-{slug}.md"
    path.write_text(body, encoding="utf-8")
    return path


def _run_driver(
    tmp_path: Path,
    *args: str,
    packdir: Path | None = None,
    ledger: Path | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PACK_CHAIN_PACKDIR"] = str(packdir or tmp_path)
    env["PACK_CHAIN_LEDGER"] = str(ledger or (tmp_path / "ledger.txt"))
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True, encoding="utf-8",
    )


def _run_with_fake_claude(
    tmp_path: Path,
    claude_body: str,
    *,
    token: str = "TP-700",
    state: str = "DRAFT",
    landing: bool = True,
    landing_state: str | None = None,
    skip_sentinel: bool = True,
) -> tuple[subprocess.CompletedProcess, Path, Path]:
    """Seed a throwaway git repo + a fake ``claude`` that runs ``claude_body``, then
    drive one pack through it. Returns ``(CompletedProcess, repo, packdir)``.

    The install gate is skipped (no venv build); the fake ``claude`` inherits the
    driver's cwd (``repo``) so any ``cc/`` artifact it writes lands where the driver
    reads it. Used for the receipt-gate + driver-finalize earn-the-reds.

    ``skip_sentinel`` (default True) sets ``PACK_CHAIN_SKIP_DISPATCH_SENTINEL`` so the
    pre-first-pack dispatch sentinel is bypassed -- the ordinary fake bodies do not
    answer a ``/status`` probe, so they would otherwise trip it. The sentinel
    earn-the-reds pass ``skip_sentinel=False`` with a ``/status``-answering body.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "seed").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)

    packdir = tmp_path / "packs"
    packdir.mkdir()
    _write_pack(packdir, token, "cfg", symbol=None, state=state,
                landing=landing, landing_state=landing_state)  # no symbols -> scope skipped

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake = fakebin / "claude"
    fake.write_text("#!/bin/bash\n" + claude_body, encoding="utf-8")
    fake.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    env["PACK_CHAIN_PACKDIR"] = str(packdir)
    env["PACK_CHAIN_LEDGER"] = str(tmp_path / "ledger.txt")
    env["PACK_CHAIN_SKIP_INSTALL_GATE"] = "1"            # skip the venv build
    if skip_sentinel:
        env["PACK_CHAIN_SKIP_DISPATCH_SENTINEL"] = "1"   # bypass the pre-first-pack -p sentinel
    r = subprocess.run(
        ["bash", str(SCRIPT), token],
        cwd=str(repo), env=env, capture_output=True, text=True, encoding="utf-8",
    )
    return r, repo, packdir


# A fake claude that commits a token-less change and writes a clean pack receipt
# (both gates ran, zero blockers). Callers vary the receipt fields for RED cases.
def _fake_claude_body(receipt_json: str | None) -> str:
    body = 'git commit --allow-empty -qm "test: a change with no pack id"\n'
    if receipt_json is not None:
        body += "mkdir -p cc\n" + "cat > cc/_pack_receipt.json <<'JSON'\n" + receipt_json + "\nJSON\n"
    return body + "exit 0\n"


_CLEAN_RECEIPT = (
    '{"pack":"TP-700","suite":{"passed":4242,"skipped":7},'
    '"red_team":{"ran":true,"finding_count":0,"blocker_count":0,"finders":["correctness"]},'
    '"pack_review":{"ran":true,"blocks":0,"auto_fixed":[]},"changelog_touched":false}'
)


# A fake claude that BRANCHES on the dispatch-sentinel probe: on a `/status` prompt it
# echoes the /status banner token (dispatch_ok=True, a live headless-slash dispatch) or
# prose WITHOUT it (dispatch_ok=False, a prose-degraded dispatch); on any other prompt
# (the real pack goal) it runs the normal pack body (commit + receipt).
def _fake_claude_body_with_sentinel(receipt_json: str | None, *, dispatch_ok: bool) -> str:
    banner = "SURFACE: healthy" if dispatch_ok else "status: everything looks fine"
    return (
        'if [[ "$*" == *"/status"* ]]; then\n'
        f'  echo "{banner}"\n'
        '  exit 0\n'
        'fi\n'
    ) + _fake_claude_body(receipt_json)


def _scope_gate_harness(report: str, rc: int, tail: str) -> str:
    """A bash script that defines the driver's real ``scope_gate()`` with
    ``python3`` stubbed to return ``report``/``rc``, then runs ``tail``."""
    import re as _re
    script = SCRIPT.read_text(encoding="utf-8")
    m = _re.search(r"(?ms)^scope_gate\(\) \{.*?^\}", script)
    assert m, "could not extract scope_gate() from the driver"
    fn = m.group(0)
    return (
        "set -uo pipefail\n"
        "SCOPE_INJECT_CAP=12\n"
        'SCOPE_INJECT=""\n'
        "python3() {\n"
        "  cat <<'__SCOPE_REPORT__'\n"
        f"{report}\n"
        "__SCOPE_REPORT__\n"
        f"  return {rc}\n"
        "}\n"
        f"{fn}\n"
        f"{tail}\n"
    )


def _run_scope_gate(report: str, rc: int) -> str:
    """Extract ``scope_gate()`` from the driver and run it hermetically.

    Stubs ``python3`` so the internal ``python3 -m espalier scope-check`` returns
    ``report``/``rc`` with zero real-repo or real-CLI coupling, then echoes the
    resulting ``SCOPE_INJECT``. A faithful unit test of the rc==2 goal-fold that
    doesn't depend on volatile real-repo reference counts.
    """
    harness = _scope_gate_harness(
        report, rc,
        "scope_gate 'FAKE.md' >/dev/null 2>/dev/null\n"
        'printf "%s" "$SCOPE_INJECT"',
    )
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _scope_gate_streams(report: str, rc: int) -> tuple[str, str]:
    """The same hermetic ``scope_gate()``, returning what it PRINTED (stdout,
    stderr) rather than the fold: the rc==1 classification is a message, not a
    variable."""
    harness = _scope_gate_harness(report, rc, "scope_gate 'FAKE.md'")
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


# A scope-check report carrying BOTH a symbol gap and a literal (`Literal refs NOT
# classified (gap):`) block, each with a `memory/`-prefixed file. The symbol
# noise-filter must drop the symbol-block memory path; the 3-B literal fold must
# KEEP the literal-block memory path (a rename's real blast radius).
_MIXED_GAP_REPORT = (
    "TP-777 scope pre-flight\n"
    "========================================\n"
    "Pack: FAKE.md\n"
    "Scope (in) declares 1 files.\n"
    "Affected symbols section declares 1 symbols.\n"
    "\n"
    "Symbol reference scan:\n"
    "  somesym                                  -> 2 references\n"
    "\n"
    "Files NOT in pack scope (gap):\n"
    "  memory/should_be_filtered.md                     [!] 1 refs\n"
    "     L1: somesym mention\n"
    "  src/real_symbol_gap.py                           [!] 1 refs\n"
    "     L2: somesym mention\n"
    "\n"
    "Literal reference scan:\n"
    "  ESPALIER_MEMORY.md                                -> 2 refs  (0 target / 0 excluded / 2 ambiguous)\n"
    "\n"
    "Literal refs NOT classified (gap):\n"
    "  memory/should_reach_inject.md                    [!] 1 refs\n"
    "     L3: ESPALIER_MEMORY.md ref\n"
    "  ESPALIER_MEMORY.md                                        [!] 1 refs\n"
    "     L4: self ref\n"
    "\n"
    "Recommendation:\n"
    "  ...\n"
)


# A symbol-gap-only report whose gap block carries a BARE `ESPALIER_MEMORY.md`
# (the renamed committed-memory file, not a `memory/`-prefixed path). The symbol
# noise-filter must drop it like the other governed source, while a real source
# gap in the same block still folds into the goal. Guards the filter-token rename
# `MEMORY.md` -> `ESPALIER_MEMORY.md` (the dead token let the renamed file leak
# into the -p goal).
_BARE_MEMORY_SYMBOL_GAP_REPORT = (
    "TP-778 scope pre-flight\n"
    "========================================\n"
    "Pack: FAKE.md\n"
    "Scope (in) declares 1 files.\n"
    "Affected symbols section declares 1 symbols.\n"
    "\n"
    "Symbol reference scan:\n"
    "  somesym                                  -> 2 references\n"
    "\n"
    "Files NOT in pack scope (gap):\n"
    "  ESPALIER_MEMORY.md                               [!] 1 refs\n"
    "     L1: somesym mention\n"
    "  src/real_symbol_gap.py                           [!] 1 refs\n"
    "     L2: somesym mention\n"
    "\n"
    "Recommendation:\n"
    "  ...\n"
)


# A foreign pack's clean receipt (same shape, different `pack`) -- used to prove the
# re-gate receipt gate rejects an attestation left by an UNRELATED pack.
_FOREIGN_RECEIPT = _CLEAN_RECEIPT.replace('"pack":"TP-700"', '"pack":"TP-999"')


def _regate_two_run_fixture(tmp_path):
    """Shared setup for the post-commit-resume (re-gate) tests: a throwaway git repo + a
    fake ``claude`` that commits ONLY on its first invocation (a RAN sentinel, modelling a
    real session whose work is already committed on the re-invoke) + a ``TP-700`` pack,
    with a PERSISTENT ledger + committed-marker across runs. Returns
    ``(repo, packdir, ledger, marker, drive)`` where ``drive(**env)`` runs
    ``run_pack_chain.sh TP-700`` in the repo with the hermetic seams set."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "seed").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)

    packdir = tmp_path / "packs"
    packdir.mkdir()
    _write_pack(packdir, "TP-700", "cfg", symbol=None)

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake = fakebin / "claude"
    fake.write_text(
        "#!/bin/bash\n"
        "mkdir -p cc\n"
        "cat > cc/_pack_receipt.json <<'JSON'\n" + _CLEAN_RECEIPT + "\nJSON\n"
        'if [[ ! -f "$PWD/.fake_committed" ]]; then\n'
        '  touch "$PWD/.fake_committed"\n'
        '  git commit --allow-empty -qm "test: a change with no pack id"\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    ledger = tmp_path / "ledger.txt"
    marker = tmp_path / "committed.txt"

    def drive(**extra):
        e = dict(os.environ)
        e["PATH"] = f"{fakebin}:{e['PATH']}"
        e["PACK_CHAIN_PACKDIR"] = str(packdir)
        e["PACK_CHAIN_LEDGER"] = str(ledger)
        e["PACK_CHAIN_COMMITTED_MARKER"] = str(marker)
        e["PACK_CHAIN_SKIP_DISPATCH_SENTINEL"] = "1"
        e.update(extra)
        return subprocess.run(
            ["bash", str(SCRIPT), "TP-700"],
            cwd=str(repo), env=e, capture_output=True, text=True, encoding="utf-8",
        )

    return repo, packdir, ledger, marker, drive


class TestRunPackChain:
    """The hardened pack-chain driver's correctness + operability contracts."""

    def test_ambiguous_pack_token_halts_the_chain(self, tmp_path):
        # Two files match TP-777 — the pre-fix globber silently ran matches[0].
        _write_pack(tmp_path, "TP-777", "alpha")
        _write_pack(tmp_path, "TP-777", "beta")
        r = _run_driver(tmp_path, "--dry-run", "TP-777")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "ambiguous pack token" in r.stderr
        # never advanced to a per-pack run.
        assert "PACK: TP-777 " not in r.stdout

    def test_missing_pack_token_halts_in_preflight_before_spending(self, tmp_path):
        _write_pack(tmp_path, "TP-100", "good")
        # TP-NOPE resolves to nothing; the whole chain must fail BEFORE TP-100 runs.
        r = _run_driver(tmp_path, "--dry-run", "TP-100", "TP-NOPE")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "PACK: TP-100 " not in r.stdout
        assert "preflight FAILED" in r.stderr

    def test_goal_omits_context_load(self, tmp_path):
        # A clean pack (nonsense symbol -> no scope gap) proceeds to goal-building.
        _write_pack(tmp_path, "TP-100", "clean")
        r = _run_driver(tmp_path, "--dry-run", "TP-100")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "/context-load" not in r.stdout
        # the goal opener invokes the real command (relaxed off the old "Land ... via"
        # prose, which 305-A replaces with "Run the real slash command:").
        assert "/implement-pack" in r.stdout

    def test_goal_invokes_the_real_implement_pack_command(self, tmp_path):
        # The goal must RUN the real slash command so all of /implement-pack's steps
        # load, not paraphrase a 6-step subset. Assert against the EMITTED goal
        # (--dry-run): the source splits the old phrase across a `\`-newline line
        # continuation, so only the bash-collapsed emitted string is an honest oracle.
        _write_pack(tmp_path, "TP-100", "clean")
        r = _run_driver(tmp_path, "--dry-run", "TP-100")
        assert r.returncode == 0, r.stdout + r.stderr
        goal = r.stdout
        # (1) invokes the real command as the instruction to run
        assert "Run the real slash command: /implement-pack" in goal
        # (2) the old 6-step paraphrase opener is gone
        assert "apply the pack's edits" not in goal
        # (3) instructs the single pack receipt (producer side of the receipt gate)
        assert "cc/_pack_receipt.json" in goal
        # (4) carries the unattended 0-A fix-and-proceed policy
        assert "FIX mechanical findings" in goal

    def test_dry_run_prints_run_report_table(self, tmp_path):
        _write_pack(tmp_path, "TP-100", "clean")
        r = _run_driver(tmp_path, "--dry-run", "TP-100")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PACK-CHAIN RUN REPORT" in r.stdout
        # the pack shows as a DRY-RUN row.
        report = r.stdout.split("PACK-CHAIN RUN REPORT", 1)[1]
        assert "TP-100" in report and "DRY-RUN" in report

    def test_print_report_survives_empty_rows(self, tmp_path):
        # Regression: on bash 3.2 (macOS /bin/bash) `"${arr[@]}"` on an EMPTY array
        # under `set -u` raises "unbound variable" (fixed in bash 4.4+). REPORT_ROWS is
        # empty whenever the chain is interrupted before the first pack records an
        # outcome - e.g. the -p session is killed mid-run - and print_report fires from
        # the EXIT trap, so the report crashed on exactly the aborted runs that most
        # need a readout. Extract the REAL print_report and drive it with empty rows.
        # Platform ceiling: the RED is only earnable on bash <4.4; on a CI bash 5.x the
        # unfixed expansion is already safe, so this pins the invariant (the fix's red
        # was verified locally on bash 3.2.57).
        lines = SCRIPT.read_text(encoding="utf-8").splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.startswith("print_report() {"))
        end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
        fn = "\n".join(lines[start : end + 1])
        harness = tmp_path / "pr.sh"
        harness.write_text(
            fn + "\nCHAIN_STARTED=1\nREPORT_ROWS=()\nprint_report\n", encoding="utf-8"
        )
        r = subprocess.run(
            ["bash", "-c", f"set -uo pipefail; source {harness}"],
            capture_output=True,
            text=True, encoding="utf-8",
        )
        combined = r.stdout + r.stderr
        assert r.returncode == 0, combined
        assert "unbound variable" not in combined, combined
        assert "PACK-CHAIN RUN REPORT" in r.stdout
        assert "halted before any pack recorded an outcome" in r.stdout

    def test_no_budget_flag_runs_without_a_dollar_cap(self, tmp_path):
        # Default is NO cap so a long productive pack is never killed mid-way.
        # Regression guard: the driver used to default to a $10 --max-budget-usd cap.
        _write_pack(tmp_path, "TP-100", "clean")
        r = _run_driver(tmp_path, "--dry-run", "TP-100")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "--max-budget-usd" not in r.stdout
        assert "budget=no cap" in r.stdout

    def test_budget_flag_sets_an_opt_in_cap(self, tmp_path):
        _write_pack(tmp_path, "TP-100", "clean")
        r = _run_driver(tmp_path, "--dry-run", "--budget", "5", "TP-100")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "--max-budget-usd 5" in r.stdout

    def test_resume_ledger_skips_already_landed_pack(self, tmp_path):
        _write_pack(tmp_path, "TP-101", "clean")
        ledger = tmp_path / "ledger.txt"
        ledger.write_text("TP-101\n", encoding="utf-8")
        r = _run_driver(tmp_path, "--dry-run", "TP-101", ledger=ledger)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "already in resume ledger" in r.stdout
        assert "SKIPPED-resumed" in r.stdout
        # skipped BEFORE the per-pack banner (no budget spent).
        assert "PACK: TP-101 " not in r.stdout

    def test_fresh_flag_ignores_the_resume_ledger(self, tmp_path):
        _write_pack(tmp_path, "TP-101", "clean")
        ledger = tmp_path / "ledger.txt"
        ledger.write_text("TP-101\n", encoding="utf-8")
        r = _run_driver(tmp_path, "--fresh", "--dry-run", "TP-101", ledger=ledger)
        assert r.returncode == 0, r.stdout + r.stderr
        # --fresh cleared the ledger, so the pack is NOT skipped this time.
        assert "SKIPPED-resumed" not in r.stdout
        assert "PACK: TP-101 " in r.stdout

    def test_ledger_skip_precedes_resolution_so_a_moved_pack_resumes(self, tmp_path):
        # A landed pack is moved to task-packs/Done/, so it no longer resolves in the
        # pack dir. The ledger must skip it BEFORE resolution (preflight + loop), else
        # a resume re-invoke false-halts on the missing file. Regression guard.
        _write_pack(tmp_path, "TP-501", "present")           # exists
        ledger = tmp_path / "ledger.txt"
        ledger.write_text("TP-500\n", encoding="utf-8")                        # TP-500 "landed", NOT present
        r = _run_driver(tmp_path, "--dry-run", "TP-500", "TP-501", ledger=ledger)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "SKIPPED-resumed" in r.stdout                 # TP-500 skipped, not halted
        assert "no pack file for 'TP-500'" not in r.stderr
        assert "DRY-RUN" in r.stdout                          # TP-501 still ran

    def test_commit_verify_accepts_a_commit_without_the_pack_token(self, tmp_path):
        # The driver used to grep recent commit messages for the pack token, but this
        # repo FORBIDS pack IDs in commit messages -> it false-halted after every
        # correctly-messaged commit (the exact failure the first real run hit). It
        # must verify by HEAD advance instead. A fake `claude` that commits with a
        # token-less message (and writes a clean receipt so the receipt gate passes)
        # must be accepted as LANDED.
        r, _repo, _pd = _run_with_fake_claude(tmp_path, _fake_claude_body(_CLEAN_RECEIPT))
        assert "HALTED-nocommit" not in r.stdout, r.stdout + r.stderr
        assert "LANDED" in r.stdout, r.stdout + r.stderr
        assert r.returncode == 0, r.stdout + r.stderr

    def test_scope_gate_skips_pack_without_affected_symbols(self, tmp_path):
        # A config-only pack declares no symbols -> scope-check exit 1 -> the gate
        # is SKIPPED (advisory) and the pack PROCEEDS, matching /implement-pack's
        # own 0-B (which skips scope-check when a pack has no Affected symbols).
        # Regression guard: an earlier build false-HALTED the whole chain here.
        _write_pack(tmp_path, "TP-102", "noaffected", symbol=None)
        r = _run_driver(tmp_path, "--dry-run", "TP-102")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "skipping the scope gate" in r.stdout
        assert "DRY-RUN" in r.stdout          # proceeded to a run row

    def test_scope_gate_is_advisory_and_never_halts_on_a_guarded_surface(self, tmp_path):
        # `Compaction` is a GUARDED surface -> its symbol scan line is tagged
        # [HIGH-RISK] -> a scope gap. The gate is ADVISORY: it auto-accepts and
        # PROCEEDS rather than halting. (The [HIGH-RISK] tag false-fires on common
        # symbol names like `main`, so it is not a trustworthy automated halt.)
        # Regression guard: an earlier build HALTED the whole chain here.
        _write_pack(tmp_path, "TP-103", "guarded", symbol="Compaction")
        r = _run_driver(tmp_path, "--dry-run", "TP-103")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PACK: TP-103 " in r.stdout    # proceeded to the (dry-run) session
        assert "DRY-RUN" in r.stdout

    def test_scope_gate_minor_proceeds(self, tmp_path):
        # `verify_install_green` is a real driver function referenced in docs but
        # NOT a guarded surface; declaring only scripts/ in scope leaves the docs
        # refs as a gap -> exit 2, no [HIGH-RISK] -> MINOR -> proceed.
        _write_pack(tmp_path, "TP-104", "minor", symbol="verify_install_green")
        r = _run_driver(tmp_path, "--dry-run", "TP-104")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "auto-accepting gap" in r.stdout or "reference-noise only" in r.stdout
        # proceeded to a DRY-RUN row.
        assert "DRY-RUN" in r.stdout

    def test_scope_gate_folds_literal_gap_bypassing_the_symbol_noise_filter(self, tmp_path):
        """TP-318 3-B: a literal-keyed pack's ambiguous hits live in a SEPARATE
        `Literal refs NOT classified (gap):` block whose real targets legitimately
        sit in the very prefixes the symbol noise-filter drops (`memory/`,
        `ESPALIER_MEMORY.md`). The rc==2 fold must carry those literal hits into
        SCOPE_INJECT WITHOUT that filter, while a same-prefix SYMBOL gap stays
        filtered (no regression). Earn-the-red: pre-3-B scope_gate has no literal
        handling, so neither `memory/should_reach_inject.md` nor `ESPALIER_MEMORY.md`
        reaches the goal fold."""
        inject = _run_scope_gate(_MIXED_GAP_REPORT, rc=2)
        # 3-B: literal ambiguous hits in noise prefixes DO reach the goal fold.
        assert "memory/should_reach_inject.md" in inject, inject   # RED before 3-B
        assert "ESPALIER_MEMORY.md" in inject, inject                       # RED before 3-B
        # No regression: a SYMBOL gap in a noise prefix is still filtered out.
        assert "memory/should_be_filtered.md" not in inject, inject
        # And a non-noise symbol gap still folds (existing behavior intact).
        assert "src/real_symbol_gap.py" in inject, inject

    def test_symbol_noise_filter_drops_the_renamed_memory_file(self):
        """The symbol noise-filter must drop a BARE `ESPALIER_MEMORY.md` gap line
        (the renamed committed-memory file), not only the `memory/` prefix. Before
        the `MEMORY.md`->`ESPALIER_MEMORY.md` filter-token rename the dead token let
        the renamed file survive into the -p goal fold; a real source gap in the same
        block must still be kept. Earn-the-red: pre-rename, `ESPALIER_MEMORY.md`
        reached the inject."""
        inject = _run_scope_gate(_BARE_MEMORY_SYMBOL_GAP_REPORT, rc=2)
        assert "ESPALIER_MEMORY.md" not in inject, inject      # dropped by the noise-filter
        assert "src/real_symbol_gap.py" in inject, inject       # a real source gap still folds

    def test_driver_fold_matches_real_cli_literal_gap_output(self, tmp_path):
        """TP-318 drift-lock (twin of `test_scope_gate_grep_recognizes_...`):
        couple the driver's literal-gap fold to the REAL `cmd_scope_check` output
        shape. Run the actual CLI on a literals-only pack whose token has an
        ambiguous hit under a noise-prefix (`memory/`) path, feed its REAL stdout
        through the actual `scope_gate` fold, and assert the hit reaches
        SCOPE_INJECT. If the CLI's block header or `  <path>  [!] N refs` line
        shape drifts from what the driver's `sed`/`grep` expect, this reds — the
        CLI's own tests (which assert the literal string) cannot catch the
        driver-side break, and `_MIXED_GAP_REPORT` is hand-authored so it would
        stay green on a stale header. Also proves the noise-filter bypass on real
        output (a `memory/` literal hit is kept, not dropped)."""
        repo = tmp_path / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "a.py").write_text("keep = 1\n", encoding="utf-8")
        (repo / "memory").mkdir()
        (repo / "memory" / "note.md").write_text(
            "ZZ_UNIQUE_RENAME_TOKEN appears here\n", encoding="utf-8",
        )
        pack = tmp_path / "TP-99-litfold.md"
        pack.write_text(
            "# TP-99\n\n## Scope (in)\n\n- `src/a.py`\n\n## Scope (out)\n\nx\n\n"
            "## Affected literals\n\n- `ZZ_UNIQUE_RENAME_TOKEN` — a rename\n",
            encoding="utf-8",
        )
        real = subprocess.run(
            ["python3", "-m", "espalier", "scope-check", str(pack), "--repo", str(repo)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        )
        assert real.returncode == 2, real.stdout + real.stderr
        assert "Literal refs NOT classified (gap):" in real.stdout, real.stdout
        # Feed the REAL CLI stdout through the ACTUAL scope_gate fold.
        inject = _run_scope_gate(real.stdout, rc=2)
        assert "memory/note.md" in inject, (
            "driver fold did not carry the real CLI's literal-gap hit into "
            f"SCOPE_INJECT (header / line-shape drift?).\nCLI stdout:\n{real.stdout}\n"
            f"SCOPE_INJECT: {inject!r}"
        )

    def test_a_declared_but_empty_marker_at_exit_one_is_an_errored_probe_not_a_skip(self):
        """DEF-781: a pack that DECLARED an Affected section which parsed to
        zero entries had its blast radius skipped like a pack with nothing to
        walk, because every zero-parse message borrowed the no-section phrase
        the gate greps. The emitter now carries a marker on such a message and
        the gate reads the marker BEFORE the skip phrases."""
        report = (
            "This pack declares an 'Affected symbols' section, but it parsed to zero\n"
            "scope-check: DECLARED_BUT_EMPTY -- a declared section parsed to zero entries.\n"
            "entries: scope-check cannot walk references until the bullets match\n"
            "`path::symbol` under a `### Added` sub-heading.\n"
        )
        out, err = _scope_gate_streams(report, rc=1)
        assert "errored probe" in err, (out, err)
        assert "skipping the scope gate" not in out, out

    def test_the_genuine_no_section_message_at_exit_one_is_still_a_clean_skip(self):
        report = (
            "This pack has no 'Affected symbols' section and no 'Affected\n"
            "literals' section. scope-check cannot walk references until one\n"
            "is added. See docs/PACK_AUTHORING.md for the format.\n"
        )
        out, err = _scope_gate_streams(report, rc=1)
        assert "skipping the scope gate" in out, (out, err)
        assert "errored probe" not in err, err

    def test_the_drivers_marker_pattern_matches_what_the_real_cli_prints(self, tmp_path):
        """DEF-781's drift-lock, the shape of the phrase test below: lift the
        driver's ACTUAL marker pattern and pin it against the CLI's ACTUAL
        output on a real declared-but-empty pack, so the two literals cannot
        drift apart (a rename in cli.py reds this, not only tests/test_cli.py)."""
        import re
        script = (REPO_ROOT / "scripts" / "run_pack_chain.sh").read_text(encoding="utf-8")
        m = re.search(r"grep -qE '([^']+)' <<<\"\$report\"", script)
        assert m, "scope_gate's DECLARED_BUT_EMPTY marker grep was not found in the driver"
        marker = re.compile(m.group(1), re.MULTILINE)

        pack = tmp_path / "TP-106-declared-but-empty.md"
        pack.write_text(
            "# TP-106\n\n## Scope (in)\n\n- `scripts/run_pack_chain.sh`\n\n## Scope (out)\n\n"
            "nothing\n\n## Affected symbols\n\nTo be determined during execution.\n\n"
            "## Pass criteria\n\n1. x\n",
            encoding="utf-8",
        )
        declared = subprocess.run(
            ["python3", "-m", "espalier", "scope-check", str(pack)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        )
        assert declared.returncode == 1, declared.stdout + declared.stderr
        assert marker.search(declared.stdout), (
            "the driver's marker pattern does not match the real declared-but-empty "
            f"report: {declared.stdout!r}"
        )
        # The genuine no-section pack must NOT carry it: that one is a clean skip.
        nosym = _write_pack(tmp_path, "TP-107", "nosym", symbol=None)
        skip = subprocess.run(
            ["python3", "-m", "espalier", "scope-check", str(nosym)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        )
        assert skip.returncode == 1, skip.stdout + skip.stderr
        assert not marker.search(skip.stdout), skip.stdout

    def test_scope_gate_grep_recognizes_the_real_no_symbols_message_not_an_error(self, tmp_path):
        # TP-312 E-2 earn-red + drift-lock. scope_gate treats rc==1 as a legitimate skip
        # ONLY when scope-check's report carries the "no Affected symbols" signal; a rc==1
        # that is actually a crash/error must NOT be swallowed as a clean skip. The pack's
        # PRESCRIBED grep ("no affected symbols|declares no affected") did NOT match the
        # message cmd_scope_check truly emits ("This pack has no 'Affected symbols'
        # section") -- so as authored it would misclassify EVERY legitimate skip as an
        # errored probe. This reads the driver's ACTUAL grep pattern and pins it against
        # the CLI's ACTUAL output: RED on the pre-fix pattern, and a permanent guard if
        # either the driver grep or the CLI message drifts out of lockstep.
        import re
        script = (REPO_ROOT / "scripts" / "run_pack_chain.sh").read_text(encoding="utf-8")
        m = re.search(r'grep -qiE "([^"]+)" <<<"\$report"', script)
        assert m, "scope_gate's rc==1 disambiguation grep was not found in the driver"
        gate = re.compile(m.group(1), re.IGNORECASE)

        # 1) The real no-symbols pack -> rc 1 + a message the grep MUST match (legit skip).
        pack = _write_pack(tmp_path, "TP-105", "nosym", symbol=None)
        skip = subprocess.run(
            ["python3", "-m", "espalier", "scope-check", str(pack)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        )
        assert skip.returncode == 1, skip.stdout + skip.stderr
        assert gate.search(skip.stdout + skip.stderr), (
            "driver grep failed to recognize the REAL no-symbols skip message "
            f"(would mis-surface a legit skip as a crash): {skip.stdout!r}"
        )
        # 2) A missing pack -> rc 1 (a FAIL, not a skip) the grep MUST NOT match.
        err = subprocess.run(
            ["python3", "-m", "espalier", "scope-check", str(tmp_path / "NOPE-does-not-exist.md")],
            cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        )
        assert err.returncode == 1, err.stdout + err.stderr
        assert not gate.search(err.stdout + err.stderr), (
            "driver grep wrongly matched an ERROR output as a clean skip: "
            f"{(err.stdout + err.stderr)!r}"
        )

    def test_missing_receipt_halts_the_chain(self, tmp_path):
        # A session that commits but writes NO cc/_pack_receipt.json has not attested
        # its steps. The pre-fix verify_red_team read "no artifact = honest null =
        # pass" and LANDED; the receipt gate must HALT instead. (Discriminates the
        # fix: RED = the old driver lands, GREEN = the new driver halts.)
        r, _repo, _pd = _run_with_fake_claude(tmp_path, _fake_claude_body(None))
        assert r.returncode != 0, r.stdout + r.stderr
        assert "did not attest" in (r.stdout + r.stderr)
        assert "HALTED-receipt" in r.stdout
        assert "LANDED" not in r.stdout

    def test_halted_claude_row_on_nonzero_child_exit(self, tmp_path):
        # The third halt branch, previously uncovered: TP-337 scoped it out AND
        # promised an in-file known-gap note in lieu of coverage; neither landed.
        # Fails CLOSED -- halts and propagates rc -- so this pins the report row
        # and the exit code, not a fail-open. The `claude` child exiting nonzero
        # is the usage-cap / crash case, which is how an unattended chain
        # actually dies.
        r, _repo, _pd = _run_with_fake_claude(tmp_path, "exit 7\n")
        assert r.returncode == 7, (
            f"driver must PROPAGATE the child's rc, got {r.returncode}\n"
            + r.stdout + r.stderr
        )
        assert "HALTED-claude" in r.stdout, r.stdout + r.stderr
        assert "LANDED" not in r.stdout
        # Discriminates from the sibling halt arms: a nonzero child exit is not
        # a no-commit and not a missing receipt.
        assert "HALTED-nocommit" not in r.stdout
        assert "HALTED-receipt" not in r.stdout

    def test_clean_receipt_lands(self, tmp_path):
        # red_team.ran + pack_review.ran true, zero blockers -> the receipt is itself
        # the proof both ran; the pack LANDS. Discriminates via the new confirmation
        # log ("0-A RAN") the old honest-null path never emits.
        r, _repo, _pd = _run_with_fake_claude(tmp_path, _fake_claude_body(_CLEAN_RECEIPT))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "LANDED" in r.stdout
        assert "0-A RAN" in r.stdout          # the receipt-confirmation log (new path only)
        assert "HALTED" not in r.stdout

    def test_receipt_with_skipped_pack_review_halts(self, tmp_path):
        # pack_review.ran false == 0-A was skipped -> HALT (skip-detection). This is
        # the gap the unified receipt closes vs the old red-team-only artifact, which
        # had no view of 0-A at all. RED = old driver ignores the receipt and lands.
        receipt = _CLEAN_RECEIPT.replace('"pack_review":{"ran":true', '"pack_review":{"ran":false')
        r, _repo, _pd = _run_with_fake_claude(tmp_path, _fake_claude_body(receipt))
        assert r.returncode != 0, r.stdout + r.stderr
        assert "pack_review.ran" in r.stdout or "0-A" in r.stdout
        assert "LANDED" not in r.stdout

    def test_driver_finalizes_landing_when_session_skips_step_12(self, tmp_path):
        # 8/9 overnight sessions committed but left the pack in the pack dir at
        # State: DRAFT (re-surfacing as pending work). The driver must OWN the
        # finalize: move to Done/ + stamp State/Commits/Date + the receipt's
        # session-ATTESTED suite count. RED: no finalize -> the pack stays put.
        r, repo, packdir = _run_with_fake_claude(tmp_path, _fake_claude_body(_CLEAN_RECEIPT))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "LANDED" in r.stdout
        assert "driver finalized move-to-Done" in r.stdout
        moved = packdir / "Done" / "TP-700-cfg.md"
        assert moved.exists(), sorted(p.name for p in packdir.rglob("*"))
        assert not (packdir / "TP-700-cfg.md").exists()          # left the pack dir
        stanza = moved.read_text(encoding="utf-8")
        assert "State: LANDED" in stanza
        short = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo,
            capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        assert short and short in stanza                         # Commits: the verified SHA
        assert "4242 passed" in stanza                           # the receipt's attested count
        assert "session-attested" in stanza                      # provenance label (no fabrication)
        assert "Date:" in stanza

    def test_finalize_is_idempotent_when_session_did_step_12(self, tmp_path):
        # A session that already moved + fully stamped the pack (with its OWN suite
        # count) -> the driver confirms, never double-moves or overwrites it.
        idem_body = (
            'git commit --allow-empty -qm "test: a change with no pack id"\n'
            'mkdir -p cc\n'
            "cat > cc/_pack_receipt.json <<'JSON'\n" + _CLEAN_RECEIPT + "\nJSON\n"
            'mkdir -p "$PACK_CHAIN_PACKDIR/Done"\n'
            "cat > \"$PACK_CHAIN_PACKDIR/Done/TP-700-cfg.md\" <<'PACKMD'\n"
            "# TP-700 cfg\n\n## Landing\n\n- State: LANDED\n- **Commits:** deadbee\n"
            "- **Suite:** 9999 passed / 0 skipped (session-attested)\n- **Date:** 2026-07-20\n"
            "PACKMD\n"
            'rm -f "$PACK_CHAIN_PACKDIR/TP-700-cfg.md"\n'
            'exit 0\n'
        )
        r, _repo, packdir = _run_with_fake_claude(tmp_path, idem_body)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "landing already in Done/" in r.stdout   # target-aware confirm (was "already complete")
        stanza = (packdir / "Done" / "TP-700-cfg.md").read_text(encoding="utf-8")
        assert "9999 passed" in stanza          # the session's own number, preserved
        assert "4242 passed" not in stanza      # driver did NOT re-stamp from the receipt

    def test_finalize_completes_a_partial_stanza_in_done(self, tmp_path):
        # The feature's rationale is that a one-shot session is UNRELIABLE at step 12: a
        # session that moved the pack to Done/ but stamped only State (no
        # Commits/Suite/Date) is the exact partial the driver must COMPLETE. Idempotency
        # keyed on COMPLETENESS, not location -> re-stamp the destination (set_field
        # leaves session-filled fields alone, so it only fills the gaps).
        partial_body = (
            'git commit --allow-empty -qm "test: a change with no pack id"\n'
            'mkdir -p cc\n'
            "cat > cc/_pack_receipt.json <<'JSON'\n" + _CLEAN_RECEIPT + "\nJSON\n"
            'mkdir -p "$PACK_CHAIN_PACKDIR/Done"\n'
            "cat > \"$PACK_CHAIN_PACKDIR/Done/TP-700-cfg.md\" <<'PACKMD'\n"
            "# TP-700 cfg\n\n## Landing\n\n- State: LANDED\nPACKMD\n"
            'rm -f "$PACK_CHAIN_PACKDIR/TP-700-cfg.md"\n'
            'exit 0\n'
        )
        r, repo, packdir = _run_with_fake_claude(tmp_path, partial_body)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "landing already in Done/" in r.stdout          # target-aware confirm log
        stanza = (packdir / "Done" / "TP-700-cfg.md").read_text(encoding="utf-8")
        short = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo,
            capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        assert short and short in stanza                       # Commits: filled by the driver
        assert "4242 passed" in stanza                         # Suite: from the receipt
        assert "session-attested" in stanza                    # provenance label
        assert "Date:" in stanza                               # the fields the session skipped

    def test_finalize_does_not_force_land_a_bold_value_scrapped(self, tmp_path):
        # A bold VALUE `State: **SCRAPPED**` (the exact mis-spelling implement-pack.md
        # warns operators against) slips ckl.landed_state -- _STATE_RE's `(\w+)` rejects
        # the leading `**`, so it returns None, the SCRAPPED-respect guard passes, and
        # the finalize would FORCE-land it. Defense: a Landing region that HAS a State:
        # line the parser cannot read cleanly is AMBIGUOUS -> never overwrite it.
        r, _repo, packdir = _run_with_fake_claude(
            tmp_path, _fake_claude_body(_CLEAN_RECEIPT), landing_state="**SCRAPPED**",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AMBIGUOUS" in (r.stdout + r.stderr)                # the defensive skip fired
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()   # NOT moved
        stanza = (packdir / "TP-700-cfg.md").read_text(encoding="utf-8")
        assert "State: **SCRAPPED**" in stanza                     # not overwritten
        assert "State: LANDED" not in stanza

    def test_finalize_ambiguous_defense_is_bounded_to_the_landing_stanza(self, tmp_path):
        # Scope-consistency: the AMBIGUOUS defense must key off the BOUNDED Landing
        # region (## Landing -> next heading), the same region set_field mutates -- NOT
        # the unbounded ckl.landed_state scan (## Landing -> EOF). A readable `State:`
        # line in a section AFTER the Landing stanza must not mask an unparseable
        # `State: **SCRAPPED**` INSIDE it and let the finalize force-land the pack.
        append_body = (
            # a section AFTER Landing with a READABLE State: -- landed_state (Landing->EOF)
            # would pick THIS up as "LANDED" and skip the AMBIGUOUS guard, but the bounded
            # region still holds the unparseable bold value the driver must respect.
            'printf "\\n## Notes\\n\\n- State: LANDED\\n" >> "$PACK_CHAIN_PACKDIR/TP-700-cfg.md"\n'
            + _fake_claude_body(_CLEAN_RECEIPT)
        )
        r, _repo, packdir = _run_with_fake_claude(
            tmp_path, append_body, landing_state="**SCRAPPED**",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AMBIGUOUS" in (r.stdout + r.stderr)                # bounded region -> AMBIGUOUS
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()   # NOT force-landed / moved
        stanza = (packdir / "TP-700-cfg.md").read_text(encoding="utf-8")
        assert "State: **SCRAPPED**" in stanza                     # Landing State untouched

    def test_finalize_leaves_a_pack_without_a_landing_stanza_in_place(self, tmp_path):
        # A pack with a State: line in ## Status but NO ## Landing stanza (older packs
        # predate it) passes preflight. The finalize heredoc prints NO_LANDING and
        # writes nothing -- the driver must NOT move it to Done/ with a false "stamped"
        # success (that would reintroduce the unstamped-Done-pack class this finalize
        # exists to close). Committed negative fixture for the fail-open branch.
        r, _repo, packdir = _run_with_fake_claude(
            tmp_path, _fake_claude_body(_CLEAN_RECEIPT), landing=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr        # the commit still landed
        # TP-312 E-1 earn-red: the outcome must be LANDED-nostamp, NOT a clean LANDED.
        # Pre-fix, finalize_landing returned 0 on the NO_LANDING branch and the caller
        # UNCONDITIONALLY reported `pack|LANDED|...` while the pack actually sat at DRAFT
        # in root and check_pack_landing globs Done/ only -- a green-but-incomplete mask.
        # `finalize_landing` now returns 3 and the caller branches the row; this REDs on
        # the pre-fix script (which emits a clean LANDED for exactly this input).
        assert "LANDED-nostamp" in r.stdout, r.stdout + r.stderr
        assert "committed but landing NOT stamped" in r.stderr
        assert "driver finalized move-to-Done" not in r.stdout   # no false stamp claim
        assert "stamped State/Commits/Date" not in r.stdout
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()  # NOT moved to Done/
        assert (packdir / "TP-700-cfg.md").exists()               # left in place for triage

    def test_finalize_neither_location_reports_landed_unverified(self, tmp_path):
        # TP-337 3-A earn-red: the THIRD finalize_landing fail-open sibling TP-312
        # missed. A session that commits but leaves the pack file at NEITHER `$file`
        # NOR `Done/<original-basename>` (renamed/deleted to a name the driver can't
        # resolve) hit the else branch's bare `return 0` -> the caller reported a
        # silent clean LANDED while the driver could not verify the Landing was ever
        # stamped. The fix: search Done/ by TP-id first (a legitimately-renamed +
        # stamped pack is a true LANDED, below), else emit LANDED-unverified + a
        # stderr diagnostic so the row carries a triage marker, not a clean claim.
        # RED pre-fix: the else branch returns 0 and the row reads a clean `LANDED`.
        neither_body = (
            'git commit --allow-empty -qm "test: a change with no pack id"\n'
            'mkdir -p cc\n'
            "cat > cc/_pack_receipt.json <<'JSON'\n" + _CLEAN_RECEIPT + "\nJSON\n"
            # the session deleted the pack file to a name the driver can't resolve
            # (neither the original path nor Done/<original-basename> exists now).
            'rm -f "$PACK_CHAIN_PACKDIR/TP-700-cfg.md"\n'
            'exit 0\n'
        )
        r, _repo, packdir = _run_with_fake_claude(tmp_path, neither_body)
        assert r.returncode == 0, r.stdout + r.stderr            # the commit still landed
        assert "LANDED-unverified" in r.stdout, r.stdout + r.stderr   # RED pre-fix (clean LANDED)
        assert "pack file vanished" in r.stderr                  # the triage diagnostic
        assert "driver finalized move-to-Done" not in r.stdout   # no false stamp claim
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()  # nothing to move

    def test_finalize_finds_a_renamed_and_stamped_pack_in_done(self, tmp_path):
        # TP-337 3-A step 1 (the over-triage guard): the branch is LEGITIMATELY
        # correct when a pack renamed AND stamped itself under a NEW name in Done/ --
        # the driver just can't locate it by the original basename. A blanket
        # `return 3/4` there would over-triage every renamed-and-landed pack as
        # unverified. The Done/-by-TP-id search must find it and report a true clean
        # LANDED. Locks the fix against the blanket-triage over-correction.
        renamed_body = (
            'git commit --allow-empty -qm "test: a change with no pack id"\n'
            'mkdir -p cc\n'
            "cat > cc/_pack_receipt.json <<'JSON'\n" + _CLEAN_RECEIPT + "\nJSON\n"
            # session renamed the pack under a NEW basename in Done/, fully stamped.
            'mkdir -p "$PACK_CHAIN_PACKDIR/Done"\n'
            "cat > \"$PACK_CHAIN_PACKDIR/Done/TP-700-renamed-slug.md\" <<'PACKMD'\n"
            "# TP-700 renamed\n\n## Landing\n\n- State: LANDED\n- **Commits:** deadbee\n"
            "- **Suite:** 9999 passed / 0 skipped (session-attested)\n- **Date:** 2026-07-24\n"
            "PACKMD\n"
            'rm -f "$PACK_CHAIN_PACKDIR/TP-700-cfg.md"\n'   # original name gone
            'exit 0\n'
        )
        r, _repo, packdir = _run_with_fake_claude(tmp_path, renamed_body)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "LANDED-unverified" not in r.stdout, r.stdout + r.stderr   # NOT over-triaged
        assert "true LANDED" in r.stdout                         # the Done/-by-TP-id search hit
        # the renamed+stamped pack is the true landing; original basename absent.
        assert (packdir / "Done" / "TP-700-renamed-slug.md").exists()
        assert not (packdir / "TP-700-cfg.md").exists()

    def test_post_commit_install_fail_then_reinvoke_regates_not_nocommit(self, tmp_path):
        # TP-337 3-B/3-C earn-red: a post-commit gate halt (a transient install-green
        # flake, forced here via the PACK_CHAIN_FORCE_INSTALL_FAIL test seam) leaves the
        # pack COMMITTED but un-ledgered (the ledger is appended only AFTER the gates
        # pass). Pre-3-B, a plain re-invoke re-ran the -p session, which -- the work
        # already committed -- made NO new commit, tripped the HEAD-advance check, and
        # false-halted as HALTED-nocommit: a phantom "the session failed to commit" when
        # the commit is right there in git. 3-B records a committed-but-ungated marker
        # the instant HEAD advances (BEFORE the gates), so a re-invoke detects "already
        # committed" and re-runs ONLY the post-commit gates against the existing HEAD.
        #
        # This single fixture drives the full two-invocation cycle and simultaneously
        # (i) lights the zero-coverage HALTED-install arm (run 1), (ii) earns the red for
        # the false-halt-on-resume (run 2 = HALTED-nocommit pre-3-B), (iii) proves the
        # re-gate lands without re-running the session (run 2 post-3-B).
        repo, packdir, ledger, marker, drive = _regate_two_run_fixture(tmp_path)

        # run 1: commit + receipt OK, install-green FORCED to fail -> HALTED-install.
        r1 = drive(PACK_CHAIN_FORCE_INSTALL_FAIL="1")
        assert "HALTED-install" in r1.stdout, r1.stdout + r1.stderr   # zero-coverage arm, now lit
        assert r1.returncode != 0, r1.stdout + r1.stderr
        assert marker.exists() and marker.read_text(encoding="utf-8").startswith("TP-700|"), (
            "committed-but-ungated marker not written the instant HEAD advanced"
        )
        assert not ledger.exists() or "TP-700" not in ledger.read_text(encoding="utf-8")  # NOT fully landed

        # run 2: flake cleared (install gate skipped) -> must RE-GATE the existing commit,
        # NOT re-run the -p session and false-halt as HALTED-nocommit.
        r2 = drive(PACK_CHAIN_SKIP_INSTALL_GATE="1")
        assert "HALTED-nocommit" not in r2.stdout, r2.stdout + r2.stderr   # the core earn-red
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "LANDED" in r2.stdout, r2.stdout + r2.stderr
        assert "already committed" in r2.stdout                       # the re-gate path fired
        # the -p session was SKIPPED on the re-invoke (re-gated the existing commit):
        # exactly ONE pack commit exists (run 1's), not a second from a re-run session.
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
        ).stdout
        assert log.count("no pack id") == 1, log
        assert (packdir / "Done" / "TP-700-cfg.md").exists()          # finalized on the re-gate
        assert "TP-700|" not in marker.read_text(encoding="utf-8")    # marker cleared after landing

    def test_regate_rejects_a_foreign_receipt(self, tmp_path):
        # Adversarial-review finding (false-GREEN, the forbidden direction): the re-gate
        # path re-runs the receipt gate against whatever cc/_pack_receipt.json is on disk
        # WITHOUT re-running the session, and the receipt gate did not check receipt.pack.
        # So if an UNRELATED pack ran between the post-commit halt and the re-invoke (the
        # shared receipt file is rm'd + rewritten per session), re-gating pack A would
        # green-wash A with pack B's attestation (B's SHA + suite in A's Landing stanza).
        # Fix: the receipt gate HALTs on a present-but-mismatched receipt.pack. RED
        # pre-fix: A lands clean on B's proof.
        repo, packdir, _ledger, marker, drive = _regate_two_run_fixture(tmp_path)

        # run 1: commit + receipt(pack=TP-700), install FORCED to fail -> committed+marked.
        r1 = drive(PACK_CHAIN_FORCE_INSTALL_FAIL="1")
        assert "HALTED-install" in r1.stdout, r1.stdout + r1.stderr
        assert marker.read_text(encoding="utf-8").startswith("TP-700|")

        # A different pack ran in between and left ITS receipt on disk (pack=TP-999).
        (repo / "cc" / "_pack_receipt.json").write_text(_FOREIGN_RECEIPT, encoding="utf-8")

        # run 2: re-invoke TP-700 -> the re-gate must reject the foreign receipt, NOT land
        # TP-700 on TP-999's attestation.
        r2 = drive(PACK_CHAIN_SKIP_INSTALL_GATE="1")
        assert r2.returncode != 0, r2.stdout + r2.stderr
        assert "foreign/stale receipt" in (r2.stdout + r2.stderr), r2.stdout + r2.stderr
        assert "|LANDED" not in r2.stdout, r2.stdout           # NOT green-washed to LANDED
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()   # not moved/stamped
        assert marker.read_text(encoding="utf-8").startswith("TP-700|")  # marker retained for a real re-run

    def test_regate_rejects_a_reset_away_commit(self, tmp_path):
        # Adversarial-review finding (false-GREEN): the re-gate gated + stamped current
        # HEAD with no ancestor check on the recorded commit. If the operator reset/rebased
        # the pack's work away (e.g. `git reset --hard` to redo it) and re-invoked, the
        # re-gate would land the pack against a HEAD that no longer contains its commit.
        # Fix: HALT unless the recorded commit is still an ancestor of HEAD. RED pre-fix:
        # the pack lands (State: LANDED, stamped with an unrelated HEAD) though its work
        # is gone from history.
        repo, packdir, _ledger, marker, drive = _regate_two_run_fixture(tmp_path)

        # run 1: commit + receipt, install FORCED to fail -> committed+marked at shaA.
        r1 = drive(PACK_CHAIN_FORCE_INSTALL_FAIL="1")
        assert "HALTED-install" in r1.stdout, r1.stdout + r1.stderr
        assert marker.read_text(encoding="utf-8").startswith("TP-700|")

        # operator resets the pack's commit away (its work is no longer in HEAD's history).
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=repo, check=True,
                       capture_output=True)

        # run 2: re-invoke TP-700 -> the recorded commit is no longer an ancestor of HEAD;
        # the re-gate must HALT, not phantom-land the pack against the reset HEAD.
        r2 = drive(PACK_CHAIN_SKIP_INSTALL_GATE="1")
        assert r2.returncode != 0, r2.stdout + r2.stderr
        assert "HALTED-regate" in r2.stdout, r2.stdout + r2.stderr
        assert "an ancestor of HEAD" in (r2.stdout + r2.stderr) or "no longer exists" in (r2.stdout + r2.stderr)
        assert "|LANDED" not in r2.stdout, r2.stdout           # NOT phantom-landed
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()

    def test_kill_in_finalize_window_leaves_pack_resumable(self, tmp_path):
        # DEF-353a earn-red: post_commit_verify_and_finalize appends the resume ledger
        # and clears the committed marker as two separate statements. A kill BETWEEN them
        # (crash, budget cut-off, SIGTERM) must not strand a fully-landed pack -- already
        # moved to Done/ by finalize_landing -- invisible to BOTH resume paths. In the
        # marker-clear-THEN-ledger-append order, a kill in the window leaves the marker
        # cleared AND the ledger empty, so a plain re-invoke false-HALTs at preflight
        # ("no pack file" -- the pack now lives in Done/). Appending the ledger FIRST
        # records the land before the window opens, so the same kill leaves the pack
        # ledger-recoverable (SKIP-resumed), with at worst a stale marker the ledger-skip
        # shadows. The PACK_CHAIN_FORCE_KILL_IN_FINALIZE_WINDOW seam exits 143 in that
        # exact window so the two-run kill/resume cycle is faithful, not a static mock.
        _repo, packdir, ledger, _marker, drive = _regate_two_run_fixture(tmp_path)

        # run 1: receipt + install gates pass, finalize moves the pack to Done/, then a
        # simulated kill lands inside the append/clear window.
        r1 = drive(PACK_CHAIN_SKIP_INSTALL_GATE="1",
                   PACK_CHAIN_FORCE_KILL_IN_FINALIZE_WINDOW="1")
        assert r1.returncode != 0, r1.stdout + r1.stderr             # died in the window
        assert (packdir / "Done" / "TP-700-cfg.md").exists()         # finalize ran before the kill
        assert not (packdir / "TP-700-cfg.md").exists()              # original location vacated
        # Tie the earn-red directly to the ORDERING, not just run2's two-hop inference: the
        # ledger must already record the land at kill time. Reverting the reorder (clear-first)
        # leaves this empty and reds here immediately, regardless of where the seam sits.
        assert ledger.read_text(encoding="utf-8").strip() == "TP-700"

        # run 2: plain re-invoke (no kill). The land must be recoverable from the ledger
        # -> SKIP-resumed, never a false-HALT on the moved-away pack file.
        r2 = drive(PACK_CHAIN_SKIP_INSTALL_GATE="1")
        assert r2.returncode == 0, r2.stdout + r2.stderr             # RED pre-reorder: false-halts
        assert "SKIPPED-resumed" in r2.stdout, r2.stdout + r2.stderr
        assert "no pack file" not in r2.stderr, r2.stdout + r2.stderr

    def test_preflight_honors_committed_marker_for_a_pack_moved_to_done(self, tmp_path):
        # DEF-353a, adjacent window (one step earlier than the append/clear window above):
        # a prior invocation committed a pack, finalize_landing moved it to Done/, and the
        # committed-marker was recorded, but the kill landed BEFORE the ledger append. End
        # state: pack in Done/, marker SET to a real ancestor commit, ledger EMPTY, receipt
        # persisted. The main loop's committed-marker path re-gates this correctly, but
        # preflight_chain runs FIRST and -- consulting ONLY the ledger -- false-HALTed the
        # whole chain ("no pack file") before the loop's marker resume ever ran. The reorder
        # alone cannot close this window (the marker, not the ledger, is what records the
        # land here); preflight must also honor the committed marker, mirroring the loop.
        # State is manufactured directly (a preflight REACTS to a given state -- no kill to
        # simulate, so no seam), reusing the re-gate fixture's helpers.
        repo, packdir, ledger, marker, drive = _regate_two_run_fixture(tmp_path)
        subprocess.run(["git", "commit", "--allow-empty", "-qm", "test: a change with no pack id"],
                       cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8").stdout.strip()
        (packdir / "Done").mkdir()
        (packdir / "Done" / "TP-700-cfg.md").write_text(
            (packdir / "TP-700-cfg.md").read_text(encoding="utf-8"), encoding="utf-8")
        (packdir / "TP-700-cfg.md").unlink()                        # moved to Done/ by the prior finalize
        marker.write_text(f"TP-700|{sha}\n", encoding="utf-8")      # committed-marker recorded
        assert not ledger.exists() or not ledger.read_text(encoding="utf-8").strip()   # ledger EMPTY
        (repo / "cc").mkdir(exist_ok=True)
        (repo / "cc" / "_pack_receipt.json").write_text(_CLEAN_RECEIPT, encoding="utf-8")

        # Re-invoke: preflight must NOT false-halt on the moved pack -- the committed marker
        # means the loop re-gates it. RED pre-fix (preflight is ledger-only): "no pack file".
        r = drive(PACK_CHAIN_SKIP_INSTALL_GATE="1")
        assert "no pack file" not in r.stderr, r.stdout + r.stderr   # the core earn-red
        assert r.returncode == 0, r.stdout + r.stderr
        assert "LANDED" in r.stdout, r.stdout + r.stderr             # re-gated + landed via the marker path
        assert (packdir / "Done" / "TP-700-cfg.md").exists()

    def test_receipt_with_skipped_red_team_halts(self, tmp_path):
        # Symmetric to the pack_review skip: red_team.ran false == the red-team was
        # skipped -> HALT. Locks the second skip-detection branch against a refactor.
        receipt = _CLEAN_RECEIPT.replace('"red_team":{"ran":true', '"red_team":{"ran":false')
        r, _repo, _pd = _run_with_fake_claude(tmp_path, _fake_claude_body(receipt))
        assert r.returncode != 0, r.stdout + r.stderr
        assert "red_team.ran" in r.stdout or "red-team skipped" in r.stdout
        assert "LANDED" not in r.stdout

    def test_finalize_respects_scrapped_state(self, tmp_path):
        # A pack authored State: SCRAPPED in its Landing stanza -> finalize must NOT
        # overwrite it to LANDED or move it (the deliberate-abandonment safety net).
        r, _repo, packdir = _run_with_fake_claude(
            tmp_path, _fake_claude_body(_CLEAN_RECEIPT), landing_state="SCRAPPED",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "SCRAPPED" in (r.stdout + r.stderr)            # the respecting-SCRAPPED log fired
        # E-1: the SCRAPPED branch also returns 3, so the caller reports LANDED-nostamp,
        # NOT a clean LANDED -- locks the shared return-3 path beyond the NO_LANDING branch.
        assert "LANDED-nostamp" in r.stdout, r.stdout + r.stderr
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()   # not moved
        stanza = (packdir / "TP-700-cfg.md").read_text(encoding="utf-8")
        assert "State: SCRAPPED" in stanza                    # not overwritten
        assert "State: LANDED" not in stanza

    def test_goal_receipt_template_names_every_field_the_driver_reads(self, tmp_path):
        # Receipt-schema drift guard: the goal (producer) tells the session which
        # fields to write; verify_pack_receipt + finalize_landing (consumers) read
        # specific keys. A rename in one site silently HALTs every real run while the
        # suite stays green (tests inject their own receipt). Pin the producer
        # template to name every consumer-read key -- a rename fails HERE.
        _write_pack(tmp_path, "TP-100", "clean")
        r = _run_driver(tmp_path, "--dry-run", "TP-100")
        assert r.returncode == 0, r.stdout + r.stderr
        goal = r.stdout
        for key in (
            "red_team", "ran", "finding_count", "blocker_count",
            "pack_review", "blocks", "suite", "passed", "skipped",
            "commit", "changelog_touched",
        ):
            assert key in goal, f"goal receipt template missing consumer-read key: {key!r}"

    def test_dispatch_sentinel_halts_a_dead_dispatch(self, tmp_path):
        # A prose-degraded dispatch (a /status probe that returns NO banner token) must
        # HALT the chain at startup, before any pack spends -p budget -- otherwise a
        # headless-slash regression silently degrades every goal to a prose paraphrase
        # and reintroduces the mechanically-green-but-incomplete class. The sentinel is
        # the ONLY mechanical guard against a dispatch regression (a prose-degraded
        # session still writes a receipt claiming it ran).
        r, repo, _pd = _run_with_fake_claude(
            tmp_path,
            _fake_claude_body_with_sentinel(_CLEAN_RECEIPT, dispatch_ok=False),
            skip_sentinel=False,
        )
        assert r.returncode != 0, r.stdout + r.stderr
        assert "did NOT dispatch" in r.stderr
        assert "PACK: TP-700 " not in r.stdout            # never reached the run loop
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
        ).stdout
        assert "no pack id" not in log                    # the pack -p goal never ran

    def test_dispatch_sentinel_passes_a_live_dispatch(self, tmp_path):
        # Lock against a false-halt: a live dispatch (the /status probe returns its
        # banner token) passes the sentinel and the pack lands normally.
        r, repo, _pd = _run_with_fake_claude(
            tmp_path,
            _fake_claude_body_with_sentinel(_CLEAN_RECEIPT, dispatch_ok=True),
            skip_sentinel=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "dispatch sentinel: /status dispatched" in r.stdout
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
        ).stdout
        assert "no pack id" in log                        # the pack actually ran + committed

    def test_sentinel_marker_is_a_token_the_status_banner_emits(self):
        # Coupling tripwire: SENTINEL_MARKER must be a token the REAL /status banner
        # emits (/status runs `session_resume.py --mode status`). The coupling otherwise
        # lives only in an inline comment; a banner rename would silently leave the
        # sentinel stale and false-halt the next chain with a misleading "did NOT
        # dispatch". Fail HERE -- at the driver's own test, pointing at the marker --
        # instead of in an unattended run chasing a non-existent dispatch regression.
        import re
        m = re.search(r'SENTINEL_MARKER="([^"]+)"', SCRIPT.read_text(encoding="utf-8"))
        assert m, "SENTINEL_MARKER not found in run_pack_chain.sh"
        marker = m.group(1)
        banner = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "status"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        )
        assert marker in banner.stdout, (
            f"SENTINEL_MARKER {marker!r} no longer appears in the /status banner "
            f"(session_resume --mode status) -- the dispatch sentinel would false-halt "
            f"every chain. Update SENTINEL_MARKER in scripts/run_pack_chain.sh to match "
            f"the renamed banner token.\nbanner was:\n{banner.stdout}"
        )

    def test_finalize_fresh_stamps_a_landing_with_no_state_line(self, tmp_path):
        # Boundary of the AMBIGUOUS guard: a ## Landing heading whose body has NO State:
        # line is NOT ambiguous (nothing to preserve) -- it falls through to a fresh
        # stamp. Locks the guard's `re.search(State:, region)` false-branch.
        nostate_body = (
            'git commit --allow-empty -qm "test: a change with no pack id"\n'
            'mkdir -p cc\n'
            "cat > cc/_pack_receipt.json <<'JSON'\n" + _CLEAN_RECEIPT + "\nJSON\n"
            'mkdir -p "$PACK_CHAIN_PACKDIR/Done"\n'
            "cat > \"$PACK_CHAIN_PACKDIR/Done/TP-700-cfg.md\" <<'PACKMD'\n"
            "# TP-700 cfg\n\n## Landing\n\n- Earn-the-red: none\nPACKMD\n"
            'rm -f "$PACK_CHAIN_PACKDIR/TP-700-cfg.md"\n'
            'exit 0\n'
        )
        r, _repo, packdir = _run_with_fake_claude(tmp_path, nostate_body)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AMBIGUOUS" not in (r.stdout + r.stderr)        # a no-State region is not ambiguous
        stanza = (packdir / "Done" / "TP-700-cfg.md").read_text(encoding="utf-8")
        assert "State:" in stanza and "LANDED" in stanza       # freshly stamped
        assert "4242 passed" in stanza                         # + the receipt's suite count

    def test_fresh_dry_run_does_not_clear_ledger_or_marker(self, tmp_path):
        # Finding B (PACKCHAIN-DRYRUN-FRESH-CLEARS-LEDGER): the `--fresh` `: > "$FILE"` clears
        # sit OUTSIDE every DRY_RUN guard, so `--fresh --dry-run` (a documented no-op: "print
        # plan, run nothing") silently TRUNCATES the resume ledger + committed marker. RED
        # pre-fix: both files come back empty. GREEN post-fix: byte-identical + a "WOULD clear"
        # line is printed instead.
        _write_pack(tmp_path, "TP-100", "clean")
        ledger = tmp_path / "ledger.txt"
        marker = tmp_path / "committed.txt"
        ledger.write_text("TP-999\n", encoding="utf-8")            # unrelated resume state
        marker.write_text("TP-888|abc1234\n", encoding="utf-8")
        ledger_before, marker_before = ledger.read_bytes(), marker.read_bytes()
        env = dict(os.environ)
        env["PACK_CHAIN_PACKDIR"] = str(tmp_path)
        env["PACK_CHAIN_LEDGER"] = str(ledger)
        env["PACK_CHAIN_COMMITTED_MARKER"] = str(marker)
        r = subprocess.run(
            ["bash", str(SCRIPT), "--fresh", "--dry-run", "TP-100"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert ledger.read_bytes() == ledger_before, "dry-run truncated the resume ledger"
        assert marker.read_bytes() == marker_before, "dry-run truncated the committed marker"
        assert "WOULD clear" in r.stdout

    def test_dry_run_with_committed_marker_does_not_regate_or_false_halt(self, tmp_path):
        # Finding A (PACKCHAIN-DRYRUN-RESUME): the committed-but-ungated resume block has NO
        # DRY_RUN guard, and the fresh-path DRY_RUN short-circuit is only reached AFTER the
        # resume `continue`. So `--dry-run` on a repo with a committed marker enters
        # post_commit_verify_and_finalize -> the receipt gate fires with no receipt present and
        # `exit 1`s (false-halt), and, given a receipt, would move the pack to Done/ + rewrite
        # its Landing (tree mutation). RED pre-fix: returncode != 0 (HALTED-receipt). GREEN
        # post-fix: returncode 0, a DRY-RUN row, pack NOT moved, marker/ledger intact.
        repo = tmp_path / "repo"
        repo.mkdir()
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                    ["git", "config", "user.name", "t"]):
            subprocess.run(cmd, cwd=repo, check=True)
        (repo / "seed").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8").stdout.strip()
        assert sha, "fixture git rev-parse returned empty"

        packdir = tmp_path / "packs"; packdir.mkdir()
        pack = _write_pack(packdir, "TP-700", "cfg", symbol=None)
        ledger = tmp_path / "ledger.txt"
        marker = tmp_path / "committed.txt"
        marker.write_text(f"TP-700|{sha}\n", encoding="utf-8")     # a REAL ancestor of HEAD
        marker_before = marker.read_bytes()

        env = dict(os.environ)
        env["PACK_CHAIN_PACKDIR"] = str(packdir)
        env["PACK_CHAIN_LEDGER"] = str(ledger)
        env["PACK_CHAIN_COMMITTED_MARKER"] = str(marker)
        r = subprocess.run(
            ["bash", str(SCRIPT), "--dry-run", "TP-700"],
            cwd=str(repo), env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert r.returncode == 0, r.stdout + r.stderr              # RED pre-fix: false-halt exit 1
        assert "DRY-RUN-regate" in r.stdout                        # the resume-block dry-run row, not a real re-gate
        assert "HALTED-receipt" not in r.stdout                    # did NOT run the receipt gate
        assert pack.exists()                                       # NOT moved to Done/
        assert not (packdir / "Done" / "TP-700-cfg.md").exists()
        assert marker.read_bytes() == marker_before               # marker untouched
        assert not ledger.exists() or ledger.read_bytes() == b""   # ledger not appended

    def test_dry_run_mutates_nothing(self, tmp_path):
        # Class invariant. The two point-tests above pin only the two blocks the pack fixed;
        # this one pins the CONTRACT itself: the documented "--dry-run = print plan, run
        # nothing" means NO dry-run shape may mutate the tree. It snapshots the whole fixture
        # state -- every pack file plus the resume ledger and committed marker, by content AND
        # path-set -- across every dry-run shape and asserts rc==0 AND byte-identical. A FUTURE
        # third mutating block added before the dry-run short-circuit reds HERE instead of
        # silently re-opening the class. Earns red pre-fix: the --fresh shapes truncate the
        # ledger/marker; the committed-marker shape false-halts exit 1.
        def _seed_repo(root):
            root.mkdir()
            for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                        ["git", "config", "user.name", "t"]):
                subprocess.run(cmd, cwd=root, check=True)
            (root / "seed").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
            out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                                 capture_output=True, text=True, encoding="utf-8").stdout.strip()
            assert out, "fixture git rev-parse returned empty"
            return out

        # TP-391 3-A: the driver's OTHER mutating surface. These three are written and
        # `rm -f`'d CWD-RELATIVE (run_pack_chain.sh defines them as bare `cc/*.json` and
        # never `cd`s), so they live outside the tmp fixture entirely and the original
        # _snap could not see them. Named explicitly rather than snapshotting "the cwd":
        # a REPO_ROOT-wide byte snapshot is 5,500+ files read twice per shape under
        # `timeout = 60`, across cc/ and __pycache__ which mutate concurrently -- that is
        # non-deterministic by construction, not merely slow.
        _CWD_ARTIFACTS = (
            "cc/_pack_receipt.json",
            "cc/red_team_findings.json",
            "cc/red_team_repros.json",
        )

        def _snap(base, packdir, ledger, marker, cwd):
            snap = {}
            for p in sorted(packdir.rglob("*")):
                if p.is_file():
                    snap[str(p.relative_to(base))] = p.read_bytes()
            for f in (ledger, marker):
                if f.is_file():
                    snap[str(f.relative_to(base))] = f.read_bytes()
            # Absence is a value: keyed to None when missing, so a dry run that CREATES
            # one of these reds just as loudly as one that deletes it. Keys are prefixed
            # rather than relative_to(base) because for the REPO_ROOT shapes the cwd is
            # not under `base` at all.
            for rel in _CWD_ARTIFACTS:
                p = cwd / rel
                snap[f"<cwd>/{rel}"] = p.read_bytes() if p.is_file() else None
            return snap

        # (label, argv, own_repo, marker_body, seed_ledger). The --fresh shapes run at
        # REPO_ROOT (they reach the read-only scope_gate, which needs a real repo) with a
        # marker --fresh nullifies; the committed-marker shape short-circuits before scope_gate
        # so it uses a throwaway repo + real ancestor SHA (the strongest pre-fix red path).
        # TP-391 3-A adds shape 3. Measured 2026-08-02, by instrumenting the script rather
        # than reading it: shapes 0/1 reach the pack-loop body (and the `rm -f` that guards
        # it) but run at REPO_ROOT; shape 2 runs in a throwaway repo but SHORT-CIRCUITS at
        # the committed-marker re-gate and never reaches that body at all. So none of the
        # original three can drive a cwd-mutating block safely: the two that reach it would
        # delete live cc/ session state, and the one that is safe cannot reach it.
        # Shape 3 is `--fresh --dry-run` in a THROWAWAY repo -- reaches the body AND is
        # disposable. Shapes 0/1 are deliberately left at REPO_ROOT: verified that
        # `scope_gate` fires there and does NOT in a throwaway, so re-pointing them would
        # silently drop scope-check from this contract.
        shapes = [
            ("fresh-dry-run", ["--fresh", "--dry-run"], False, "TP-888|abc1234\n", True),
            ("fresh-dry-run + marker", ["--fresh", "--dry-run"], False, "TP-700|deadbeefdeadbeef\n", True),
            ("dry-run + marker", ["--dry-run"], True, "TP-700|{sha}\n", False),
            ("fresh-dry-run @ own repo", ["--fresh", "--dry-run"], True, "TP-888|abc1234\n", True),
        ]
        for i, (label, argv, own_repo, marker_body, seed_ledger) in enumerate(shapes):
            case = tmp_path / f"case{i}"
            case.mkdir()
            packdir = case / "packs"; packdir.mkdir()
            _write_pack(packdir, "TP-700", "cfg")            # default symbol -> scope-check exit 0
            ledger = case / "ledger.txt"
            marker = case / "committed.txt"
            if seed_ledger:
                ledger.write_text("TP-999\n", encoding="utf-8")
            if own_repo:
                cwd = case / "repo"
                marker.write_text(marker_body.format(sha=_seed_repo(cwd)), encoding="utf-8")
                # Seed the driver's cwd artifacts so the widened domain has teeth: `rm -f`
                # on an ABSENT file is a no-op, so an unseeded fixture leaves even the
                # widened _snap green and shape 3 would be born weak -- the exact failure
                # class this pack exists to close. REPO_ROOT shapes are NOT seeded: there
                # the live files (or their absence) are the fixture, read-only.
                (cwd / "cc").mkdir(parents=True, exist_ok=True)
                for _rel in _CWD_ARTIFACTS:
                    (cwd / _rel).write_text('{"seeded": true}', encoding="utf-8")
            else:
                cwd = REPO_ROOT
                marker.write_text(marker_body, encoding="utf-8")

            before = _snap(case, packdir, ledger, marker, cwd)
            env = dict(os.environ)
            env["PACK_CHAIN_PACKDIR"] = str(packdir)
            env["PACK_CHAIN_LEDGER"] = str(ledger)
            env["PACK_CHAIN_COMMITTED_MARKER"] = str(marker)
            r = subprocess.run(
                ["bash", str(SCRIPT), *argv, "TP-700"],
                cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8",
            )
            after = _snap(case, packdir, ledger, marker, cwd)
            assert r.returncode == 0, f"[{label}] rc={r.returncode}\n{r.stdout}\n{r.stderr}"
            diff = {k: (before.get(k), after.get(k))
                    for k in set(before) | set(after) if before.get(k) != after.get(k)}
            assert not diff, f"[{label}] --dry-run mutated the fixture tree: {sorted(diff)}"
