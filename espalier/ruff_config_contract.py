"""Allowlist for ``[tool.ruff.lint.per-file-ignores]`` entries.

Inverse-direction sibling of
``tests/test_ruff_config_includes_security_rules.REQUIRED_RULES``:
that contract pins what the ``select`` list MUST include; this
allowlist pins what the ``per-file-ignores`` block MAY include (FM-17).

Without an inverse contract, a future edit adding e.g.
``"espalier/cli.py" = ["S110"]`` to ``per-file-ignores`` would
silently roll back that file's security-rule gate. The
``per-file-ignores`` block's lack of structural enforcement was the
asymmetry; this allowlist closes it.

Each row: ``(path_glob, frozenset_of_rule_codes, reason_substring)``.
The ``reason_substring`` must appear in the
``[tool.ruff.lint.per-file-ignores]`` section text of
``pyproject.toml`` so the rationale stays at the surface. Adding a
new entry without an allowlist row fails the parity contract;
forgetting the rationale comment in pyproject also fails. Both errors
keep the discipline asymmetric to the friction of dropping a rule
from the lint set.

Stdlib-only; no third-party deps. Public-shaped name so tests import
it; the rest of ``espalier/`` does not consume the registry at
runtime.
"""
from __future__ import annotations

ALLOWED_PER_FILE_IGNORES: tuple[tuple[str, frozenset[str], str], ...] = (
    # Verdict-state constants ("pass"/"fail"/"BLOCK") are not passwords;
    # ruff S105's lexical heuristic over-matches on them.
    (
        "bench/end_to_end/assertions.py",
        frozenset({"S105"}),
        "Verdict-state constants",
    ),
    (
        "espalier/audit_accuracy.py",
        frozenset({"S105"}),
        "Verdict-state constants",
    ),
    (
        "espalier/scanners/freshness.py",
        frozenset({"S105"}),
        "Verdict-state constants",
    ),
    # Test fixtures deliberately exhibit anti-patterns under test.
    # FM-21 (post-OSS) is queued to narrow this set; for now, fixtures
    # get the broad-class ignore.
    (
        "tests/fixtures/**",
        frozenset({"S", "B", "F", "RUF"}),
        "Test fixtures deliberately exhibit anti-patterns",
    ),
    # ``tests/test_hooks.py`` execs hook source for isolation testing.
    (
        "tests/test_hooks.py",
        frozenset({"S102"}),
        "Tests may exec hook source for isolation",
    ),
)
