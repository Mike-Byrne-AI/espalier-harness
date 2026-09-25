# Convergence Is a Property of the Angle Set, Not the Implementation

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Convergence Is a Property of the Angle Set, Not the Implementation" (if you maintain an index)

**What it is:** When a multi-round review chain "converges" — round N
finds 0 BLOCKs and the chain stops — the result describes the review
angles the chain attacked, not the state of the code. A fresh review
using *different* angles (taxonomy holes, drift detection,
vacuous-test grep, encoding edges, config-shape coherence) will often
re-open findings the converged chain declared closed.

**How you hit it:** A 14-round adversarial review chain. The final
round declares "0 code BLOCKs, only doc drift." Within an hour of
the tag, a post-tag audit running five different specialist agents
in parallel against fresh angles finds 7 new BLOCKs plus 2
operational CRITICALs. Most embarrassing: an earlier round was
explicitly a "sister-site sweep" — yet it missed two known parallel
sites because the sweep didn't include itself.

**How to avoid it:**

1. **Document the angle set explicitly** in any "we're done" claim.
   Not "code is clean" but "code is clean against angles X, Y, Z."
   The next audit attacks angles A, B, C — and the limit is the
   union, not either set.
2. **Pre-commit to angle rotation.** For high-stakes features,
   allocate budget for: code correctness, docs accuracy, layer
   architecture, security/bypass, concurrency, MCP/extensibility,
   upgrade-path, case-insensitive FS, sister-site sweep,
   **plus**: test-taxonomy holes, drift-from-fingerprint, vacuous-
   test grep, encoding edges, config-shape coherence, operational
   state (blueprints, fingerprint).
3. **Run a different-angle pass after the chain stops.** A
   post-asymptote audit using specialist agents in parallel against
   angles the chain didn't attack is cheap and catches the class
   of BLOCKs that survive convergence-by-angle-exhaustion.
4. **Sister-site sweeps must include their own documentation.** The
   line documenting "we swept sister-sites for X" is itself a
   sister-site of X.

**Class signature:** "absence of evidence is not evidence of absence,
unless your evidence-gathering covers the search space." The chain's
convergence is a fixed point of the chain's own attention. Fresh
attention re-perturbs the system.

**Operational pattern:** Pre-cut deep-dives that run 4+ specialist
agents in parallel against orthogonal angles are the canonical
counter-measure. Espalier's own v0.7.3 cut used this shape and the
failure-mode-reviewer agent surfaced a release-blocker
(wheel-package-data omission) that the per-pack review angles had
no chance of seeing. The cost is one extra parallel-review pass
per release; the saved cost is the post-release hotfix the missed
blocker would have required.
