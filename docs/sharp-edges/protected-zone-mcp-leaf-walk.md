# Protected-Zone MCP Write Extraction (Class-A2)

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Protected-Zone MCP Write Extraction (Class-A2)"

**What it is:** when an MCP tool call reaches `write_guard`, the friction layer
must decide "does this tool_input write to a protected harness zone?" The
pre-fix branch swept only a finite, **top-level** field set
(`_hook_utils.MCP_PATH_FIELDS` = `path`/`file_path`/`destination`/…). That is
structurally insufficient — a protected write hides behind:

| id | shape | why it bypassed |
|----|-------|-----------------|
| N2 | `{"output_path": "<protected>"}` | key not in the finite field set |
| N6 | `{"files": [{"path": "<protected>"}]}` | nested one level below top-level |
| M1 | `{"batch": {"files": [{"path": "<protected>"}]}}` | nested two levels (the live freeze-blocker) |
| M1 | `{"edits": [{"file": {"path": "<protected>"}}]}` | arbitrary dict/list nesting |

**A finite key set can never cover arbitrary keys, and a finite depth can
never cover arbitrary nesting.** So the fix is a single structural move, not
more field names: a **key-agnostic, depth-bounded leaf-walk** over *every*
string leaf of the `tool_input`.

**The chokepoint (`_hook_utils.iter_mcp_path_leaves`).** Recurses dicts
(values) and lists/tuples, yielding `(governing_key, location, value)` for
each non-empty string leaf. `governing_key` is the nearest enclosing dict key
(a list inherits its parent key), so `{"files":[{"path":X}]}` yields key
`"path"` and `{"files":["a.py"]}` yields key `"files"`. The walk is **bounded**
(`MCP_LEAFWALK_MAX_DEPTH=10`, `MCP_LEAFWALK_MAX_NODES=10000`) and raises
`MCPPayloadUnverifiable` past either bound so the caller **fails closed** — an
un-inspectable payload is denied, never waved through. The walk is O(payload
bytes), the same complexity the `json.loads` that produced `tool_input` already
paid, so it adds no new super-linear (ReDoS-class) vector.

**FS-free normalisation (`_hook_utils.normalize_path_str`).** Leaves are
normalised with `posixpath.normpath` (pure string), **not** `Path.resolve()`.
resolve()'s per-component `lstat` over many/long leaves would itself be the
slow-hook fail-open (cf. the `_PERL_OPEN_RE` ReDoS critical). It shares the
separator/env-var/`~`/`lstrip` cleaning with `normalize_path` via
`_clean_path_prefixes` (one source, no drift), and `_protected_zones._fs_equiv`
applies the Class-A1 ADS/trailing-dot/NFKC/casefold fold on top — so every
Class-A1 spelling-equivalence still folds inside a nested leaf. Symlink-
following is intentionally NOT done here; that is the Class-A3 fix's job.

A relative leaf is **joined to root before `normpath`** so a leading `..` that
re-enters the repo (`../<reponame>/tools/...`) collapses against root the way
`resolve()` would, lexically — `normpath` alone cannot drop a leading `..`.
The repo-relative strip (`_rel_under_root`, shared with
`normalize_path`) is **case-insensitive**: macOS APFS / Windows NTFS treat
`/users/…` and `/Users/…` as the same file, so a case-sensitive prefix compare
would let a case-variant absolute path under root escape. On a case-sensitive FS
the case-insensitive strip over-protects, the safe fail-closed direction.

**The two hooks apply the walk asymmetrically — severity-matched, both
fail-safe:**

- **`write_guard.check_mcp` is key-AGNOSTIC** (checks every leaf, skipping only
  `MCP_CONTENT_KEYS`). Its predicate is the *narrow* protected set, so an
  under-fire is a **security fail-open** — it must catch every leaf. The rare
  over-block (a data blob that lexically starts with a protected prefix) is
  trimmed by the content-key skip and is recoverable anyway.
- **`plan_guard` gates only on `key in MCP_PATH_FIELDS`.** Its predicate is the
  *broad* "any non-exempt path requires a plan," so a key-agnostic walk would
  over-fire on every prose field carrying a slash. An under-fire here is
  recoverable plan-discipline friction (write_guard still backstops protected
  zones), so gating on path-shaped keys is the right trade.

**The content-key skip (`MCP_CONTENT_KEYS`).** A *direct* string leaf under a
content key (`content`/`text`/`body`/`data`/`code`/`snippet`/`patch`/`diff`/
`sql`/`query`/`message`) is data, not a write target, and is skipped — so
`{"path":"notes.txt","content":"cc/ ..."}` does not spuriously deny. The skip
membership test is **case-insensitive** (`key.casefold()`), parity with the
case-folding protected check — else a capitalized content key (`"Content"`)
isn't skipped and a path-shaped data value under it over-blocks (a
fail-closed false-DENY). Because the skip keys on the
*governing* (immediate) key, a path nested **under** a content key —
`{"content":{"path":"<protected>"}}` — keeps its own `"path"` governing key and
is still checked.

**How you hit it:** an MCP write whose protected target sits under a
non-canonical key, inside a list/dict nest, or both, classified ALLOW.

**How to avoid breaking it:**
- Any new MCP path-extraction must route through `iter_mcp_path_leaves` — never
  re-introduce a flat top-level field scan (that was the N2/N6/M1 hole).
- write_guard must stay key-agnostic (security); plan_guard must stay
  key-allowlisted (friction) — do not "unify" them into one filter.
- Normalise leaves with `normalize_path_str` (FS-free), never `resolve()` in a
  loop over arbitrary leaves.
- Regression coverage:
  `tests/test_write_guard.py::TestClassA2MCPLeafWalk`,
  `::TestClassA2LeafWalkUnit`,
  `tests/test_hooks.py::TestPlanGuard::test_blocks_nested_mcp_write_no_plan`.

**Known limits — residuals the leaf-walk does NOT close** (all friction-layer
only; a *committed* write to the real protected file is still caught by
`ci_guard` / `harness-guard.yml`, which read git's diff regardless of payload
shape):

1. **Content-key path targets.** A leaf under a `MCP_CONTENT_KEYS` key is
   skipped, so an MCP tool that used (say) `content` as a *write-target path*
   rather than data would escape. No known shipping tool does this (content =
   data, path = target, universally); the skip eliminates a large false-deny
   surface on real content blobs.
2. **Path-as-dict-key.** The walk inspects dict *values*; a tool that keyed a
   write by the path itself — `{"<protected>": {...}}` — would not have the key
   checked. No canonical filesystem MCP server uses this shape.
3. **Depth/node bound.** A payload nested deeper than 10 or wider than 10000
   nodes is denied **fail-closed** (an over-block on a pathological-but-legit
   batch, recoverable by splitting it or via maintenance mode), never allowed.
