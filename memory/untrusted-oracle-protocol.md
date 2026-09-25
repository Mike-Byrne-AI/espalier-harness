# Untrusted-oracle protocol

**Status:** active
**Linked from:** [CLAUDE.md "Core Rules"](../CLAUDE.md)

When the Claude Code **tool I/O runtime** intermittently fabricates output —
phantom file reads returning invented content, empty/echoed/stale frames,
cancelled parallel batches, a display-frame `FAILED` that never failed — the
in-loop agent cannot trust what a single rendered frame shows. This is an
upstream *runtime* behavior, not an Espalier logic gap. The discipline below
kept a degrading session (the TP-151 retro, 2026-05-30) to zero bad landings;
it is codified here so the next session does not re-improvise it under pressure.

The governing instinct is the same one Espalier's design already teaches —
**never let a producer validate its own output** (dual-witness denylist,
byte-equality parity, AST-over-substring checks) — applied to the tool channel
itself. The "producer" is the tool display channel; the "independent witness" is
a mechanical oracle (an exit code, a byte-match, cross-command agreement) that
does not depend on believing a frame.

**Framing (do not overstate).** "Trust git" is *wrong*: `git`, `pytest`, and
every other command flow through the same Bash channel that can lie. What
actually protects is (a) a **mechanical gate** that refuses the operation on
mismatch and (b) **triangulation** — independent commands fabricating
*consistently* is low-probability. There is no single authoritative command.

## The four techniques

1. **Mechanical gate over rendered output.** The strongest leg is not "read
   carefully" — it is letting a tool *refuse the operation on mismatch*. Edit's
   exact-`old_string` requirement is a built-in guard: an edit built from a
   fabricated read **cannot match** the real bytes, so it fails loudly instead
   of corrupting. Prefer constructs that fail-closed on bad input over
   constructs that ask you to believe a frame. *Why it works:* the guard is
   independent of the channel that produced the read. *Limit:* exact-match
   protects *replace* edits well but is weak for *append*-style edits where the
   anchor is short or common — that gap is what technique 4 escalates on.

2. **Triangulate; don't trust a single frame.** Believe a fact only when ≥2
   independent commands agree — e.g. `git diff --numstat` + a functional probe +
   a `pytest` exit code. *Why it works:* consistent fabrication across
   independent commands is low-probability, so agreement is the confidence
   signal. A single rendered frame is never authoritative — least of all a
   scrolled `FAILED`/`passed` line, which is *display*, not a result. Only a
   cleanly-captured process **exit code** is a test result.

3. **Route around the display layer.** When a frame looks wedged, empty, or
   stale, capture to a file and read it back through a second path:
   `python3 - > /tmp/x.txt 2>&1` then read `/tmp/x.txt`, or
   `python3 -c "print(open('/tmp/x.txt').read())"`. *Why it works:* a *different
   rendering path* de-correlates a transient display glitch. **Caveat (do not
   overstate):** a `/tmp` round-trip still flows through the same Bash/Read
   channel and can still fabricate — it lowers display-glitch correlation, it is
   **not** an independent oracle. Real confidence comes only from the mechanical
   gate (1) and triangulation (2); the round-trip is a tactic for un-wedging a
   frame, not a witness.

4. **Escalate to checkpoint-and-pause when the strongest guard weakens.** The
   mechanical gate (1) is strong for replace-edits but weak for append-style
   edits on protected files (short anchors, no surrounding match to fail on).
   When the work shifts to that mode *and* the channel is actively degrading,
   **stop**: checkpoint-commit the verified work with a precise blueprint resume
   note, and recommend a fresh session to clear the channel rather than pushing
   through. *Why it works:* a clean restart is cheaper than an undetected bad
   landing.

## Red/green asymmetry (load-bearing)

A phantom *red* (false failure report) costs operator time but can never become
drift — there is nothing real to build on. A phantom *green* (false pass) is the
dangerous case, and it is caught by CI / committed contracts regardless. The
rule is therefore **directional and conservative**:

- **A red is presumed REAL.** Never *dismiss* a failure as "probably phantom"
  and move on. *Re-derive* it through an independent out-of-band oracle — re-run
  the failing node, capture output to a file, read the exit code through a second
  path — then act on the re-derived result. If you cannot re-derive it, treat it
  as real and stop.
- **A green is never trusted on a frame alone.** A phantom green is the only one
  that can corrupt; lean on the mechanical Stop-event gate
  (`tools/cc/hooks/stop_gate.py` Gate 1, which adjudicates on a cleanly-captured
  subprocess exit code and is not phantom-vulnerable) and committed contracts to
  catch it.

So the verify-before-acting step is about *not wasting turns chasing a phantom
red* and *never trusting a phantom green* — it **never relaxes a real gate and is
never license to dismiss a failing one.**

Corollary (from the same family): **do not let isolation override aggregate.** A
test that fails in the full suite but passes alone is the textbook signature of a
real order-dependent / shared-fixture / import-coupling bug — treat the
isolation/aggregate *mismatch* as its own stop condition, never as proof the
failure was phantom.

## When to stop

Stop and checkpoint when both hold: the work has shifted to a mode the mechanical
gate (1) cannot protect (append-style edits, short anchors) **and** the channel
is actively degrading (repeated void/stale/echoed frames). Commit the verified
work with a resume note and recommend a fresh session — a clean restart clears
the channel; pushing through risks the one outcome the protocol exists to
prevent.

This is the independent-witness instinct Espalier's design teaches (dual-witness
denylist, byte-equality, AST-over-substring), applied to the tool channel itself.

## See also

- `docs/SHARP_EDGES.md` — "A rendered test-failure frame is not a test result"
  (the failure-mode framing of technique 2 + the red/green asymmetry; names the
  deferred mechanical form `tools/cc/confirm_test_failure.py`).
- The bash-guard quoted-argument over-match is one concrete instance of this
  doctrine (the env-prefix deny scans a raw frame it cannot fully parse).
- Provenance: TP-151 session retro, 2026-05-30; the channel was still
  intermittently fabricating while this protocol was authored, so authoring it
  used the protocol it codifies (git-show oracle + temp-file round-trip +
  cross-command triangulation).
- Dual: [[complacent-oracle]] (FAILURE_MODES §13.9) is the case this protocol's
  trigger MISSES — output that looks *fine*, not fabricated / empty / stale.
  When a trusted tool's output is plausible, distrust it by *schedule* (audit
  raw output against ground truth), not by symptom.

## Worked instances (2026-06, autonomous execution)

Two more concrete applications of "verify the side-effect, not the rendered
frame" (full context: `docs/AUTONOMOUS_EXECUTION.md`):

- **Channel-probe: stdout success ≠ hook fired.** Bringing up a nested
  `claude -p` channel, the first probe returned a `CHANNEL_OK` sentinel on
  stdout — but the blueprint files did not change, so SessionStart could NOT yet
  be confirmed to have fired. The decisive test reads the *hook side-effect* (the
  `session_started` flag mtime + the blueprint store), not the model's reply.
  Technique 2 (triangulate) applied to channel bring-up.
- **SIGPIPE "no match" disproved by timestamps.** A `git log | grep -q`
  commit-verify intermittently reported "no match" under `pipefail` (a SIGPIPE
  race — FAILURE_MODES §7.6). The "the commit isn't there" frame was the
  unreliable oracle; reading the commit *timestamps* (the commit predated the
  check) was the trustworthy one and killed the timing theory. The rendered
  failure was display; the disk timestamp was the result.
