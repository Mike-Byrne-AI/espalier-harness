# Forward Ledger

_This repository's forward-work tracker: what is still wrong or still to do, grouped
into classes by the unit of work that fixes it, each live row carrying a probe that
re-derives its claim or a declared reason why none can. `espalier init` seeded it and
filed the onboarding rows below; every row after those is yours. Edit it through the
verbs in `tools/cc/`, never by hand -- they keep the rows, the index and the probes
in step, and refuse a write that would leave them disagreeing:_

- `python tools/cc/ledger_row.py class C4 --title "..." --population HYGIENE --audience MAINTAINER` opens a class;
- `python tools/cc/ledger_row.py file <ID> --section C4 --anchor <site> --text-file <row.md> --severity minor --subject <file> --probe-cmd "..." --open-value <value>` files a row, and drives its probe first (`--after <ID>` places it after an existing row; `--why-not "<reason>"` replaces the probe for a row nothing on disk can measure);
- `python tools/cc/ledger_row.py strike <ID> --text-file <closing.md>` closes a row, keeping its prior text;
- `python tools/cc/check_ledger_probes.py` re-derives every probed row (`/preflight` runs it);
- `python tools/cc/generate_ledger_regions.py --print` prints every count, derived from the rows; the file stores none, so two people filing at once never both rewrite a total, and `--check` fails if one is written back in.

Each writing verb holds a lock file beside the ledger while it works, so run them one at a
time: a second one refuses rather than racing the first.

**No completeness gate ships yet.** Nothing fails a build when a live row carries
neither a probe nor a declared reason for having none; filing through `ledger_row.py`
is what keeps every row honest, because it requires one or the other.

**Counts are derived, never stored here:** `python tools/cc/generate_ledger_regions.py --print` prints the live total, its split by population and by audience (counted apart on purpose, never as one number), and each class's live and closed members.

## §2 — Open fixes, by unit of work

**The three populations are counted apart, never as one number** -- a defect in the
code, a document or registry out of step, and a thing only a person can do are three
different kinds of "not done yet".

| population | what it means |
|---|---|
| LOGIC_BUG | code behaves wrongly |
| HYGIENE | docs / comments / registries / test scaffolding |
| OPERATOR_ACTION | no code fix exists: a person has to do it |

| audience |
|---|
| **ADOPTER** — a person who uses what this repository ships |
| MAINTAINER — you, and whoever works on this repository with you |
| OPERATOR — whoever runs what this repository ships |

### Class index

| § | class | population | audience | effort |
|---|---|---|---|---|
| [§C1](#c1--initialise-finish-what-init-started) | Initialise: finish what init started | OPERATOR_ACTION | MAINTAINER | — |
| [§C2](#c2--test-confirm-the-harness-runs-this-repositorys-own-checks) | Test: confirm the harness runs this repository's own checks | OPERATOR_ACTION | MAINTAINER | — |
| [§C3](#c3--adapt-fit-the-harness-to-this-repository) | Adapt: fit the harness to this repository | OPERATOR_ACTION | MAINTAINER | — |

### §C1 — Initialise: finish what init started

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C2 — Test: confirm the harness runs this repository's own checks

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C3 — Adapt: fit the harness to this repository

**Members**

| id | site | what | sev |
|---|---|---|---|

## §6 — Dropped / do-not-rediscover

**A finding a review has already declined, with the reason it stays declined.** The
review workflows read this section before they report, so a row here stops the same
finding being paid for twice; deleting one invites the re-find it prevents.

| id | what | why it stays declined |
|---|---|---|

## Appendix B — id index

| id | § | site |
|---|---|---|
