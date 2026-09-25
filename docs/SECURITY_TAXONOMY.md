# Espalier-Harness Security Coverage — OWASP ASI 2026 Mapping

If your org maps its tools to the OWASP ASI Top 10, here's how
Espalier-Harness's seatbelts line up. This document maps Espalier's
enforcement surfaces to the OWASP GenAI Security Project's **[Top 10 for
Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)**
(released December 2025). Each row identifies the Espalier surfaces
that address a given ASI category, the mechanism, and an honest scope
note on what the surface does and does not guarantee.

This is a *coverage* mapping of a workflow harness — not a *certification*
and not a positioning credential. Espalier-Harness is a workflow +
friction-and-visibility layer with a CI-side guarantee; it is explicitly
**not** a sandbox, security boundary, enterprise compliance product, or
hardened security tool. See the "Honest scope" section below and
[README.md](../README.md#what-this-is-not).

## Coverage matrix

| OWASP ASI 2026 | Espalier surface | Mechanism | Honest scope |
|---|---|---|---|
| **ASI01 — Agent Goal Hijack** | `plan_guard`, `write_guard` kill-switch enforcement, `test_loosening` scanner, pack-artifact 0-A review | Plan-gated writes constrain agent action to declared intent. Kill-switch protection denies the in-session edit that would set `disableAllHooks` (a pre-launch disable or the two-step subprocess bypass is out of scope — see the Honest scope cell). Test-loosening scanner catches landed reward-hacking artifacts (`assert True`, bare skips). The /implement-pack 0-A review catches phantom predicates declaring intent without runtime grounding (MAST-class specification ambiguity). | Friction layer, not a sandbox. Bypassable by design — see `bench/corpus/BC-OOS-*.json`. CI is the load-bearing guarantee. |
| **ASI02 — Tool Misuse** | `write_guard` dangerous-bash + dangerous-PowerShell patterns | Denies `rm -rf /`, fork bombs, sudo escalation, and other documented dangerous-tool patterns at write-time. Pattern corpus pinned by `bench/corpus/BC-NNN-*.json`. | Pattern-based; new tool-misuse vectors require corpus update. Out-of-scope bypass classes documented as `BC-OOS-*`. |
| **ASI03 — Identity & Privilege Abuse** | `write_guard` protected-zone enforcement, `config_guard` settings safety, `.espalier/integrity.json` manifest | Hard-deny on mutations (a write, a delete, a move) of harness machinery — the `tools/cc/` and `cc/` trees (plus `espalier/` and `.github/workflows/` on the self-host repo) and the exact files `.claude/settings.json`, `.claude/settings.local.json`, `.github/workflows/harness-guard.yml`, `.espalier/integrity.json`, `.espalier/freshness.json`. Integrity manifest verifies the hash chain of governance files. Config_guard blocks unsafe project/local/user settings changes. | Protected-zone enforcement is friction; the two-step subprocess bypass (BC-OOS-001) is documented out-of-scope. Integrity verification detects tampering; CI gates the merge. |
| **ASI04 — Agentic Supply Chain Vulnerabilities** | `tools/cc/ci_guard.py`, `scripts/release_check.py` dual-witness archive validation | CI-side guard gates merges to `main` regardless of any session-side bypass. Release-check uses two independent classifiers (`espalier/release_noise.py` + `espalier/release_denylist.py`, asserted independent via AST walk) for archive cleanliness. | Covers the harness's *own* supply chain (governance machinery integrity, release artifact cleanliness). User-project dependency CVEs are out of scope. |
| **ASI05 — Unexpected Code Execution** | `write_guard` dangerous-bash patterns, variable-indirect detection, heredoc-eval guards, `plan_guard` | Blocks inline `bash -c "$X"`, variable-indirect expansion, heredoc-to-interpreter patterns at PreToolUse. Plan-required gate forces explicit intent declaration before source writes. | AST-pattern + regex denylist. Documented bypass classes in `bench/corpus/`. Literal write paths inside an interpreter program are read whether it arrives by `-c` or on stdin (`python3 - <<'PY'`, `bench/corpus/BC-051`); computed paths, a body that is data to a script or module operand, and file-mediated two-step writes (`bench/corpus/BC-OOS-001`) remain the boundary -- subprocess introspection is the architectural gap. |
| **ASI06 — Memory & Context Poisoning** | Cognitive blueprint chain (`tools/cc/cognitive_blueprint.py`), `subagent_stop`, `post_compact`, `stop_gate` Gate 4 | Blueprint chain creates a session-continuity record across compactions. `post_compact` re-injects critical context after Claude Code compresses the conversation. `subagent_stop` appends sub-agent reasoning to the active blueprint. Gate 4 of stop_gate auto-finalizes the blueprint at session end. | Context-corruption *resistance*, not a cryptographic *guarantee*. Blueprint files (`cc/blueprints/*.json`) are protected via `write_guard`; tampering requires the same out-of-scope bypass classes as other protected-zone edits. |
| **ASI07 — Insecure Inter-Agent Communication** | *(Not directly addressed)* | n/a | Espalier-Harness is single-agent governance scoped to one Claude Code session. Multi-agent coordination — where ASI07 lives — is out of scope. Subagent reasoning is captured via `subagent_stop` for visibility (see ASI06) but inter-agent communication channels are not gated. |
| **ASI08 — Cascading Failures** | `exceptions` scanner, `stop_gate` pytest gate, `post_write_check` | Exceptions scanner catches silent exception swallows (`except: pass`, broad catches without re-raise) — the most common cascading-failure precursor. stop_gate runs pytest at session-end to detect cascading regressions before they ship. post_write_check validates JSON parse-ability per write so structural corruption surfaces immediately. | Detection only; recovery is operator-driven. The exceptions scanner is regex-based; AST-evading patterns (string-interpolated `except` keywords) are out of scope. |
| **ASI09 — Human-Agent Trust Exploitation** | `reflect_trigger`, `~/.espalier/audit/` log, structured deny reasons (`tools/cc/hooks/_denial_reasons.py`) | `reflect_protocol` fires every 10 source writes to surface emergent patterns for operator review. The audit log is **append-mode** (a HOME-dir `open("a")` JSON-lines file at `~/.espalier/audit/{repo}-{date}.log`); it is not tamper-resistant. Denial reasons are machine-parseable and human-readable, with explicit escape-hint pointers (e.g., "set `plan_exempt_prefixes` in `espalier.toml`" rather than the more powerful `ESPALIER_MAINTENANCE_MODE`). | Surfaces signal to the operator; does not prove operator trust is correctly calibrated. The "alert fatigue" failure mode — a substantial, widely-varying fraction of static-analysis warnings are non-actionable, a recurring finding in the static-analysis literature — motivates Espalier's deliberately conservative 10-hook count. |
| **ASI10 — Rogue Agents** | Three-tier defense: `session_start` (visibility) → `write_guard` + `config_guard` (deny) → `tools/cc/ci_guard.py` (CI guarantee) | `session_start` reports kill-switch state at session open. `write_guard` and `config_guard` hard-deny new tool calls / settings changes once a kill-switch is committed. `ci_guard` fails CI regardless of any session-side approval marker (BC-032). | Friction is bypassable; the CI guarantee is the load-bearing layer. The harness explicitly publishes its limitations in `README.md` "What this is NOT" — adopters are responsible for understanding the friction-vs-guarantee distinction. |

## Honest scope

This mapping describes which OWASP ASI 2026 categories Espalier's
enforcement surfaces **address**, not which they **fully mitigate**.
Per [README.md](../README.md), Espalier-Harness is:

- **Not a sandbox.** The agent can shell out, write to /tmp, run
  subprocess.
- **Not a security boundary.** Two-step subprocess bypasses, variable-
  indirect interpreter invocations, and other documented `BC-OOS-*`
  bypass classes work by design.
- **Not enterprise compliance.** Espalier addresses agent-coding-
  failure-mode categories; it does not implement SOC 2 controls, GDPR
  data-handling, or industry-specific compliance frameworks.

The friction layer (`write_guard`, `plan_guard`, `config_guard`) is
bypassable by design. See `bench/corpus/BC-OOS-*.json` for the
documented out-of-scope bypass classes (two-step subprocess, mid-
session env-var assignment ignored, a write target built by command
substitution, etc.). The mechanical guarantee lives in CI
(`.github/workflows/harness-guard.yml`); the friction layer is the
visibility-and-attention layer.

### What this taxonomy is for

This document is intended to make Espalier's coverage **legible to
enterprise security reviewers** who need to evaluate the harness
against a recognized taxonomy. It is not a substitute for:

- Reading the [bench corpus](../bench/corpus/) for the specific bypass
  classes Espalier covers and the documented out-of-scope cases.
- Reviewing [docs/SHARP_EDGES.md](SHARP_EDGES.md) for the harness's
  known footguns and friction-layer gaps.
- Running the regression benchmark (`python bench/run_benchmark.py`)
  to verify coverage on your installation.

## References

- **OWASP Top 10 for Agentic Applications 2026** — [genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (canonical taxonomy)
- **OWASP GenAI Security Project announcement** — [genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/](https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/)
- **Espalier honest-scope statement** — [README.md "What this is NOT"](../README.md)
- **Bypass corpus** — [bench/corpus/](../bench/corpus/) (BC-NNN documented classes)
- **CI guarantee** — [.github/workflows/harness-guard.yml](../.github/workflows/harness-guard.yml)
- **Vulnerability reporting** — [SECURITY.md](../SECURITY.md)
