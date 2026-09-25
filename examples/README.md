# Examples

This folder is a **reference shelf** — browse it to see what the harness
produces and how it holds itself to its own standards. Nothing here is
deployed into your repo; it's here to look at and copy from. Three things are
worth your time, in order:

| Look at | To see | Start here |
|---|---|---|
| **Deploy templates** | What `espalier init` writes into *your* repo — preview it before you run anything | [`CLAUDE.template.md`](CLAUDE.template.md), [`ESPALIER_MEMORY.template.md`](ESPALIER_MEMORY.template.md) |
| **Dogfooding config** | How Espalier-Harness governs its *own* repo — the full agent / command / skill roster in real use | [`dogfooding/`](dogfooding/) |
| **Golden tests** | The make-it-prove-it test discipline that makes the harness trustworthy — four runnable exemplars you can copy into any repo | [`golden/`](golden/) |

The rest of this page is the option reference for each piece.

## espalier.toml

Optional configuration file. Place in your repo root to customize harness
behavior — profile overrides, protected paths, parallel work settings.

See `espalier.toml` in this directory for the full option reference.

## Deploy templates

`espalier init` writes a `CLAUDE.md` and `ESPALIER_MEMORY.md` skeleton into the
target repo. The canonical, rendered output is committed alongside this
README so OSS visitors can preview exactly what `init` produces:

- [`CLAUDE.template.md`](CLAUDE.template.md) — the harness governance
  config skeleton (~95 lines): project context, hook table, Slash
  Commands / Skills / Agents tables, Plan Guard, architecture rules,
  build commands.
- [`ESPALIER_MEMORY.template.md`](ESPALIER_MEMORY.template.md) — the project-memory
  skeleton (~30 lines): repo context, decisions table (empty), patterns
  table (empty), session log with pruning policy.

These differ deliberately from the espalier-harness repo's own root
`CLAUDE.md` and `ESPALIER_MEMORY.md`, which are the harness's working documents
for self-hosting (richer hook tables, full agent roster, maintenance
mode docs, session log entries). The deploy templates are a clean
starting point for *user* repos using espalier as a tool.

To preview the templates without going through `init`:

```bash
espalier render-template claude   # prints CLAUDE.md template to stdout
espalier render-template memory   # prints ESPALIER_MEMORY.md template to stdout
```

The snapshots in this directory are pinned by
`tests/test_documented_claims.py::TestDeployTemplateSnapshots` — if the
generators in `espalier/cli.py` (`_build_claude_md`, `_build_memory_md`)
drift, the test fails and the snapshots must be regenerated:

```bash
python3 -m espalier.cli render-template claude > examples/CLAUDE.template.md
python3 -m espalier.cli render-template memory > examples/ESPALIER_MEMORY.template.md
```

## Quick Start

Espalier installs by **fusion** — one command builds a *new* repo that is your
project + the harness overlaid at root, leaving your original untouched. A
packaged `pipx` / PyPI channel is planned but is **not yet** the install path
(the distribution name is not yet published), so fuse from a source checkout:

> **Interpreter note.** The commands below spell `python`. A stock macOS ships only
> `python3` (and it is 3.9; Espalier requires 3.10+), while many Windows installs ship
> only `python`. Use whichever both resolves AND reports 3.10+ (`<name> --version`);
> `espalier doctor .` checks this for you.

```bash
git clone https://github.com/Mike-Byrne-AI/espalier-harness.git
cd espalier-harness
python -m espalier fuse /path/to/your/repo --out /path/to/your-repo-governed
```

**Prefer to govern your existing repo in place?** Run `init` inside it instead —
no new directory. Note the trade-off: in-place `init` deploys the governance
config + hooks but assumes the engine is available separately (your source
checkout, or pip once that channel ships), whereas **fusion** vendors the full
engine + reusable docs into the new repo. So in place you install the engine
from the checkout first:

```bash
cd espalier-harness
python -m venv .venv
. .venv/bin/activate          # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e .    # make the engine importable
cd /path/to/your/repo
python -m espalier init .                 # deploy the harness in place
python -m espalier doctor .               # verify everything is wired
python -m espalier audit .                # run the surface gate
```

See the project README for the full workflow.
