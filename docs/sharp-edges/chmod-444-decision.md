# chmod 444 on hook files — considered and rejected

**Status:** retired
**Linked from:** ESPALIER_MEMORY.md row 24 (chmod 444 considered and rejected); docs/SHARP_EDGES.md "Retired considerations"

**What it was:** A proposed addition to `cmd_init` that would
`chmod 444` every hook file under `tools/cc/hooks/` after initial
deployment. The intent was OS-level enforcement on top of the existing
hook-pattern matching: if an attacker bypasses the `write_guard.py`
bash-pattern detector via two-step subprocess or `python3 -c "..."`
heredoc, a read-only file mode still refuses the write at the syscall
boundary.

**Why it was rejected:**

1. **Bypass classes already exist.** The threat model behind the
   proposal is hook-pattern bypass — the attacker side-steps
   `write_guard.py`'s string-based detection. But the bypass classes
   that motivate this are already documented and tested:
   `bench/corpus/BC-OOS-001-two-step-subprocess.json` and sibling
   entries. The pattern detector treats those as known-bypass; adding
   chmod 444 doesn't change the bypass class taxonomy, it just adds
   one more friction layer between the detector and the syscall.

2. **chmod 444 is itself bypassable.** The same attacker model that
   evades the bash-pattern detector can run `chmod u+w
   tools/cc/hooks/X.py` first, then overwrite. The incremental
   defense is friction (one extra command), not a guarantee.

3. **The 3-tier defense is the primary surface.** Espalier-Harness
   defends governance state through three independent layers:
   - **Friction layer** — `write_guard.py` denies obvious bypass
     patterns in shell commands.
   - **Visibility layer** — `espalier audit .` walks managed paths
     and reports drift; `_integrity.py` pins hook content via
     SHA-256.
   - **CI guarantee** — `ci_guard.py` runs against PR diffs and
     fails the merge if managed paths drift without the
     `HARNESS-UPDATE-APPROVED` marker. The CI gate is the only layer
     a local-machine bypass cannot reach.
   chmod 444 lives inside the friction layer's threat model; it does
   not contribute to the visibility or CI-guarantee layers.

4. **The honest documentation surface beats a stale TODO.** The
   ESPALIER_MEMORY.md row tracking this carried "NOT YET IMPLEMENTED — add to
   `cmd_init`" for 30+ days. The pre-OSS-release review surfaced this
   as either-implement-or-strike. The chosen path: strike + write
   this document. Adopters reading ESPALIER_MEMORY.md see a closed decision
   with rationale rather than a stale TODO.

**What ships instead:** The unchanged 3-tier defense. `write_guard.py`
catches the documented bypass classes (BC-OOS-* corpus); CI gates the
remaining surface. Adopters who want OS-level enforcement on top of
this can add it in their own init flow — the harness does not deploy
it.

**Class signature:** "Friction layered on friction is still friction."
A bypass-class catalog combined with a CI guarantee is structurally
stronger than any number of local-machine permission bits.

**Receipts:** a pre-release configuration review flagged this row as
open debt; the chosen path was strike + sharp-edge documentation. The
companion `ESPALIER_MEMORY.md` row 24 is now rewritten as a
closed-decision pointing here.
