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

import pytest

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
        # invalid entry should drop the whole list and say so once a session
        # per distinct entry (a say_once record, with this stderr line as its
        # debug copy -- the hook exits 0, so stderr alone reaches nobody).
        # The src/ entry, even though it is valid alongside, is dropped too
        # (strict fallback per pack spec).
        for invalid_toml in (
            'plan_exempt_prefixes = ["/usr/local/", "src/"]\n',  # absolute
            'plan_exempt_prefixes = ["../escape/", "src/"]\n',  # traversal
            'plan_exempt_prefixes = ["src"]\n',  # missing trailing /
        ):
            result = _run_plan_guard_edit(
                "src/myapp/foo.py", tmp_path, espalier_toml=invalid_toml
            )
            assert_hook_denied(result, contains_reason="src/myapp/foo.py")
            # TP-472 2-C (DEF-1022): the deny itself names the cause.
            assert_hook_denied(result, contains_reason="invalid plan_exempt_prefixes entry")
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
        assert_hook_denied(result, contains_reason="malformed espalier.toml")  # TP-472 2-C
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


class TestTomliBelowOneOneTextHandleRetry:
    """DEF-871: tomli below 1.1 types ``load()`` for a text handle and raises
    ``TypeError`` on the binary one ``_hook_utils.read_toml_table`` opens.
    Measured 2026-10-08 on CPython 3.10 with tomli 1.0.4 against the source
    hook on an init'd Node tree: with any ``espalier.toml`` present every
    source write reached plan_guard's crash handler and was denied as the
    guard's internal error; tomli 1.2.3 read the binary handle. The floor in
    pyproject.toml is ``tomli>=2.0`` now, and the reader retries a
    ``TypeError`` with a text handle for an interpreter that has an older one
    anyway.

    The parser here is a stub reproducing tomli 1.0's documented behaviour,
    not the library (the suite runs on one interpreter); the real one was
    driven once at landing (TP-472's Landing stanza says which).

    RED against the pre-fix reader: delete the ``except TypeError`` retry and
    the loader returns ``()`` while ``main`` denies with the internal error.
    """

    @staticmethod
    def _text_only_parser(real):
        class _Tomli10:
            @staticmethod
            def load(fh):
                if "b" in getattr(fh, "mode", ""):
                    raise TypeError("a bytes-like object is required, not 'str'")
                return real.loads(fh.read())

        return _Tomli10()

    def test_loader_honors_prefixes_under_a_text_only_parser(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(HOOKS_DIR))
        import plan_guard

        real = plan_guard._tomllib
        assert real is not None, "this interpreter has no TOML parser for the stub to delegate to"
        (tmp_path / "espalier.toml").write_text('plan_exempt_prefixes = ["src/"]\n', encoding="utf-8")
        monkeypatch.setattr(plan_guard, "_tomllib", self._text_only_parser(real))
        assert plan_guard._load_adopter_exempt_prefixes(tmp_path) == ("src/",)

    def test_main_allows_rather_than_failing_closed(self, tmp_path, monkeypatch, capsys):
        # The whole-hook shape of the same defect: the TypeError used to ride
        # to main's crash handler, which denies EVERY write as an internal
        # error -- the 3.10 adopter who followed the remedy and created the
        # file lost every source write.
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)
        sys.path.insert(0, str(HOOKS_DIR))
        import importlib
        if "plan_guard" in sys.modules:
            plan_guard = importlib.reload(sys.modules["plan_guard"])
        else:
            import plan_guard  # type: ignore[import-not-found]

        real = plan_guard._tomllib
        assert real is not None
        (tmp_path / "espalier.toml").write_text('plan_exempt_prefixes = ["src/"]\n', encoding="utf-8")
        (tmp_path / "src").mkdir()
        monkeypatch.setattr(plan_guard, "_tomllib", self._text_only_parser(real))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "src" / "x.py")}}
        monkeypatch.setattr(plan_guard._hook_utils, "read_stdin_safely", lambda: payload)

        rc = plan_guard.main()
        captured = capsys.readouterr()
        assert rc == 0
        assert "plan_guard internal error" not in captured.out, captured.out
        assert "plan_guard crashed" not in captured.err, captured.err
        if captured.out.strip():
            decision = json.loads(captured.out)["hookSpecificOutput"]["permissionDecision"]
            assert decision != "deny", captured.out


def _reason_of(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


# The eight shapes DEF-1022's probe drives, each with the cause its deny must
# name, plus the two the row's remedy misdirected on: a valid list that does
# not cover the path, and a file that sets nothing.
_CONFIG_SHAPES = [
    ('plan_exempt_prefixes = ["src"]\n', "must end with '/'"),
    ('plan_exempt_prefixes = ["src/", "notes.txt"]\n', "must end with '/'"),
    ('plan_exempt_prefix = ["src/"]\n', "did you mean `plan_exempt_prefixes`"),
    ('exempt_prefixes = ["src/"]\n', "top-level flat key"),
    ('[plan_guard]\nplan_exempt_prefixes = ["src/"]\n', "top-level flat key"),
    ('[tool.espalier]\nplan_exempt_prefixes = ["src/"]\n', "sits under [tool.espalier]"),
    ('plan_required_prefixes = ["docs/"]\n', "has no required-list setting"),
    ('plan_exempt_prefixes = ["src/"\n', "malformed espalier.toml"),
    ('plan_exempt_prefixes = ["src/"]\n', 'is set to ["src/"] and does not cover `lib/x.py`'),
    ('# nothing set\n', "sets no `plan_exempt_prefixes`"),
    # Three tables deep: the walk's declared depth (the 3-A review's surviving
    # mutation cut it to one and nothing noticed).
    ('[a.b.c]\nplan_exempt_prefixes = ["src/"]\n', "sits under [a.b.c]"),
]


class TestTheDenySaysWhatItDidWithTheKey:
    """TP-472 2-C (DEF-1022). Before this, a plan-required deny under a
    misspelled, misplaced, malformed or non-covering ``plan_exempt_prefixes``
    was byte-identical to the no-config deny, and its remedy told the adopter
    to set the key they had just set (measured 2026-10-07 and 2026-10-08:
    doctor named the misspelling; the deny did not). The loader's explanation
    reached only stderr, which an exit-0 hook sends to the debug log alone.

    Every shape must change the deny against the no-config baseline AND name
    its cause. RED against the pre-fix hook, and when ``_adopter_exempt_note``
    returns ``""``.
    """

    @pytest.mark.parametrize("toml,cause", _CONFIG_SHAPES, ids=[c[:24] for _, c in _CONFIG_SHAPES])
    def test_the_deny_differs_from_the_baseline_and_names_the_cause(self, tmp_path, toml, cause):
        baseline = _run_plan_guard_edit("lib/x.py", tmp_path)
        assert_hook_denied(baseline, contains_reason="lib/x.py")
        assert "sets no `plan_exempt_prefixes`" not in _reason_of(baseline)
        result = _run_plan_guard_edit("lib/x.py", tmp_path, espalier_toml=toml)
        assert_hook_denied(result, contains_reason="lib/x.py")
        reason = _reason_of(result)
        assert reason != _reason_of(baseline), reason
        assert cause in reason, (cause, reason)
        # The note precedes the knob's hint, so the reader meets what the hook
        # did before being told what to set.
        assert reason.index(cause) < reason.index("Adopter source roots"), reason

    def test_a_listed_root_file_is_not_said_to_be_uncovered(self, tmp_path):
        # README.md is in PLAN_REQUIRED_ROOT_FILES: no prefix exempts it, so the
        # note must not read as "cover it", which cannot work (the explainer's
        # label says the same: tests/test_explain_path.py).
        result = _run_plan_guard_edit("README.md", tmp_path, espalier_toml='plan_exempt_prefixes = ["src/"]\n')
        assert_hook_denied(result, contains_reason="README.md")
        reason = _reason_of(result)
        assert "always gates" in reason and "cannot exempt it" in reason, reason
        assert "does not cover" not in reason, reason

    def test_a_nested_listed_name_is_covered_like_any_path(self, tmp_path):
        # `lib/README.md` is not a ROOT file: the always-gated branch is for
        # the root roster alone, and a prefix covers a nested one (the 3-A
        # review's surviving mutation dropped the parent check).
        result = _run_plan_guard_edit("lib/README.md", tmp_path, espalier_toml='plan_exempt_prefixes = ["src/"]\n')
        assert_hook_denied(result, contains_reason="does not cover `lib/README.md`")
        assert "always gates" not in _reason_of(result)

    def test_a_tree_without_a_config_file_reads_as_before(self, tmp_path):
        # No note, and the hint names what exists: there is no file to
        # uncomment a line in, so it says to create one (or run the upgrade
        # that writes the skeleton).
        reason = _reason_of(_run_plan_guard_edit("lib/x.py", tmp_path))
        assert "sets no `plan_exempt_prefixes`" not in reason and "plan_exempt_prefixes` is set" not in reason
        assert "(attempted: lib/x.py) Adopter source roots: create espalier.toml" in reason, reason
        assert "uncomment" not in reason, reason
        root_reason = _reason_of(_run_plan_guard_edit("app.py", tmp_path))
        assert "create espalier.toml" in root_reason and '["./"]' in root_reason, root_reason

    def test_the_hint_says_uncomment_only_when_the_file_exists(self, tmp_path):
        with_file = _reason_of(_run_plan_guard_edit("lib/x.py", tmp_path, espalier_toml="# nothing set\n"))
        assert "uncomment `plan_exempt_prefixes" in with_file and "create espalier.toml" not in with_file, with_file
        assert (tmp_path / "espalier.toml").is_file()
        (tmp_path / "espalier.toml").unlink()
        without = _reason_of(_run_plan_guard_edit("lib/x.py", tmp_path))
        assert "create espalier.toml" in without and "uncomment" not in without, without


class TestTheNearMissThresholdClearsEveryEngineKey:
    """The did-you-mean arm reads an unknown key within ``_NEAR_MISS_RATIO`` of
    `plan_exempt_prefixes` as a misspelling. That is only safe while no
    legitimate key sits inside the distance: a future `plan_exempt_paths` or
    `plan_gate_exempt_prefixes` would be told it is a typo. Derived over every
    HarnessConfig field and every foreign key, so a sibling key reds here
    before it mis-advises an adopter (the 3-A review)."""

    def test_no_config_key_is_within_the_did_you_mean_distance(self):
        import dataclasses
        import difflib

        from espalier.config import FOREIGN_KEYS
        from espalier.models import HarnessConfig

        sys.path.insert(0, str(HOOKS_DIR))
        import plan_guard

        key = plan_guard._ADOPTER_CONFIG_KEY
        names = [f.name for f in dataclasses.fields(HarnessConfig)] + list(FOREIGN_KEYS)
        ratios = {
            n: round(difflib.SequenceMatcher(None, n, key).ratio(), 3) for n in names if n != key
        }
        close = {n: r for n, r in ratios.items() if r >= plan_guard._NEAR_MISS_RATIO}
        assert not close, (
            f"{close} sit within the did-you-mean distance of `{key}`: the hook would call a "
            "legitimate setting a misspelling. Raise _NEAR_MISS_RATIO or name the key in the "
            "hook's own branch (as plan_required_prefixes is)."
        )
        assert ratios and max(ratios.values()) < plan_guard._NEAR_MISS_RATIO
