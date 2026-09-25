# Incident, 2026-09-17 — a fixture row executed on the real shell wiped part of the host

**Status:** closed, recovered
**Author:** self-host session, with the operator
**Blast radius:** the developer machine's `/Applications`, its Homebrew prefix, and some admin-writable content under `/Library`. The repository, its history, all committed and gitignored state, and the operator's home directory were untouched.

This record is kept because the harness tests itself with populations of real
shell commands, and the failure was in how one of those populations was
driven, not in the guard. It is a maintainer discipline note, written in full
so the next session inherits the whole picture.

---

## How it started

The session was working the post-Windows-walk ledger tail. The last major had
landed (DEF-827); the DEF-829 read-twin lane had landed and was struck but
uncommitted (38 files, green tier). The operator asked to file the new
class-exploration row and start the next lane.

DEF-835 was filed cleanly (the caller-following decode-guard gap; probe added,
ratchet green). The next lane opened was DEF-830 — the shell read-loop carrier,
a compound statement that binds a loop variable to an enumerator and removes
each line in its body, which the friction guard nudges rather than walls.

## What we were doing when it happened

To size the DEF-830 class, a scratch driver was written to run each loop-carrier
spelling on the real shell against a fresh throwaway directory and record what
each one removed, then ask the guard for its answer. Driving a *relative*
spelling on a throwaway is a sanctioned method: a real shell is the only honest
oracle for what the guard should refuse, and the throwaway bounds the blast
radius.

The driver's row set was then extended with variable-glob spellings. One of
those rows carried a variable that the driver never bound. That is the whole
defect: a fixture whose point is an unset variable exists *because* an unset
variable is dangerous, and such a row must be asked of the guard's classifier
in memory, never executed on a real shell.

## The mechanism

When the driver executed that row, the shell expanded the unbound variable to
nothing and the adjacent glob to the entries of the filesystem root. The
recursive force-delete then ran, as the operator's own admin user, against the
root's children in locale order. The driver had wrapped each execution in a
20-second subprocess timeout; that timeout is what stopped it. A timeout is not
a safety net — 20 seconds of deletion as an admin user is most of the
admin-writable content on the volume.

The delete walked the root alphabetically: `Applications`, then `bin`, `cores`,
`dev`, `etc`, `home`, `Library`, `opt`, `private`. The kill landed while it was
inside `/opt/homebrew` or on entering `/private`. Everything sorted after that
point was never reached.

## What was damaged

Established by a volume-wide scan for directories whose entries changed inside
the incident minute, cross-checked against ownership and the surviving remnants:

- **`/Applications`** — every user-installed app removed. Only the root-owned
  Apple apps and the Safari symlink remained. VS Code and the Claude Code CLI
  were among the losses; the running VS Code stayed alive only because macOS
  keeps a launched app's open files.
- **`/opt/homebrew`** — the prefix top level and most of the Cellar removed.
  With it went Python 3.14 (which held the harness toolchain: the editable
  espalier install, pytest, xdist, mypy, ruff and the rest), and node, uv,
  gh, shellcheck, actionlint, scorecard. After this, `python3` resolved to
  Apple's 3.9 and `git` to Apple's 2.39; `brew` and `claude` were off the PATH.
- **`/Library`** — `Receipts` (the Installer's visible history; the real
  package-receipt database was untouched), the `CrashReporter` consent record,
  and the admin-writable music content (`Application Support/{Logic,GarageBand}`,
  `Audio/{Apple Loops,Impulse Responses}`) were emptied. `Application Support/Logi`
  lost entries. `LaunchAgents`, `LaunchDaemons` and `Preferences/SystemConfiguration`
  showed a same-minute timestamp change but are root-owned and looked complete;
  a non-root process cannot remove their entries, so the change was most likely
  a vendor root helper reacting to its app vanishing, or routine system writes.

## What was NOT damaged

- **The repository** — `git fsck` clean, HEAD unchanged, the uncommitted
  DEF-829 lane intact at its exact diffstat, no stash, the gitignored ledger and
  `.espalier`/`cc` state present. No execution plan for DEF-830 had been created,
  so nothing was half-landed.
- **The operator's home directory in full** — Claude's machine-local auto-memory
  and the transcript archive, VS Code settings and extensions, the uv-managed
  Python 3.10/3.13 shims and pwsh under `~/.local`, the session scratchpad under
  `/private/tmp`.
- **`/System`, `/usr`, `/Users/Shared`, external volumes** — all sorted after the
  kill point or protected by SIP.

## How it was found and stopped

The driver's own 20-second timeout raised `subprocess.TimeoutExpired` and ended
the run; the traceback named the offending row. The operator's message arrived
in the same window ("we hit the classifier"), and the assessment established
what had actually happened. Damage was mapped read-only, worst-first: the
process table (no delete still running), then the home directory, the repo, and
outward across the volume by directory-mtime in the incident minute. An early
overstatement — "Homebrew intact" read off a truncated four-entry listing — was
caught and corrected: a Homebrew prefix has many more top-level entries, and
most were gone.

## Recovery

- The Claude Code CLI was reinstalled from the documented native installer
  (downloaded to a file and read first, per the guard's fetch-execute nudge),
  restoring the session's own tooling.
- VS Code was reinstalled before the running copy could be quit.
- The damaged Homebrew prefix was moved aside (remnants preserved), Homebrew
  reinstalled, then the eight formulae, the repo's dev extras and espalier
  editable into Python 3.14, and the work apps.
- The full proof tier was run on the rebuilt toolchain and matched the
  pre-incident counts exactly (14,524 parallel, 1,468 serial, proof PASS),
  proving the environment restored the repository to a known-green state.
- No Time Machine destination was configured; setting one up is recommended.
- A recovery runbook and an unattended install script were written to
  `~/Developer/recovery-2026-09-17/`.

## The rules that came out of it

1. **A real-shell drive runs only spellings whose every operand is relative to
   the throwaway and whose every variable is bound in the same command.** A row
   whose point is an unbound or absolute operand is asked of the guard's
   classifier in memory and never executed. (Auto-memory:
   `a-real-shell-drive-never-runs-a-row-with-an-unbound-variable`.)
2. **Before executing any fixture text, read it for `$`, `~`, or a leading `/`
   on an operand, and for a glob beside a variable.** One such token and the row
   is classifier-only.
3. **A subprocess timeout is not a blast-radius bound.** It cannot be relied on
   to stop a delete.
4. **Past the one headline spelling per shell, the guard's answer for every row
   comes from a test class run by name, not from execution** — the same
   discipline the classifier-trip note already required for a different reason.

## Why this is a self-host record, not an adopter footgun

Adopters never drive the guard's fixture population; that work is the harness
testing itself. The defect lived entirely in maintainer test-driving method,
which is why the remedy is a discipline note and a memory entry rather than a
guard change. The guard behaved correctly throughout: it had already classified
the loop-carrier spelling as a soft-tier nudge, which is the DEF-830 finding the
lane set out to record.
