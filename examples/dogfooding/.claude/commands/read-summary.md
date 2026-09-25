Dump the live working-summary doc for this repo — `cc/_working_summary.md`, the
always-current "pick up where we left off" picture (an exact mirror of Claude
Code's post-compaction summary plus the espalier resume index), rewritten at
every session boundary so it is never stale.

```bash
python tools/cc/read_summary.py "$@"
```

With no arguments it prints the live doc — the same picture Claude already has on
tap; this command dumps it to the transcript so the operator can inspect it. If
it reports "no cc/_working_summary.md yet," the session hasn't compacted and no
handoff has run yet.

- `--list` — enumerate the per-session archive captures.
- `--session <id>` — print a specific archived session's capture(s).
- `--all` / `--index N` — browse an individual transcript's compaction legs.
- `--path <file.jsonl>` — read a raw transcript verbatim (escape hatch).

> Cross-platform note: command bodies show `python` for brevity; try `python3`
> first, fall back to `python` (per the repo's invocation rule).
