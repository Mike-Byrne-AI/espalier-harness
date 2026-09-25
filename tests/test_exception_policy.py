"""TP-53 Group E — exception-policy regression test.

Runs ``scripts/check_exception_policy.py`` against the live tree and
asserts no NEW unannotated ``except Exception:`` / ``except:`` handler
landed outside the grandfathered allowlist.

The convention (docs/CONVENTIONS.md "Broad-except narrowing") is:

1. Specific exception types by default
   (``except (ValueError, OSError):``).
2. ``# noqa: BLE001 — <reason>`` on the except line when the broad
   form is genuinely required.

Pairs with `scripts/exception_policy_allowlist.json` which records the
shrinking list of grandfathered sites.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_checker():
    """Import the script as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(
        "_tp53_exception_check",
        REPO_ROOT / "scripts" / "check_exception_policy.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pytestmark = [pytest.mark.contract]


class TestExceptionPolicyGate:
    def test_a_latin1_allowlist_is_an_empty_set_not_a_traceback(self, tmp_path, monkeypatch):
        """Ledger DEF-829: ``UnicodeDecodeError`` is a ``ValueError``, so the
        ``(JSONDecodeError, OSError)`` tuple let it past ``_load_allowlist``.
        A JSON file is a structured answer: the strict read stays, and the
        handler names ValueError so a code-page re-save takes the unreadable
        path (every finding then reads as new, which is loud, not a crash)."""
        checker = _load_checker()
        bad = tmp_path / "allow.json"
        bad.write_bytes(b'{"grandfathered": ["caf\xe9"]}')
        monkeypatch.setattr(checker, "ALLOWLIST_PATH", bad)
        assert checker._load_allowlist() == set()

    def test_no_new_unannotated_broad_except(self):
        """Any new ``except Exception:`` MUST carry ``# noqa: BLE001`` OR
        narrow to a concrete tuple. The allowlist captures grandfathered
        pre-convention sites and shrinks over time.
        """
        checker = _load_checker()
        findings = set(checker.find_unannotated_broad_excepts(REPO_ROOT))
        allowlist = checker._load_allowlist()
        new_violations = sorted(findings - allowlist)
        assert not new_violations, (
            "new unannotated broad-except handlers added without "
            "either narrowing the type or adding `# noqa: BLE001 — "
            "<reason>` on the except line:\n  "
            + "\n  ".join(new_violations)
            + "\n\nSee docs/CONVENTIONS.md 'Broad-except narrowing' "
            "for the precedent shape."
        )

    def test_allowlist_does_not_grow_silently(self):
        """If the allowlist file has more entries than the live tree
        contains, those entries are stale and should be removed —
        someone fixed the site without bumping the allowlist down.
        """
        checker = _load_checker()
        findings = set(checker.find_unannotated_broad_excepts(REPO_ROOT))
        allowlist = checker._load_allowlist()
        stale = sorted(allowlist - findings)
        assert not stale, (
            "exception_policy_allowlist.json lists entries that no longer "
            "appear in source — remove them so the allowlist tracks "
            "reality:\n  " + "\n  ".join(stale)
        )

    def test_helper_skips_narrow_except(self, tmp_path):
        """Sanity: narrowed except handlers are NOT flagged."""
        checker = _load_checker()
        sample = tmp_path / "sample.py"
        sample.write_text(
            "def f():\n"
            "    try: pass\n"
            "    except (ValueError, OSError): pass\n",
            encoding="utf-8",
        )
        import ast
        tree = ast.parse(sample.read_text(encoding="utf-8"))
        broad_handlers = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler) and checker._is_broad_except(node)
        ]
        assert not broad_handlers

    def test_vendor_mirror_is_excluded_from_scan(self, tmp_path):
        """TP-267 2-A: find_unannotated_broad_excepts must skip
        ``espalier/_vendor/`` (the byte-identical mirror of tools/cc), matching
        the sibling scanners (magic_depth, filesystem_contracts). The natural RED
        cannot fire on this host — the live mirror carries no un-annotated
        broad-except today — so this PLANTS one under a fake ``espalier/_vendor/``
        tmp tree. Magnitude: latent false-positive prevention, NOT an observed CI
        red. A real (non-vendor) espalier file with the same handler is the
        control: it MUST still be flagged, proving the exclusion is scoped to
        ``_vendor`` and is not a blanket suppression."""
        checker = _load_checker()
        broad = "def f():\n    try:\n        risky()\n    except Exception:\n        pass\n"

        vendored = tmp_path / "espalier" / "_vendor" / "cc"
        vendored.mkdir(parents=True)
        (vendored / "vendored_mod.py").write_text(broad, encoding="utf-8")
        (tmp_path / "espalier" / "real_mod.py").write_text(broad, encoding="utf-8")

        findings = checker.find_unannotated_broad_excepts(tmp_path)

        assert not any(p.startswith("espalier/_vendor/") for p in findings), (
            f"vendored mirror was scanned (should be excluded): {findings}"
        )
        # Control: the real espalier file's handler is still flagged — the
        # exclusion is _vendor-scoped, not a blanket off-switch.
        assert any(p.startswith("espalier/real_mod.py") for p in findings), (
            f"exclusion suppressed a real espalier finding too: {findings}"
        )


# ---------------------------------------------------------------------------
# TP-58 sub-task 1-B — three-construct split + hook-entrypoint exemption
# ---------------------------------------------------------------------------


def _scan_with_kind(tmp_path, body: str, rel_path: str):
    """Helper: write ``body`` to ``tmp_path/rel_path`` and run scan_file
    against it, returning the list of Finding records.
    """
    checker = _load_checker()
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return checker.scan_file(target, rel_path)


class TestScannerCatchesBaseException:
    """Three-construct split + hook-entrypoint exemption (TP-58 1-B).

    The scanner now classifies each broad handler as ``bare`` /
    ``exception`` / ``baseexception`` rather than collapsing them.
    BaseException at hook entrypoints is EXEMPT because Claude Code's
    hook protocol treats exit 1 as 'hook bug — allow the tool call',
    which is the opposite of the deny-on-uncertainty contract a guard
    hook needs; catching BaseException there is the correct form, not
    a code smell to suppress.
    """

    BARE = "try:\n    x=1\nexcept:\n    pass\n"
    EXC = "try:\n    x=1\nexcept Exception:\n    pass\n"
    BASE = "try:\n    x=1\nexcept BaseException:\n    pass\n"

    def test_bare_except_flagged_in_non_hook(self, tmp_path):
        findings = _scan_with_kind(tmp_path, self.BARE, "espalier/m.py")
        assert len(findings) == 1
        assert findings[0].kind == "bare"

    def test_exception_flagged_in_non_hook(self, tmp_path):
        findings = _scan_with_kind(tmp_path, self.EXC, "espalier/m.py")
        assert len(findings) == 1
        assert findings[0].kind == "exception"

    def test_baseexception_flagged_outside_hooks(self, tmp_path):
        findings = _scan_with_kind(tmp_path, self.BASE, "espalier/m.py")
        assert len(findings) == 1
        assert findings[0].kind == "baseexception"

    def test_baseexception_exempt_in_hook_dir(self, tmp_path):
        """Hook entrypoint exemption: BaseException at deny-on-
        uncertainty hook sites is the correct form, not a smell."""
        findings = _scan_with_kind(
            tmp_path, self.BASE, "tools/cc/hooks/example.py",
        )
        assert findings == []

    def test_baseexception_exempt_in_ci_guard(self, tmp_path):
        findings = _scan_with_kind(
            tmp_path, self.BASE, "tools/cc/ci_guard.py",
        )
        assert findings == []

    def test_exception_in_hook_still_flagged(self, tmp_path):
        """Only BaseException is exempt at hook sites; ordinary
        Exception catches still need annotation."""
        findings = _scan_with_kind(
            tmp_path, self.EXC, "tools/cc/hooks/example.py",
        )
        assert len(findings) == 1
        assert findings[0].kind == "exception"

    def test_bare_in_hook_still_flagged(self, tmp_path):
        """bare ``except:`` is never exempt — it aliases BaseException
        without name-binding and has no legitimate use case."""
        findings = _scan_with_kind(
            tmp_path, self.BARE, "tools/cc/hooks/example.py",
        )
        assert len(findings) == 1
        assert findings[0].kind == "bare"

    def test_noqa_skips_finding(self, tmp_path):
        body = (
            "try:\n"
            "    x=1\n"
            "except BaseException:  # noqa: BLE001\n"
            "    pass\n"
        )
        findings = _scan_with_kind(tmp_path, body, "espalier/m.py")
        assert findings == []

    def test_hook_entrypoint_files_cardinality_pinned(self):
        """HOOK_ENTRYPOINT_FILES MUST contain exactly the enumerated
        harness-internal helpers. Widening this list without adding
        the new file's entrypoint discipline is the failure shape —
        pin the cardinality so a silent addition trips this test.
        """
        checker = _load_checker()
        expected = frozenset({
            "tools/cc/ci_guard.py",
            "tools/cc/cognitive_blueprint.py",
            "tools/cc/execution_plan.py",
            "tools/cc/reflect_protocol.py",
            "tools/cc/statusline.py",
            "tools/cc/session_resume.py",
        })
        actual = frozenset(checker.HOOK_ENTRYPOINT_FILES)
        assert actual == expected, (
            "HOOK_ENTRYPOINT_FILES drifted from pinned set.\n"
            f"  Added: {sorted(actual - expected)}\n"
            f"  Removed: {sorted(expected - actual)}"
        )

    @pytest.mark.parametrize("rel_path", [
        "tools/cc/cognitive_blueprint.py",
        "tools/cc/execution_plan.py",
        "tools/cc/reflect_protocol.py",
        "tools/cc/statusline.py",
        "tools/cc/session_resume.py",
    ])
    def test_baseexception_exempt_in_widened_helper_files(
        self, rel_path, tmp_path,
    ):
        """Harness-internal helpers called from hook entrypoints share
        the deny-on-uncertainty contract; their BaseException catches
        are exempt too."""
        findings = _scan_with_kind(tmp_path, self.BASE, rel_path)
        assert findings == []
