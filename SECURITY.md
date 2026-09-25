# Security Policy

## Supported Versions

Espalier-Harness is pre-1.0 software. Security fixes are provided for the
latest released version and the current `main` branch on a best-effort
basis.

## Reporting a Vulnerability

**Please do not open a public GitHub issue, public pull request, or
public discussion with vulnerability details.**

Preferred path: use GitHub's private vulnerability reporting flow from
the repository Security tab by selecting `Report a vulnerability`
(equivalent URL:
<https://github.com/Mike-Byrne-AI/espalier-harness/security/advisories/new>).

Fallback path: email `mbbyrne.byrne@gmail.com` with the subject prefix
`[espalier security]`.

If neither private path is available, you may publicly request a
private security contact (with the title "request: private security
contact" and **no technical details, exploit steps, proof-of-concept
code, affected paths, or screenshots**). Vulnerability details belong
on the private channel only.

## What to Include

Please include, where possible:

- affected Espalier-Harness version or commit SHA
- operating system and shell
- whether this affects a source install, wheel install, or generated
  harness output
- affected file or component, if known
- reproduction steps
- expected impact
- whether the issue is already public or privately known
- any suggested mitigation

## Expected Response

Maintainers aim to acknowledge private reports within 7 days and
provide an initial triage result within 14 days. Fix timelines depend
on severity and maintainer availability. Public disclosure should be
coordinated after a fix or mitigation is available.

## Security Scope

In scope:

- hook scripts under `tools/cc/hooks/`
- generated `.claude/settings.json` hook wiring
- command/path parsing that could bypass protected-path friction
- `espalier init`, release-pack, pre-release, and CI guard behavior
- accidental secret or internal-material inclusion in release artifacts
- path traversal, unsafe file writes, or unsafe subprocess behavior
  in espalier code

Out of scope unless combined with another vulnerability:

- a local user intentionally editing or deleting their own hooks
- a local user intentionally setting `disableAllHooks` before hooks run
- known limitations already documented in `docs/SHARP_EDGES.md`
- upstream Claude Code behavior outside this repository
- social engineering, physical access, denial-of-service without
  security impact, or reports requiring control of the user's machine

### Coverage taxonomy

For a category-by-category mapping of Espalier's enforcement surfaces
to the OWASP GenAI Security Project's [Top 10 for Agentic Applications
2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/),
see [docs/SECURITY_TAXONOMY.md](docs/SECURITY_TAXONOMY.md). The taxonomy
documents which ASI categories each Espalier surface addresses and
where the friction-layer ends.

## Safe Harbor

Good-faith security research is welcome. Please:

- avoid accessing, modifying, or deleting data that is not yours;
- avoid persistence on systems you don't own;
- avoid public disclosure before a fix is available; and
- give maintainers a reasonable opportunity to investigate and
  remediate.
