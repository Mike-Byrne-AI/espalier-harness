"""TP-97: plan_guard adopter exempt_prefixes (espalier.toml) contract.

Adopters opt into ergonomics for conventional source roots (src/, lib/)
via flat top-level `plan_exempt_prefixes = [...]` in espalier.toml.
Discipline-is-the-product framing is preserved as the default (strict);
customization-is-expected gets a concrete mechanism that does NOT
require MAINTENANCE_MODE.

These six tests pin:
- empty TOML → default EXEMPT_PREFIXES still apply
- valid flat prefix → matching path exempt; non-matching root file not exempt
- invalid prefix (absolute, traversal, missing slash) → strict fallback +
  stderr advisory
- malformed TOML → strict fallback + stderr advisory
- zero-espalier-imports contract on plan_guard.py preserved
- adopter config and harness self-host carve-out are independent sources
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from tests._hook_assertions import assert_hook_allowed, assert_hook_denied

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"


def _run_plan_guard_edit(
    file_path: str,
    tmp_path: Path,
    *,
    espalier_toml: str | None = None,
) -> subprocess.CompletedProcess:
    """Run plan_guard.py with an Edit tool event under tmp_path.

    No execution plan is staged in cc/ — only the exempt-prefix
    mechanism can authorize the write.
    """
    if espalier_toml is not None:
        (tmp_path / "espalier.toml").write_text(espalier_toml, encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    payload = {"tool_name": "Edit", "tool_input": {"file_path": file_path}}
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "plan_guard.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env, encoding="utf-8",
    )


class TestPlanGuardAdopterConfig:
    """TP-97 contract on espalier.toml plan_exempt_prefixes."""

    def test_empty_toml_preserves_default_exempt_set(self, tmp_path: Path):
        # No espalier.toml at all → adopter list is empty → default
        # behavior applies. Root-level .py files still require a plan.
        result = _run_plan_guard_edit("src/myapp/foo.py", tmp_path)
        assert_hook_denied(result, contains_reason="src/myapp/foo.py")

    def test_flat_prefix_exempts_matching_path(self, tmp_path: Path):
        # plan_exempt_prefixes = ["src/"] → src/myapp/foo.py exempt; a
        # root-level foo.py is NOT exempt (root .py extension rule).
        toml = 'plan_exempt_prefixes = ["src/"]\n'
        assert_hook_allowed(
            _run_plan_guard_edit("src/myapp/foo.py", tmp_path, espalier_toml=toml)
        )
        assert_hook_denied(
            _run_plan_guard_edit("foo.py", tmp_path, espalier_toml=toml),
            contains_reason="foo.py",
        )

    def test_root_source_sentinel_exempts_root_file(self, tmp_path: Path):
        # TP-264 3-A: `plan_exempt_prefixes = ["./"]` is the flat-layout escape
        # hatch. A root-level source file (app.py) is plan-required by default,
        # but exempt when the "./" sentinel is configured. Without the sentinel
        # branch "./" is a dead no-op (it can never startswith-match a bare root
        # filename), so the allow assertion is RED against the pre-fix hook.
        assert_hook_denied(
            _run_plan_guard_edit("app.py", tmp_path),
            contains_reason="app.py",
        )
        toml = 'plan_exempt_prefixes = ["./"]\n'
        assert_hook_allowed(
            _run_plan_guard_edit("app.py", tmp_path, espalier_toml=toml)
        )

    def test_root_source_sentinel_is_root_only(self, tmp_path: Path):
        # The "./" sentinel must not degrade into a blanket exemption: a nested
        # path is unaffected and still requires a plan (or its own prefix).
        toml = 'plan_exempt_prefixes = ["./"]\n'
        assert_hook_denied(
            _run_plan_guard_edit("pkg/deep.py", tmp_path, espalier_toml=toml),
            contains_reason="pkg/deep.py",
        )

    def test_root_source_sentinel_excludes_special_root_files(self, tmp_path: Path):
        # PLAN_REQUIRED_ROOT_FILES (setup.py, README.md, ...) are always
        # plan-required; the "./" sentinel does not exempt them.
        toml = 'plan_exempt_prefixes = ["./"]\n'
        assert_hook_denied(
            _run_plan_guard_edit("setup.py", tmp_path, espalier_toml=toml),
            contains_reason="setup.py",
        )

    def test_root_source_deny_hint_names_sentinel(self, tmp_path: Path):
        # TP-264 3-A-3: a denied root-level source file gets the targeted hint
        # naming the "./" sentinel + espalier.toml, not the generic src/ hint.
        result = _run_plan_guard_edit("app.py", tmp_path)
        assert_hook_denied(result, contains_reason='["./"]')
        assert_hook_denied(result, contains_reason="espalier.toml")

    def test_invalid_prefix_rejected_with_strict_fallback(self, tmp_path: Path):
        # Absolute path, .. traversal, missing trailing slash — any one
        # invalid entry should drop the whole list and write a stderr
        # advisory. The src/ entry, even though it is valid alongside,
        # is dropped too (strict fallback per pack spec).
        for invalid_toml in (
            'plan_exempt_prefixes = ["/usr/local/", "src/"]\n',  # absolute
            'plan_exempt_prefixes = ["../escape/", "src/"]\n',  # traversal
            'plan_exempt_prefixes = ["src"]\n',  # missing trailing /
        ):
            result = _run_plan_guard_edit(
                "src/myapp/foo.py", tmp_path, espalier_toml=invalid_toml
            )
            assert_hook_denied(result, contains_reason="src/myapp/foo.py")
            assert "invalid plan_exempt_prefixes" in result.stderr, (
                f"expected stderr advisory for {invalid_toml!r}; got {result.stderr!r}"
            )

    def test_malformed_toml_falls_back_to_strict(self, tmp_path: Path):
        # Syntactically broken TOML → hook still exits 0 (allow channel
        # is the JSON deny payload, per the channel-XOR contract); stderr
        # carries the parse error advisory; strict mode applies.
        result = _run_plan_guard_edit(
            "src/myapp/foo.py",
            tmp_path,
            espalier_toml='plan_exempt_prefixes = ["src/" missing_close\n',
        )
        assert_hook_denied(result, contains_reason="src/myapp/foo.py")
        assert "malformed espalier.toml" in result.stderr, (
            f"expected malformed-TOML advisory; got {result.stderr!r}"
        )

    def test_zero_espalier_imports_contract_preserved(self):
        # tools/cc/hooks/plan_guard.py must never import espalier.* —
        # the hook scripts run standalone after harness deploy. A pure-Python
        # line scan flags any non-commented `from|import espalier`; this avoids
        # depending on `grep`, which is absent on stock Windows.
        plan_guard = HOOKS_DIR / "plan_guard.py"
        offenders = [
            f"{n}: {line}"
            for n, line in enumerate(
                plan_guard.read_text(encoding="utf-8").splitlines(), start=1
            )
            if re.search(r"^[^#]*(?:from|import)\s+espalier", line)
        ]
        assert not offenders, (
            "plan_guard.py must have ZERO espalier imports outside comments;\n"
            "matches:\n" + "\n".join(offenders)
        )

    def test_self_host_carve_out_independent_of_adopter_config(self, tmp_path: Path):
        # The two sources are independent: self-host carve-out comes
        # from _hook_utils.harness_exempt_prefixes (5-signal fingerprint
        # detection); adopter prefixes come from espalier.toml. Neither
        # leaks into the other. Running inside the actual self-host repo
        # gives access to (a); tmp_path with an espalier.toml verifies (b).
        sys.path.insert(0, str(HOOKS_DIR))
        import _hook_utils
        import plan_guard

        repo_root = Path(__file__).resolve().parent.parent
        assert _hook_utils.is_self_host_repo(repo_root), (
            "test runs inside the self-host repo by design"
        )
        self_host_prefixes = _hook_utils.harness_exempt_prefixes(repo_root)
        assert "espalier/" in self_host_prefixes, (
            f"self-host carve-out missing espalier/: {self_host_prefixes!r}"
        )

        (tmp_path / "espalier.toml").write_text(
            'plan_exempt_prefixes = ["src/"]\n', encoding="utf-8"
        )
        adopter = plan_guard._load_adopter_exempt_prefixes(tmp_path)
        assert adopter == ("src/",)
        assert "espalier/" not in adopter, (
            "espalier/ leaked into adopter list — must come from self-host only"
        )
        # tmp_path is not self-host (no espalier/, no pyproject etc.) →
        # harness_exempt_prefixes for tmp_path omits espalier/.
        tmp_self_host = _hook_utils.harness_exempt_prefixes(tmp_path)
        assert "espalier/" not in tmp_self_host, (
            "non-self-host tmp_path unexpectedly got espalier/ carve-out: "
            f"{tmp_self_host!r}"
        )


class TestAdopterDocFencedTomlSchema:
    """Every fenced ```toml block in adopter-visible docs must parse
    through the same path `_load_adopter_exempt_prefixes` uses: the
    top-level `plan_exempt_prefixes` key. Nested `[plan_guard]` table
    forms are a known silent-fallback class (TP-135) and must not
    appear in adopter-facing docs.

    Self-host-only docs (e.g. docs/external/cc-hook-protocol.md) are
    excluded — they are not deployed to adopters and may legitimately
    show implementation-side TOML shapes.
    """

    _ADOPTER_VISIBLE_DOCS = (
        "docs/QUICKSTART.md",
        "docs/TROUBLESHOOTING.md",
        "CLAUDE.md",
        "espalier/assets/docs/TROUBLESHOOTING.md",
    )

    def test_no_plan_guard_table_form_in_adopter_docs(self) -> None:
        import re

        repo_root = Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        fence_re = re.compile(r"```toml\s*\n(.*?)\n```", re.DOTALL)
        for rel in self._ADOPTER_VISIBLE_DOCS:
            path = repo_root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for block in fence_re.findall(text):
                if re.search(r"^\s*\[plan_guard\]", block, re.MULTILINE):
                    offenders.append(f"{rel}: [plan_guard] table form")
                if re.search(
                    r"^\s*exempt_prefixes\s*=", block, re.MULTILINE
                ) and not re.search(
                    r"^\s*plan_exempt_prefixes\s*=", block, re.MULTILINE
                ):
                    offenders.append(f"{rel}: bare exempt_prefixes key")
        assert not offenders, (
            "Adopter-visible docs contain fenced TOML blocks the hook "
            "parser silently ignores. The hook reads "
            "`plan_exempt_prefixes` at the top level only. Offenders: "
            f"{offenders}"
        )


class TestNoTomlParserRegexFallback:
    """TP-254 F6: on a Python < 3.11 hook interpreter without ``tomli`` (so
    ``_tomllib is None``), the adopter's ``plan_exempt_prefixes`` must still be
    honored via the stdlib regex fallback — not silently dropped, which forced
    every configured-exempt path back into strict plan-blocking + a per-write
    stderr advisory.

    RED against the pre-fix shape: with no parser the loader returned ``()``
    unconditionally, so these would see the empty tuple.
    """

    def test_regex_fallback_honors_prefixes_without_parser(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(HOOKS_DIR))
        import plan_guard

        (tmp_path / "espalier.toml").write_text(
            '# adopter comment\nplan_exempt_prefixes = ["src/", "lib/"]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(plan_guard, "_tomllib", None)
        got = plan_guard._load_adopter_exempt_prefixes(tmp_path)
        assert got == ("src/", "lib/"), (
            f"regex fallback dropped the exempt config under no-parser: {got!r}"
        )

    def test_regex_fallback_still_validates_bad_entries(self, tmp_path, monkeypatch):
        # The fallback feeds the SAME validator: an absolute-path entry must
        # still trigger strict fallback (empty tuple), not leak through.
        sys.path.insert(0, str(HOOKS_DIR))
        import plan_guard

        (tmp_path / "espalier.toml").write_text(
            'plan_exempt_prefixes = ["/etc/"]\n', encoding="utf-8",
        )
        monkeypatch.setattr(plan_guard, "_tomllib", None)
        assert plan_guard._load_adopter_exempt_prefixes(tmp_path) == ()

    def test_regex_fallback_ignores_commented_key(self, tmp_path, monkeypatch):
        # A fully-commented key must not be matched (full-line comments stripped).
        sys.path.insert(0, str(HOOKS_DIR))
        import plan_guard

        (tmp_path / "espalier.toml").write_text(
            '# plan_exempt_prefixes = ["src/"]\n', encoding="utf-8",
        )
        monkeypatch.setattr(plan_guard, "_tomllib", None)
        assert plan_guard._load_adopter_exempt_prefixes(tmp_path) == ()
