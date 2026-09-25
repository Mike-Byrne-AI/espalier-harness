# External Truth Pins

This directory contains pinned excerpts of external contracts that
espalier depends on. Every file here has:

1. A **canonical source URL**.
2. A **fetch date** in `YYYY-MM-DD` format.
3. A **section reference** (anchor or page identifier from the source).
4. A **purpose statement** — what espalier asserts against this excerpt.

## Why this exists

espalier shipped a foundational bug for months because internal docs
(docs/SHARP_EDGES.md), tests (test_contracts.py), implementations (hook scripts),
and benchmarks all agreed with each other on the wrong contract. The
external source of truth (Claude Code hook protocol) was never pulled into
the verification loop. This directory is the verification loop.

Files here are **not authoritative copies** of the external sources — they
are **pinned excerpts at a known date**, used as the verification target
for Espalier-Harness's claims. When the upstream contract changes, the diff
should surface here first.

## Frontmatter schema

Every pin file under this directory (except this README) starts with a
YAML frontmatter block delimited by `---`. The schema:

| Field | Required | Format | Notes |
|---|---|---|---|
| `source_url` | yes | `https://...` | Canonical upstream URL. One per pin. |
| `fetched` | yes | `YYYY-MM-DD` | Date the excerpt was last refreshed against `source_url`. |
| `section` | yes | string | Human-readable section name from the upstream source. |
| `purpose` | yes | string (block scalar OK) | What espalier asserts against this excerpt. |
| `mirrors` | no | list of URLs | Alternate canonical URLs (CDN, mirrored docs site). |
| `section_anchor` | no | string | Anchor/fragment ID for direct linking. |
| `content_hash` | no | sha256 hex | SHA-256 of normalized body (post-frontmatter). Cleared to empty on each refresh; operator re-fills manually via a hash util (advisory — not auto-maintained). |
| `refresh_policy` | no | `weekly` \| `monthly` \| `manual` | Cadence for the refresh CI workflow. Default: `manual`. |

The body after the frontmatter is the excerpt itself — markdown, prose
quotes from upstream, and a closing "What espalier asserts against
this excerpt" section listing the binding tests.

## Refresh policy

Excerpts are refreshed via `espalier refresh-externals`:

```bash
espalier refresh-externals                 # dry-run summary
espalier refresh-externals --pin NAME      # one pin only
espalier refresh-externals --apply         # write .candidate.md files + run bound tests
espalier refresh-externals --interactive   # prompt accept/reject per pin
```

The CI workflow `.github/workflows/refresh-externals.yml` runs `--apply`
weekly and opens a PR when drift is detected. Auto-merge is never
enabled; refreshes are reviewed by a human.

When the pin's body changes:

1. Fetched content is written to `<pin-name>.candidate.md` — the
   original pin is **not** overwritten.
2. `pytest tests/test_documented_claims.py tests/test_hook_protocol.py`
   runs against the candidate.
3. Failing tests reveal espalier claims that drifted with the
   upstream contract — those claims must be reconciled before the
   candidate is renamed over the pin.

## Files

- `cc-hook-protocol.md` — Claude Code hook protocol channel/exit-code/JSON contract.
- `cc-statusline.md` — Claude Code status line: shell string, shell per platform, update triggers, silent-blank failure, trust/kill-switch gating.
- `cc-worktrees.md` — Claude Code worktrees: the hook input's `cwd` follows Claude into a worktree while `CLAUDE_PROJECT_DIR` stays at the project root; the `git worktree lock` Claude Code holds on a running agent's or backgrounded session's worktree, and the stale-lock window until the sweep.

(Add new pins as espalier takes on new external dependencies.)
