Quick progress check — harness state in 10 lines. Never starts a new blueprint session.

```bash
python tools/cc/session_resume.py --mode status
```

```bash
git log --oneline -5 2>/dev/null || echo "no git history"
```

Report what you see and what's next.

## `--log [N]` — governance audit tail

Read-only: print the last N (default 20) enforcement-refusal records the
harness logged for this repo today, newest last, with a per-type count for
the whole day above them and the day's pause records (a speed-bump fire, a
Stop-gate block — once-then-continue) counted on a line of their own;
`--all` widens the tail to the pauses (on a busy day that tail is mostly
Stop-gate records; the day-wide by-type line above it still lists every
refusal). The event types and their tiers are
the table under "Governance audit log" in `docs/HOOKS.md` — one enumerator,
pinned to the code, not re-listed here. Reads the records from
`~/.espalier/audit/` (advisory records like `action_justification_missing`
are filtered out, and so are another checkout's records when two share a
basename); no new store. A repo root after `--log` reads that checkout's
tail.

```bash
python tools/cc/session_resume.py --log          # last 20 refusals
python tools/cc/session_resume.py --log 50       # last 50 refusals
python tools/cc/session_resume.py --log 50 --all # last 50 blocks, pauses included
```

## `--explain <path>` — per-path enforcement read-out

Read-only: for a repo-relative `<path>`, report what the path-conditioned hooks
would do and why — is it plan-gated or plan-exempt (and by which rule), in a
write_guard protected zone / an exact protected file / allowlisted-within /
unprotected (naming the matched zone), plus the live maintenance-mode effect and
a one-line net verdict. Pairs with `--log` (what the hooks *did*): `--explain`
shows what they *will* do. Every verdict is derived from the hooks' own
predicates (`_protected_zones` / `plan_guard`), never a re-implementation, so the
read-out cannot drift from enforcement. No mutation; no new store.

```bash
python tools/cc/session_resume.py --explain tools/cc/hooks/write_guard.py
python tools/cc/session_resume.py --explain <path/to/a/source/file.py>
```
