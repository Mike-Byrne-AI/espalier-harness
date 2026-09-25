Session resume and degraded-state recovery guidance.

The SessionStart hook auto-runs the equivalent of this command at every
session begin: the context block carries a one-line `/recall` pointer to
whichever footgun/failure-mode catalogs **this repo actually has**, a MEMORY
digest once `ESPALIER_MEMORY.md` carries dated Session Log rows, and the
standing-principles index on the self-host repo — plus orientation
instructions. Each section is gated on its own artifact, so the banner
describes your tree rather than the harness's. And Claude
OPENS with a provisional first-thoughts read of the handoff on first
response (it no longer full-reads ESPALIER_MEMORY.md or the SHARP_EDGES TOC). This
slash command is the manual re-trigger — useful mid-session (a long
discussion drifts), after PostCompact, or to recover from a DEGRADED
surface state where the auto-orient may have been skipped.

1. Run the session resume engine (use `--mode recover` on a DEGRADED surface):
```bash
python tools/cc/session_resume.py --mode normal
```
This is a pure, idempotent reorient: it assesses the surface and renders the
report. It does NOT start a new blueprint node when one already exists — the
SessionStart hook now advances the chain on a new session (source
`startup`/`clear`), so running this mid-session won't fragment the chain. It
bootstraps a node only when none exists at all. If the surface is DEGRADED, it
prints recovery information and safe next actions.

2. Re-orient from whatever continuity the banner actually injected — the
   blueprint always, plus a GOAL section and a MEMORY digest **if this repo
   keeps them** (the goal snapshot is local and gitignored; the digest renders
   once `ESPALIER_MEMORY.md` has dated Session Log rows). Pull full MEMORY
   rows or a relevant footgun section on demand with `/recall <topic>` — do NOT
   full-read ESPALIER_MEMORY.md or the SHARP_EDGES / FAILURE_MODES catalogs.
3. Do NOT re-litigate prior blueprint decisions unless new evidence appears.
4. Open with a brief, provisional first-thoughts read of the continuity — what
   stands out, where you'd pick up — and end with a proposed next move +
   "confirm or redirect?". (Step 1's `session_resume` already printed the
   structured REPO/SURFACE/LAST/BRANCH/STATUS/NEXT facts; don't re-emit them as
   a form — layer your read on top.)
