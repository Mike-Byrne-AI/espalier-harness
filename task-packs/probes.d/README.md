# The forward ledger's probes

One file per probe: `<id>.json`, named for the ledger row it re-derives, holding one
object whose `id` is the file's name. `tools/cc/check_ledger_probes.py` runs them;
`tools/cc/ledger_row.py` writes them (`file`, `strike`, `repin`); readers take the
roster through `tools/cc/_record_fragments.py::probe_roster`, which reads this
directory beside a `LEDGER_PROBES.json` where a tree still has one (an adopter's does).
Until the fold of 2026-10-14 (TP-479a Wave C) the probes lived in
`task-packs/LEDGER_PROBES.json`; its prose follows, unchanged.

## What a probe is

Mechanical probes for FORWARD_LEDGER.md rows. Each re-derives its row's claim; when a probe stops printing open_value the row is a STRIKE CANDIDATE. Run tools/cc/check_ledger_probes.py. A missing subject is UNRESOLVED, never STRIKE -- a wrong strike costs a re-discovery, and until 2026-09-21 the ledger was gitignored, so it was invisible to `git status` as well. (It was never unrecoverable, which this line once claimed: `scripts/record_snapshot.py` carries the file on the orphan `record` branch, so `git show record:task-packs/FORWARD_LEDGER.md` reaches the snapshots from before it was tracked, and `git log -p -- task-packs/FORWARD_LEDGER.md` reaches every committed state since. The three-way verdict is right on its own merits and never needed the stronger claim.) A STRUCK row must also LOSE its probe: the tests gate live-row coverage only, so retired probes accumulated until 14 of 198 aimed at struck rows and made 10 of 11 strike candidates noise -- `scripts/generate_ledger_regions.py` now reports that direction. `row_sha` is the sha256[:12] of the ledger line this probe re-derives: when the row's PROSE is edited and the probe is not, the runner reports STALE_CLAIM. That is a separate axis from the verdict, because a row can be STILL_OPEN and stale at the same time -- DEF-493 was, for five days, and nothing said so. A probe whose COMMAND reads paths beyond its subject -- a local-only folder or an untracked file the public checkout lacks -- declares them in `inputs`, written only by `ledger_row.py` `file` or `repin --inputs` (a hand edit is undriven): a missing member, or a directory that exists and holds nothing, is UNRESOLVED like a missing subject, never a strike (DEF-858, 2026-09-22).

## Retirement

A probe is retired WITH its row. Leaving the ten C2 probes behind made every future run report ten permanent STRIKE_CANDIDATEs -- a runner that cries wolf trains its reader to ignore it, which is worse than no runner.

(The roster's last rebuild before the fold: 2026-09-20 rebuild (third).)
