Run code quality scanners against this repo.

```bash
python -m espalier scan .
```

**Sub-modes** — run `/scan` with a focus keyword to narrow the output:

| Invocation | Focus |
|---|---|
| `/scan` | All scanners: exceptions, prints, godfiles, perf smells, test loosening, convergence theater, subprocess contracts, filesystem contracts, magic depth, retired vocab, encoding contracts |
| `/scan exceptions` | Swallowed exceptions only |
| `/scan prints` | Print calls that should be logging only |
| `/scan godfiles` | Large files only — AST outline and extraction hints |
| `/scan perf_smells` | Performance anti-patterns only — subprocess shell-injection, `import *`, bare `open()` calls |
| `/scan test_loosening` | Test-loosening patterns only — tautological asserts, bare skips, decorators without reason, and deny-intent hook tests that observe only the return code (advisory, name-heuristic) |
| `/scan convergence_theater` | Test assertions where both sides resolve to the same source (assert X==X, len(producer)==EXPECTED_DERIVED, etc.) |
| `/scan subprocess_contracts` | Cross-module subprocess invocations not pinned by SUBPROCESS_CONTRACTS or a sister contract test |
| `/scan filesystem_contracts` | Cross-module structured-file writes (.json/.toml/.yaml) without a schema-parity test |
| `/scan magic_depth` | `Path(...).parents[N>=2]` without registry entry or `# magic-depth: ok` pragma |
| `/scan retired_vocab` | Severity-label-shape occurrences of retired vocabulary (registered in the engine's `retired_vocab` scanner, `RETIRED_TERMS`) outside historical / changelog / test-or-pack-comment contexts |
| `/scan encoding_contracts` | Text-mode `open()`, `.read_text()`, `.write_text()` and `subprocess.*(text=True)` calls that omit `encoding="utf-8"` or pin another codec — the OS-locale I/O class, on every tree including `tests/` (self-host only) |

Report findings with actionable summaries:

**Exceptions:** Silent swallows (`except: pass`) and broad catches without re-raise or logging.
For each: file, line, handler type, suggested fix.

**Prints:** `print()` calls that should be logging.
For each: file, line, content, suggested replacement.

**Godfiles:** Files above threshold with AST outlines and extraction hints.
For each: LOC, function count, function clusters (prefix groups suggesting boundaries).

**Perf smells:** Surface-level performance/IO smells the line/token scanner can see — `subprocess(..., shell=True)`, `from X import *`, and bare builtin `open()` calls. (Multi-line shapes like nested O(n²) loops are NOT detected — the `nested_loop_pattern`/`n_plus_one` regexes are retained-dead; activating them needs multi-line scan support.)

**Test loosening:** Landed artifacts of test-loosening — `assert True`, `pytest.skip()` without reason, `@pytest.mark.skip`/`@pytest.mark.xfail` without `reason=`. Empirical basis: ImpossibleBench (Oct 2025) showed GPT-5 exploits test cases 76% of the time on impossible tasks.

**Convergence theater:** Parity assertions where both sides resolve to the same source (test passes by construction, not observation). Shapes: `assert X==X` (literal-pair), `assert f(args)==f(args)` (same-call), `assert a.b==a.b` (same-attribute), `assertEqual(X,X)` (assertEqual-self), `len(producer)==EXPECTED_DERIVED` (derived-constant SUSPECT), `assert X==pytest.approx(X)` in either operand order (approx-self SUSPECT). Pragma escape: `# theater: ok <reason ≥12 chars>` above the assertion. Pragma count capped at `MAX_PRAGMA_COUNT=5`; raising the cap is a deliberate operator act.

**Subprocess contracts:** Internal subprocess invocations (`subprocess.run/Popen/check_output`, `os.system/popen`, `Popen(...).communicate()`, `shell=True` string) whose CLI surface lacks a pinning entry in `SUBPROCESS_CONTRACTS` + sister test in `tests/test_subprocess_cli_contract.py` (Espalier source repo; your own contract test elsewhere). OS-utility binaries (git, pytest, tar) are skipped via `OS_BINARIES`. Dynamic argv (`cmd = base + [...]`) is reported as UNRESOLVED — either refactor to a literal list, or attach `# subprocess-contract: ok <reason citing contract test>`.

**Filesystem contracts:** Cross-module writes of structured files (`.json/.toml/.yaml`) without a `FILESYSTEM_CONTRACTS` entry pointing at a schema-parity test. Covers `Path.write_text/.write_bytes`, `json.dump/pickle.dump/yaml.dump/toml.dump`, `with open(p, "w") as f: ...`, and `atomic_write_text/atomic_write_json` wrappers. Outputs under `reports/` (scan/fingerprint artifacts) are exempt — those are write-once-by-producer-read-by-humans, not coordination surfaces.

**Magic depth:** `Path(...).parents[N>=2]` encodes a structural depth assumption that breaks silently when a file moves. Pin via `MAGIC_DEPTH_SITES` registry entry with rationale, or attach `# magic-depth: ok <reason>` pragma above the call (reason ≥12 chars). Dynamic indices (`parents[<var>]`) always require a pragma — the depth can't be statically verified.

**Retired vocab:** Severity-label-shape occurrences of retired vocabulary outside allowed contexts. Retired terms and their replacements are registered in the engine's `retired_vocab` scanner (`RETIRED_TERMS`). The scanner matches on usage shape — bold (`**TERM**`), label (`TERM:`), table cell, bullet — not on the bare word, so prose use does not false-fire. Allowed contexts: immediate parent heading mentions History/Historical/Migration/Retired/Provenance/Deprecated; CHANGELOG; `docs/external/`; line-comment in `tests/` or `task-packs/`.

**Encoding contracts:** Text-mode I/O that follows the OS locale instead of UTF-8 — `open()` in a text mode, `.read_text()` / `.write_text()`, `subprocess.*(text=True | universal_newlines=True)` — with no `encoding=` (MISSING) or a value that is not UTF-8 (NOT_UTF8; `None` follows the locale). Invisible on a UTF-8 host; on a cp1252 Windows console a UTF-8 fixture mis-decodes and a test that is green everywhere else fails. Walks the whole tree, `tests/` included, because the user it protects runs the suite under that locale; `tests/fixtures/` and the byte-mirrors are exempt. Pragma escape: `# encoding-locale-ok: <reason ≥12 chars>` on the line above; capped at `MAX_PRAGMA_COUNT` and every pragma must still sit above a site that would fire (a dead one reds).

Priority for fixing: swallowed exceptions first (hide real failures), then test-loosening + convergence-theater (signals reward-hacking and tautology), then stealth contracts (subprocess/filesystem/magic-depth — silent coupling between modules), then encoding contracts (a failure only a non-UTF-8 host can see), then retired vocab (consolidation residue), then prints, then godfiles.
