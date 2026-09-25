# Commit messages must stand alone

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Commit messages must stand alone"

Commit messages must make sense to a reader who has **never seen the task packs**.
No task-pack IDs, no pack-item labels, no internal jargon — in the subject **or**
the body. Describe *what* changed and *why* in plain language: "fast test slice on
PRs, full suite on push", not an internal label pair.

## Why

Git history is the permanent, public, adopter-visible record. A task pack is a
working artifact that lands in `task-packs/Done/`, which is gitignored (the active
packs are tracked since 2026-09-21; the landed ones are not) — so an internal pack
reference in a commit is a **dangling pointer** once the pack lands: meaningless to a future reader,
to an adopter browsing `git log`, or to a changelog generator.

The traceability a pack ID would give **already lives in the pack's `## Landing`
stanza**, which records the commit SHA. The arrow points pack → commit, never
commit → pack.

## How to apply

Write the subject and body about the change itself. If you catch yourself typing
an internal task label, that is provenance — strip it and say what the change
does.

Same principle as [[github-workflows-are-a-shipping-surface]] (no internal
language in public artifacts), here enforced by operator preference rather than a
mechanical test.

## Rewording safety — never reword a pushed commit

It is fine to reword a message to fix this (or any) issue **only while the commit
is still local and unpushed**. The operator batches pushes rarely, so there is
usually a window.

Once a commit is on `origin`, its message is **frozen**. Rewriting it rewrites
public history — a force-push, breaking anyone who pulled, on a repo that is live
on GitHub.

**Before any reword or rebase, verify the targets are unpushed:**

```
git fetch                                          # so origin/main is current
git merge-base --is-ancestor <sha> origin/main     # reports ancestry
```

If it reports the SHA **is** an ancestor of origin, **stop.**

When you do reword unpushed commits the SHAs change — so update any pack
`## Landing` stanza that cites the old SHA, or the traceability arrow breaks.
Recover a botched rebase from the reflog; the original commits stay reachable
there.
