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
| `quote_sources` | no | list of `https://` URLs | Further pages the body quotes, beside `source_url`. The refresh checks each quoted passage against `source_url` and these together. |

The body after the frontmatter is the excerpt itself — markdown, prose
quotes from upstream, and a closing "What espalier asserts against
this excerpt" section listing the binding tests.

**Every `>` line in a pin is an upstream quote**, word for word apart from
formatting (links, emphasis, table bars, line wrapping), with any omission
marked `[…]`. The refresh reads a pin's drift off those lines alone, so
espalier's own commentary, a callout or a warning included, is written as
prose, never as a blockquote.

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

What a refresh checks, per pin:

1. **Drift is read off the quotes.** Every `>` passage must appear in the
   fetched `source_url` page (or one of the pin's `quote_sources`), once
   both sides drop formatting. `none`: every quote stands. `semantic`: the
   report names each passage that moved, by pin line. `unverifiable`: the
   pin quotes nothing. Espalier's own prose is never compared, so a
   refresh no longer reports drift on every run.
2. With `--apply`, a pin whose quotes moved gets `<pin-name>.candidate.md`,
   the fetched page under the pin's frontmatter, to re-excerpt from. The
   original pin is **not** overwritten, and a candidate is never renamed
   over a pin: it is the raw page, not an excerpt. Re-excerpt the moved
   passages by hand, and say what changed.
3. The tests the pins cite run on the committed tree: every `tests/...py`
   path a pin's body names, plus `tests/test_documented_claims.py` and
   `tests/test_hook_protocol.py` (a tree that holds none of them, such as
   an adopter's, skips them and says so). A pass means espalier's claims
   against the committed pins still hold. It does not mean upstream still
   says what a pin quotes: that is step 1.

The run fails (non-zero) only when a pin could not be checked: a page that
could not be fetched, came back empty, or came back as HTML instead of the
Markdown twin; or a pin that quotes nothing long enough to check. Moved
quotes do not fail it; the candidate and the report are the action.

What the quote check cannot see: text upstream adds *beside* a quote that
still stands -- a new sentence after it, a clause before it. A clause added
inside a quoted sentence or before its period is caught, as is a table row
only a longer name's row would contain. A quote of fewer than twelve letters
and digits is too short to judge; the summary counts those. And
`--interactive`'s accept is the one path that replaces a pin with the
fetched page: it overwrites the curated excerpt, so re-excerpt by hand
instead.

## Files

- `cc-hook-protocol.md` — Claude Code hook protocol channel/exit-code/JSON contract, and the two worktree events (`WorktreeCreate`, `WorktreeRemove`), which espalier does not wire.
- `cc-statusline.md` — Claude Code status line: shell string, shell per platform, update triggers, silent-blank failure, trust/kill-switch gating.
- `cc-worktrees.md` — Claude Code worktrees: the hook input's `cwd` follows Claude into a worktree while `CLAUDE_PROJECT_DIR` stays at the project root; the `git worktree lock` Claude Code holds on a running agent's or backgrounded session's worktree, and the stale-lock window until the sweep; a `WorktreeCreate` hook replaces creation and leaves no such lock.

(Add new pins as espalier takes on new external dependencies.)
