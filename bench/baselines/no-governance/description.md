# no-governance baseline

**What this represents:** A Claude Code project with no hooks, no `permissions.deny`
rules, no governance harness. This is the floor — what gets through when nothing
is configured.

**What it claims to handle:** Nothing. This baseline exists to establish the bottom
of the comparison.

**Expected results:** Every in-scope bypass attempt is allowed (the runner records
"not blocked") because there is no enforcement layer to invoke. The documented
out-of-scope cases are also allowed, which is the correct outcome — the friction
layer is supposed to allow those.

**Why it's in the benchmark:** Without a floor baseline, "all in-scope classes
blocked" looks like a feature claim instead of a measurable improvement. The floor
shows the delta.
