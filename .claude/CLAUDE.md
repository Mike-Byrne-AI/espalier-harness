# .claude/

**Doing:** Source of truth for the harness's Claude Code surface — `agents/`, `commands/`, and `skills/` are hand-edited HERE, never in a mirror.

**Don't break:**
- After editing `agents/`, `commands/`, or `skills/`, run `python3 scripts/sync_claude_mirrors.py` — it regenerates the byte-parity-pinned mirrors (`espalier/assets/claude/`, `examples/dogfooding/.claude/`). Never hand-edit a mirror. Only those three subdirectories are mirrored — this file and `settings.json` are not. (These are two of nine mirror rows; the census lives in `espalier/mirror_registry.py`.)
- Adding/removing a command, agent, or skill fans out to the `EXPECTED_*` counts, the root `CLAUDE.md` tables (`/smoke` greps those rows + the command count), and `cc/COMMANDS.md`. See `espalier/surface_impact.py` for the obligation list.
- `settings.json` is gitignored + guard-protected — a kill-switch there is denied live and by CI.
- A dispatch scripted in any body here is pre-approved and not optional — [root `CLAUDE.md`](../CLAUDE.md) Core Rule 11 is its sole home.

**Read first:** [`memory/asset-mirroring.md`](../memory/asset-mirroring.md)

_Self-host governance; not deployed to adopters._
