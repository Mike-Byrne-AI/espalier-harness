# TP-361 — New dev tooling: pack-doc consistency linter + red_team_guard Integration C

## Status
- Version target: current (self-host, pre-OSS-launch)
- Change type: FEATURE — two net-new self-host maintainer tools, both verified
  un-built at HEAD. Neither is user-facing; neither gates the launch. Bundled
  here because they are the same shape (a small standalone dev tool over a
  surface the harness already parses/produces) and because both have been
  homeless — deferred to numbers that were reused, so they never entered the
  FORWARD_LEDGER lineage.
- **Kind: PACK** (two independent sub-tasks; may land as one commit or two)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`) +
  `reports/lost-idea-sweep-2026-07-26.md` — section C rows **#9** (pack-doc
  linter, source `Done/TP-318:126`) and **#27** (red_team_guard Integration C,
  source `reports/bp-00-06-analysis.md:184`).

## Motivation

The pre-flip sweep found 39 genuinely-lost forward-work items; ~two-thirds are
low-leverage self-host tooling. Two of those are net-new tools rather than
tweaks, so they earn a deliberate call rather than a one-line ledger row:

- **#9** — TP-318 built the *codebase* scope-check literal/symbol arm but
  explicitly scoped OUT a *pack-document* declaration-consistency linter,
  deferring it "to **TP-319**." TP-319 was then claimed by the unrelated
  OSS-landscape roadmap, so the linter has had no home for the interval. It is
  real and valuable — it mechanically catches the three declaration defects a
  session actually hit (a Files-touched file no Affected-symbol covers; a rename
  with no `### Renamed` entry; a silently-dropped Added-paths bullet) — but it
  validates *pack docs*, not source, so it is genuinely a different tool from the
  codebase scope-check it was scoped out of. It is distinct from the two partial
  overlaps: `scripts/check_pack_landing.py` (Landing-stanza only) and
  `tools/cc/pack_artifact_checklist.md` (a MANUAL LLM checklist, no mechanical
  teeth).

- **#27** — `espalier/red_team_guard.py` is LANDED (the re-execution gate that
  computes `externally_verified`) but has **no CLI and no CI leg**: grep confirms
  zero `red_team` references in `espalier/cli.py` and zero in `.github/`. The
  guard's public API (`guard_findings` / `format_report`) can only be reached
  from Python today. bp-00-06 named "Integration B (CI artifact-commit
  convention) + C (CLI subcommand)"; B is subsumed by the driver's
  `cc/_pack_receipt.json` attestation model (`docs/CONVENTIONS.md` ~L560), so
  only **C** remains: a `red-team-guard` CLI subcommand + a CI leg that re-runs
  it as an independent oracle.

**Neither gates the OSS launch** (the sweep bottom line: "the repo is clean
enough to flip public; no lost idea gates function"). This pack captures them so
they stop being homeless, and the operator can land at leisure.

## Scope (in)

### Sub-task 27-A — `red-team-guard` CLI subcommand (`espalier/cli.py`)
`espalier/red_team_guard.py` exposes `guard_findings(findings, repros, *, root,
min_finders, timeout)` and `format_report(result)` but nothing wires them to the
CLI — by design, so the stdlib module carries no `print`/`main()` and stays out
of the prints-scanner's way (bp-00-06 §8 flags this as a design-rationale
assertion; the CLI layer, `espalier/cli.py`, prints freely and is exempt, so the
subcommand belongs there). The artifacts the guard reads are the tracked-able
`cc/red_team_findings.json` (a FINDING_SCHEMA list) + `cc/red_team_repros.json`
(the repros), per `docs/CONVENTIONS.md` (~L555). An honest null — no artifact, or
zero blockers — PASSES; the guard already fails CLOSED on a non-list findings
payload (`red_team_guard.guard_findings` L239-254).

**Fix (add a new command handler — model it on `cmd_provenance`, which uses the
same `_resolve_repo_arg` + stderr + exit-2 idiom, `espalier/cli.py` L2858-2873):**

```python
def cmd_red_team_guard(args: argparse.Namespace) -> int:
    """Re-execute a committed red-team's blocker repros as an INDEPENDENT oracle.

    Reads cc/red_team_findings.json + cc/red_team_repros.json. Exit 0 = an
    honest null (no artifact / no claimed blockers) OR every claimed blocker
    reproduced its specific failure signature. Exit 2 = any unverified blocker,
    or an unreadable/malformed payload (fail closed).
    """
    from espalier.red_team_guard import format_report, guard_findings
    repo_root = _resolve_repo_arg(args.repo)
    if repo_root is None:
        return 2
    findings_path = repo_root / "cc" / "red_team_findings.json"
    repros_path = repo_root / "cc" / "red_team_repros.json"
    if not findings_path.exists():
        print("red_team_guard: no cc/red_team_findings.json -- nothing to gate (honest null).")
        return 0
    try:
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
        repros = (
            json.loads(repros_path.read_text(encoding="utf-8"))
            if repros_path.exists() else []
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(f"red_team_guard: cannot read artifacts ({exc}) -- failing closed", file=sys.stderr)
        return 2
    result = guard_findings(findings, repros, root=repo_root)
    print(format_report(result), file=sys.stdout if result.passed else sys.stderr)
    return 0 if result.passed else 2
```

**Fix (register the subparser — model on the `worktree-plan` block, which is
`_add_repo_arg`-only with no `--config`, `espalier/cli.py` L4655-4658):**

```python
    p_rtg = sub.add_parser(
        "red-team-guard",
        help="re-execute a committed red-team's blocker repros (independent oracle)",
        description="Read cc/red_team_findings.json + cc/red_team_repros.json and "
                    "re-run each CLAIMED blocker's repro. Exit 0 = every claimed "
                    "blocker reproduced its signature (or an honest null); "
                    "exit 2 = an unverified blocker or a malformed payload.",
    )
    _add_repo_arg(p_rtg, optional=True)
    p_rtg.set_defaults(func=cmd_red_team_guard)
```

`json` and `sys` are already imported at the top of `espalier/cli.py` (L6, L9);
`_resolve_repo_arg` is defined at L381. Adding a CLI subcommand does **not** touch
the `.claude/commands/` slash-command count (`EXPECTED_COMMAND_COUNT`) — that pin
governs slash commands, not `espalier` CLI subparsers; there is no CLI
subcommand-count contract (only per-command existence tests, `tests/test_cli.py`
L579+).

**Earn the red:** in `tests/test_cli.py` (new `TestRedTeamGuard`), build a tmp
repo with `cc/red_team_findings.json` = one `blocks_release` finding whose id has
**no** matching repro → assert `cmd_red_team_guard` returns **2** (RED:
unverified blocker). Then add a `cc/red_team_repros.json` entry with a real
`argv` that fails and emits a specific `match` → assert it returns **0** (GREEN).
Assert the no-file case returns **0** (honest null). Assert a truncated
findings file returns **2** (fail-closed).

### Sub-task 27-B — CI leg for `red-team-guard` (`.github/workflows/test.yml`)
The guard is only a backstop if it runs in an independent oracle. When a
convergence pass commits the `cc/red_team_*.json` pair alongside a change, a CI
step re-verifies each claimed blocker on independent hardware. When no artifacts
are committed (the usual clean-checkout state), the step is a no-op PASS by
27-A's honest-null branch — a modest but real backstop (called out honestly in
Scope (out)).

**Fix (add a step to the full-suite job, after the "Self-host check" step at
`.github/workflows/test.yml` L98-104):**

```yaml
      - name: Red-team guard (re-verify committed blocker repros)
        run: python -m espalier red-team-guard .
```

**⚠ Execution note:** `.github/workflows/` is a `write_guard`-protected zone on
the self-host repo (blocked regardless of plan). Editing `test.yml` requires
launching with `ESPALIER_MAINTENANCE_MODE=1 claude` in the parent shell. The
workflow is also provenance-scanned (a public shipping surface) — the step MUST
NOT contain a `TP-NNN` literal.

**Earn the red:** commit a `cc/red_team_findings.json` fixture with an unverified
blocker on a scratch branch and confirm the new CI leg (or a local
`python -m espalier red-team-guard .`) FAILS (exit 2); remove/repair the artifact
→ PASS (exit 0). Locally: `./actionlint -shellcheck= -pyflakes= -color` (the
`workflow-lint` job, `test.yml` L240) stays green after the edit.

### Sub-task 9-A — pack-doc declaration-consistency linter (`scripts/lint_pack_doc.py`)
A NEW standalone maintainer tool that validates a pack *document's* internal
consistency — distinct from the codebase scope-check TP-318 shipped and from the
two partial overlaps (`scripts/check_pack_landing.py` = Landing-stanza only;
`tools/cc/pack_artifact_checklist.md` = manual LLM checklist). It reuses the
already-shipped parsers in `espalier/pack_manifest.py` (`parse_pack` L94,
`parse_scope_in` L116, `_section_body` L330, `_looks_like_path` L347) — scripts
may import `espalier` (`scripts/build_release_archive.py`,
`scripts/final_release_matrix.py` already do). It checks exactly three defects:

1. **Uncovered Files-touched path** — a backticked path in `## Files touched`
   that appears in **no** `## Affected symbols` bullet (the path portion of a
   `path::symbol` token, or an `### Added-paths` bare path) and no
   `## Affected literals`. (`parse_affected_symbols` L219 discards the path — it
   stores only the symbol after `::`, L259-261 — so the linter extracts paths
   itself from the section body via `_section_body` + the backtick regex.)
2. **Rename without `### Renamed`** — the pack body mentions `git mv` (or
   `rename`/`renamed`) but has no `### Renamed` subsection under
   `## Affected symbols`.
3. **Malformed Added-paths bullet** — a `- ` bullet under `### Added-paths` with
   **no** backticked token — the exact bullet `parse_affected_symbols` silently
   `continue`s past (L252-253), so a declared new path vanishes from the manifest
   unnoticed.

**Fix (new file — representative core; model the CLI shell + advisory-exit idiom
on `scripts/check_pack_landing.py`, which is stdlib + `--strict` exit-1):**

```python
#!/usr/bin/env python3
"""Declaration-consistency lint for a TP-* pack document (advisory).

Validates a pack doc's internal cross-references -- NOT the codebase (that is
`espalier scope-check`) and NOT the Landing stanza (that is
scripts/check_pack_landing.py). Advisory: reports and exits 0; --strict exits 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from espalier.pack_manifest import _looks_like_path, _section_body, parse_pack


def _backticked_paths(section: str | None) -> set[str]:
    if not section:
        return set()
    return {
        t.split("::", 1)[0].strip()
        for t in re.findall(r"`([^`]+)`", section)
        if _looks_like_path(t.split("::", 1)[0].strip())
    }


def lint_pack_doc(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[str] = []

    affected = _section_body(text, r"(?m)^#{2,3}\s+(?:\d+\.\s+)?Affected symbols", r"^## ")
    literals = _section_body(text, r"(?m)^#{2,3}\s+(?:\d+\.\s+)?Affected literals", r"^## ")
    files = _section_body(text, r"(?m)^#{2,3}\s+(?:\d+\.\s+)?Files touched", r"^## ")
    covered = _backticked_paths(affected) | _backticked_paths(literals)

    for p in sorted(_backticked_paths(files) - covered):
        findings.append(f"Files-touched path not covered by any Affected symbol/literal: {p}")

    if re.search(r"\bgit mv\b|\brename[d]?\b", text, re.IGNORECASE) and (
        affected is None or not re.search(r"(?m)^###[ \t]+Renamed\b", affected)
    ):
        findings.append("pack mentions a rename but declares no '### Renamed' subsection")

    if affected:
        added = re.search(r"(?m)^###[ \t]+Added.*$", affected)
        if added:
            body = affected[added.end():]
            body = body[: (re.search(r"(?m)^###[ \t]", body) or re.match(r"", body)).start()] \
                if re.search(r"(?m)^###[ \t]", body) else body
            for bullet in re.findall(r"(?m)^- .+$", body):
                if "`" not in bullet:
                    findings.append(f"Added-paths bullet has no backticked path (silently dropped): {bullet.strip()!r}")
    return findings


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv
    paths = [Path(a) for a in argv if not a.startswith("-")]
    if not paths:
        print("usage: lint_pack_doc.py <pack.md> [<pack.md> ...] [--strict]")
        return 0
    any_findings = False
    for p in paths:
        findings = lint_pack_doc(p)
        parse_pack(p)  # cheap parse-integrity check (never raises on bad UTF-8)
        if findings:
            any_findings = True
            print(f"{p.name}:")
            for f in findings:
                print(f"  - {f}")
        else:
            print(f"{p.name}: OK (no declaration inconsistencies)")
    return 1 if (any_findings and strict) else 0


if __name__ == "__main__":
    sys.exit(main())
```

(The Added-paths body-slice above is a CLAIM — earn it red before trusting the
slice arithmetic; a `_section_body`-style two-anchor extraction for the
subsection body is the cleaner implementation and may replace the inline slice.)

**Earn the red:** add `tests/test_lint_pack_doc.py` with a crafted BAD pack
fixture that carries all three defects (a Files-touched path absent from
Affected symbols; a `git mv` line with no `### Renamed`; an `### Added-paths`
bullet with no backticks) → assert `lint_pack_doc` returns exactly those three
findings, and `main([...,"--strict"])` returns **1**. A CLEAN fixture → **0**
findings, `main` returns **0**. Prove the detector discriminates: delete one
check → its fixture assertion REDs.

## Scope (out)
- **Integration B (a standing "commit the `cc/red_team_*.json` pair" CI
  convention).** Subsumed/moot: the unattended driver already attests the
  red-team RAN via the gitignored `cc/_pack_receipt.json`
  (`docs/CONVENTIONS.md` ~L560), so a *missing* receipt halts at the driver.
  bp-00-06 §8 also corrected the original B blocker (it cited the gitignored
  `finding_ledger.jsonl`, but the guard reads the *un-ignored*
  `red_team_findings/repros.json` pair). C's CLI + no-op-safe CI leg is the whole
  remaining value; B is a documentation decision, not code — dropped.
- **Making either tool a hard CI merge gate.** `task-packs/` was gitignored when this was written
  (absent in a clean CI checkout); since 2026-09-21 the active packs ship, so this
  scope-out's premise no longer holds and the call is open again. As written: the pack-doc linter **cannot** be a merge
  gate — identical to why `scripts/check_pack_landing.py` is advisory-only. It
  stays a local maintainer tool. The red-team CI leg is a re-verifier that
  no-ops when no artifact is committed (its honest-null branch), NOT a
  find-me-blockers gate — an honest limitation, stated so the green is not
  over-read.
- **Folding the linter into `/scope-check` or `/implement-pack` pre-flight.**
  Ship the standalone tool first; wiring it into a command surface (with the
  attendant count-pin / mirror obligations) is a separate integration concern.
- **The other seven `pack_artifact_checklist.md` items** (line-number accuracy,
  effort calibration, pass-criteria realism, …). Those require judgement or
  tree-wide line resolution; the linter deliberately covers only the three
  *declaration* defects that are cheaply and unambiguously mechanical. The manual
  LLM checklist remains the home for the rest.
- **A `main()`/CLI inside `espalier/red_team_guard.py` itself.** Intentionally
  NOT added — the stdlib module stays print-free (design rationale above); the
  CLI lives in `espalier/cli.py`.

## Affected symbols

### Added-paths
- `scripts/lint_pack_doc.py::lint_pack_doc` — the three-check pack-doc linter (9-A, NET-NEW)
- `scripts/lint_pack_doc.py::main` — advisory CLI entrypoint, `--strict` exits 1 (9-A, NET-NEW)
- `scripts/lint_pack_doc.py::_backticked_paths` — path-token extraction helper (9-A, NET-NEW)
- `espalier/cli.py::cmd_red_team_guard` — new subcommand handler (27-A, NET-NEW symbol in an existing file)
- `tests/test_lint_pack_doc.py::TestLintPackDoc` — linter fixture assertions (9-A, NET-NEW)
- `tests/test_cli.py::TestRedTeamGuard` — CLI exit-code + honest-null + fail-closed assertions (27-A, NET-NEW)

### Changed-semantics
- `espalier/cli.py::build_parser` — register the `red-team-guard` subparser (27-A; symbol EXISTS at HEAD)
- `.github/workflows/test.yml` — add the "Red-team guard" CI step to the full-suite job (27-B; path-level, no Python symbol)

### Referenced-unchanged (grounding anchors — cited, not touched)
- `espalier/red_team_guard.py::guard_findings` / `::format_report` (reused by 27-A; EXIST at HEAD)
- `espalier/pack_manifest.py::parse_pack` / `::_section_body` / `::_looks_like_path` / `::parse_scope_in` (reused by 9-A; EXIST at HEAD)
- `espalier/cli.py::_resolve_repo_arg` (reused by 27-A; EXISTS at HEAD, L381)

## Pass criteria
- **Earn-red 27-A:** `TestRedTeamGuard` REDs when a `blocks_release` finding has
  no matching repro (`cmd_red_team_guard` returns 2); GREEN (returns 0) with a
  matching failing+signature-matched repro; returns 0 on the no-artifact honest
  null; returns 2 on a truncated findings file (fail-closed).
- **Earn-red 9-A:** the BAD-pack fixture yields exactly the three declared
  findings and `main(--strict)` returns 1; the CLEAN fixture yields 0 and
  `main` returns 0; deleting any one check REDs its fixture assertion.
- **27-B:** the `red-team-guard` step is present in `.github/workflows/test.yml`;
  `actionlint` (the `workflow-lint` job) stays green; a committed
  unverified-blocker fixture fails the leg, and its removal passes.
- **Surface hygiene:** `tests/test_lint_pack_doc.py` (and, if a new file,
  `tests/test_cli.py` additions) are classified in `tests/conftest.py`
  `_MARKER_RULES` (or carry the `# pytest-marker:` opt-out) so
  `test_marker_taxonomy` stays green; new test files are `git add`-ed BEFORE
  gating (git-ls-files contracts false-green on untracked files).
- **Provenance:** NO `TP-NNN` literal in any shipped surface this pack touches —
  `espalier/cli.py`, `scripts/lint_pack_doc.py`, and `.github/workflows/test.yml`
  are all provenance-scanned (only `task-packs/`, this file, is exempt).
- **Full gate:** `pytest -q` green; `ruff check .` clean; `python3 -m espalier
  audit .` 0/0. No `.claude/{agents,commands,skills}` edits → no
  `sync_claude_mirrors.py`; no `tools/cc/*.py` edits → no `sync_vendor_cc.py`
  (both mirror syncs are N/A for this pack).

## Files touched
- **New:** `scripts/lint_pack_doc.py` (9-A); `tests/test_lint_pack_doc.py` (9-A).
- **Modified:** `espalier/cli.py` (`cmd_red_team_guard` + `build_parser`
  registration, 27-A); `.github/workflows/test.yml` (CI leg, 27-B —
  MAINTENANCE_MODE required); `tests/test_cli.py` (`TestRedTeamGuard`, 27-A);
  `tests/conftest.py` (`_MARKER_RULES` classification for the new test file(s)).
- **Mirrors (regenerated):** NONE — this pack touches neither `.claude/` nor
  `tools/cc/`, so no mirror sync runs.
- **Unmodified-on-purpose:** `espalier/red_team_guard.py` (reused as-is; no
  `main()` added — CLI lives in `cli.py` by design); `scripts/check_pack_landing.py`
  and `tools/cc/pack_artifact_checklist.md` (adjacent but deliberately NOT merged
  — different scopes); `espalier/pack_manifest.py` (parsers reused, not changed).

## Sub-task ordering
1. **27-A** CLI subcommand — smallest, well-patterned change: add
   `cmd_red_team_guard` + register the subparser → add `TestRedTeamGuard` →
   observe RED (no-repro blocker) → GREEN. Checkpoint: `pytest -q
   tests/test_cli.py` + `python3 -m espalier red-team-guard .` (honest-null PASS).
2. **9-A** linter — new `scripts/lint_pack_doc.py` + `tests/test_lint_pack_doc.py`;
   classify the new test file in `conftest.py::_MARKER_RULES`; earn the three-defect
   red on the BAD fixture. Checkpoint: `pytest -q tests/test_lint_pack_doc.py` +
   run the linter against a real recent pack.
3. **27-B** CI leg — (launch with `ESPALIER_MAINTENANCE_MODE=1`) add the step to
   `test.yml`; verify no `TP-NNN` literal. Checkpoint: `./actionlint -shellcheck=
   -pyflakes= -color` green.
4. **final** — `git add` new test files, then full `pytest -q` + `ruff check .` +
   `python3 -m espalier audit .` + provenance census; stamp Landing.

## Estimated effort
- 27-A ~30m · 9-A ~1.5h (new file + fixtures + earn-red) · 27-B ~20m
  (incl. MAINTENANCE_MODE launch) · verify+land ~25m.
  **Total ≈ 2.5–3 h.**

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) 27-A `cmd_red_team_guard` returns 2 on a
  no-repro `blocks_release` finding (RED) and 0 with a matching
  failing+signature repro (GREEN), 0 on the no-artifact null, 2 on a truncated
  payload; 9-A the BAD-pack fixture yields exactly three declaration findings and
  `main(--strict)` returns 1 (deleting any check REDs its assertion), CLEAN
  fixture returns 0.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep
  (`reports/lost-idea-sweep-2026-07-26.md` rows #9 + #27). Operator disposition:
  DEFER — both are self-host maintainer tooling; neither gates the OSS flip. #9
  was homeless because TP-318 deferred it to the reused number "TP-319"; #27's
  Integration B is dropped as subsumed by the driver-receipt model, leaving only
  the CLI + no-op-safe CI leg.
