---
name: review
description: Per-file correctness review of the current diff — bugs, style drift, project-specific pitfalls, one file at a time. Use when the user asks to review code, audit a diff, check changes before commit, or run a second-opinion pass. Distinct from /reflect (cross-artifact gaps) and /adversarial (failure-mode discovery). Delegates to the code-reviewer agent for orthogonal-context analysis.
---

# Review — code-reviewer delegation

The work is performed by the **code-reviewer** agent in its own context
so this conversation's framing does not bias the review.

## Step 1 — Frame the review

Identify the surface to review:

- "review the current branch" → `git diff main...HEAD` is the scope
- "review the staged changes" → `git diff --cached` is the scope
- "review file X" → file path is the scope
- Otherwise: ask the user which diff or path to review

## Step 2 — Delegate to code-reviewer

Dispatch the **code-reviewer** subagent (`subagent_type='code-reviewer'`). Pass:

- The exact diff or file path framed in Step 1.
- Any conventions the user mentioned that the reviewer should honor.
- Whether this is pre-commit, pre-PR, or post-merge — the cadence
  affects which severity levels matter.

The agent runs in its own context window and returns a structured
review covering correctness, style, convention drift, and
project-specific pitfalls. The agent body ships with examples drawn
from Espalier-Harness (hook exit codes, `tools/cc/` isolation, scanner
stdlib constraint, path normalization, test naming) — adopters should
treat those as starting examples and adapt to their project.

## Step 3 — Surface the findings

Present the agent's verdict as-is. Do not re-litigate its calls — the
agent's context is the reference. If the user asks "should I fix X?",
that's a separate decision; the review just names what's there.
