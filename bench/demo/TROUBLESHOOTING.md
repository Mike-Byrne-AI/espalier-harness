# Demo recording: troubleshooting

Predictable failure modes when re-recording the demo. If the recording
isn't behaving as `script.md` describes, the problem is almost always
one of these.

---

## Hooks didn't fire

**Symptom:** Claude Code accepts the prompt and edits `.claude/settings.json`
without producing any block message.

**Diagnosis:**

1. Run `espalier doctor .` from inside the demo target. Expect `pass`.
   If you get `risky` or `fail`, the harness isn't fully installed.

2. Check `.claude/settings.json` exists and has hook wiring:
   ```bash
   python -c "import json; print(list(json.load(open('.claude/settings.json')).get('hooks', {}).keys()))"
   ```
   Expected output: the 10 wired events — `['ConfigChange', 'PostCompact',
   'PostToolUse', 'PostToolUseFailure', 'PreToolUse', 'SessionStart', 'Stop',
   'SubagentStart', 'SubagentStop', 'UserPromptSubmit']` (order may vary). An
   empty dict or far fewer keys means hooks were partially installed or
   stripped — re-run `espalier init .`.

3. Confirm `CLAUDE_PROJECT_DIR` is set inside Claude Code's session.
   Type into Claude Code: `Run: echo $CLAUDE_PROJECT_DIR`. If empty,
   Claude Code wasn't started from the target directory or the
   environment didn't propagate. Quit and re-launch from the target.

**Fix:** Re-run `espalier init .` from the target. It's idempotent;
re-running deploys any missing pieces without overwriting your work.

---

## Block message text differs from `script.md`

**Symptom:** The hook fires but the message reads, e.g., `Write to
protected zone denied: ...` instead of `Write to protected harness zone
blocked: ...`.

**Diagnosis:** The hook source is the source of truth. The block-message
templates live in `tools/cc/hooks/_denial_reasons.py` (`PROTECTED_ZONE_*`);
`write_guard.py` formats and emits them. Compare the templates against what
`script.md` quotes.

```bash
grep -n 'PROTECTED_ZONE' tools/cc/hooks/_denial_reasons.py
```

**Fix:** Update `script.md` to the current message. Don't edit the hook
to match the script — the script tracks the hook, not the other way
round.

---

## Demo runs over 60 seconds

**Symptom:** Recording is 65–90 seconds and feels padded.

**Common causes:**

- Holding the title card too long. 5 seconds is plenty.
- Reading the prompt out loud to yourself before typing it. Don't —
  just type at conversational speed.
- Waiting for Claude Code to "finish thinking" between attempts. The
  block fires inside the tool call; you don't need to wait for a
  follow-up assistant message before moving on.
- The end-card lingering past 8 seconds.

**Fix:** Cut the third attempt before cutting anything else. Two
attempts (direct edit + traversal) are enough to make the regression
point. The third (tee variant) is a nice-to-have.

If two attempts still run long, retime the title and end cards — those
are the easiest seconds to win back.

---

## Demo is too fast to follow

**Symptom:** Viewers can't read the block messages before the next
prompt scrolls them off.

**Fix:** After each block, hold for 2–3 seconds before typing the next
prompt. The block message is the payoff; let it land. If you're using
asciinema, you can also slow playback with the `-s` (speed) option in
`asciinema play` and re-export — but the recommendation is to record
at the right pace, not edit afterward.

---

## GIF over 5MB

**Symptom:** GitHub renders a "Sorry, this image is too large" link
instead of the inline GIF.

**Fix:** Run gifsicle to optimise:
```bash
gifsicle -O3 --colors 64 espalier-demo.gif -o espalier-demo-min.gif
```

If still over budget:
- Reduce frame rate (`-f X` where X is fps; 10 fps is acceptable)
- Reduce the recording window (smaller terminal = smaller frames)
- Convert to asciinema + svg-term instead — SVG output is typically
  20–100× smaller than equivalent GIFs

---

## SessionStart banner text differs

**Symptom:** The banner in your recording doesn't match what `script.md`
shows (e.g., shorter, different field order, missing surface line).

**Diagnosis:** `tools/cc/hooks/session_start.py` controls the banner.
Format may have changed in a recent version.

**Fix:** Update `script.md`'s 00:05–00:15 section to match the current
banner. The exact field set isn't load-bearing for the demo — the
viewer just needs to see *some* hook output to confirm the harness
is alive.

---

## Recording shows real paths or usernames

**Symptom:** Reviewer asks why the demo shows `/Users/yourname/...` or
your terminal prompt has your real username.

**Fix before re-recording:**

- Use `cd /tmp/demo-target` and never cd anywhere else during the
  recording. `/tmp/...` is universally readable in the demo.
- If your shell prompt includes username/host, swap to a minimal
  prompt for the recording: `PS1='$ '` (bash/zsh) or use a separate
  recording profile in your terminal app.

---

## GitHub embed renders differently from local

**Symptom:** Local Markdown preview shows the demo correctly; GitHub
shows it broken, scaled wrong, or missing alt text.

**Cause:** GitHub strips/rewrites some Markdown features that local
previewers don't, and resizes images to fit container width.

**Fix:** Always verify on github.com/<repo>/blob/<branch>/README.md
before merging. Don't trust the local preview as final.

---

## When in doubt

The recording's purpose is to demonstrate that the friction layer
catches real bypass attempts. If anything in the recording could lead
a careful viewer to think it's staged or mocked, the recording fails
its purpose. Re-record rather than ship a recording you'd have to
defend.

If the friction layer itself stops doing what `script.md` describes,
that's a regression in espalier, not in the demo. Stop, file an
issue, and fix the regression before re-recording.
