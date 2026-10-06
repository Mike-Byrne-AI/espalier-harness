"""TP-34: settings profile contract tests.

Pins the four-profile contract: ``minimal``, ``workflow``,
``self-host``, ``full`` each define a complete ``settings.json``
shape. This file parametrizes on all four so the contract for
each is pinned independently. TP-40 added ``self-host``. Without
this contract a refactor of the profile renderer (or a new field
added to one profile but not the others) could silently change
the deployed settings shape for any single profile, and the
regression would only surface when an adopter using that profile
hit the differing behavior.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from espalier import cli
from espalier.settings_profiles import (
    DEFAULT_PROFILE,
    PROFILES,
    deny_defaults,
    get_profile,
    powershell_twins,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)


def _run_init(repo: Path, *, profile: str | None = None) -> None:
    cmd = [sys.executable, "-m", "espalier.cli", "init", str(repo)]
    if profile is not None:
        cmd.extend(["--profile", profile])
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, capture_output=True)


def _read_settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


# Module-level constants

class TestProfileModule:
    def test_profiles_exposes_four_names(self):
        # TP-40: 3 -> 4 with addition of self-host.
        assert sorted(PROFILES.keys()) == ["full", "minimal", "self-host", "workflow"]

    def test_default_profile_is_workflow(self):
        assert DEFAULT_PROFILE == "workflow"

    def test_get_profile_raises_on_unknown(self):
        with pytest.raises(ValueError):
            get_profile("nonexistent")

    def test_deny_defaults_no_longer_arms_the_read_deny_prompt(self):
        """The sensitive-path guarantee MOVED to the hook layer; it did not go.

        This test used to assert `".env" in " ".join(deny_defaults())` -- a pin
        on the IMPLEMENTATION (the strings live in this tuple), not on the
        PROPERTY (sensitive reads are refused). The property is now enforced by
        `write_guard.check_secret_path_access`, and
        `TestSecretPathAccess` in tests/test_write_guard.py is its pin.

        What this asserts instead is the reason for the move: emitting ANY
        `Read()` deny rule arms Claude Code's static-resolvability check, which
        raises an interactive permission prompt on every Bash command whose
        read set cannot be proven -- unsuppressable by `allow` or by
        bypassPermissions, because deny outranks both. Re-adding one here would
        silently restore the stalls the removal was measured to fix, so the
        absence is the contract.
        """
        offenders = [rule for rule in deny_defaults() if rule.startswith("Read(")]
        assert not offenders, (
            "deny_defaults() emits Read() deny rule(s) again: "
            f"{offenders}. Any Read() rule re-arms Claude Code's "
            "static-resolvability prompt on ordinary Bash commands, defeating "
            "bypassPermissions. Deny sensitive READS in "
            "write_guard.check_secret_path_access instead."
        )

    def test_deny_defaults_pins_pipe_to_shell(self):
        """TP-152 C-1: the curl|sh / wget|sh deny rules had no pinning test —
        a refactor of _DENY_DEFAULTS could silently drop them, removing the
        permission-layer half of the pipe-to-shell defense. Pin them."""
        deny = deny_defaults()
        assert "Bash(curl * | sh)" in deny
        assert "Bash(wget * | sh)" in deny

    def test_no_deny_default_ends_in_a_star_or_puts_one_right_after_a_slash(self):
        """In a `Bash(...)` rule the text before the first `*` is matched as
        written and the star matches any text; there is no way to spell a
        literal asterisk (the platform's permissions page, read 2026-09-29).
        Text AFTER a star is still required -- driven 2026-09-29: `curl
        --version` runs under `Bash(curl * | sh)`, so the two fetch-pipe rules
        deny the pipe-to-sh family and nothing else -- but a rule that ENDS in
        a star denies everything that begins with its prefix. `Bash(rm -rf /*)`,
        written for the root glob wipe, denied EVERY recursive delete of an
        absolute path -- a temp build directory, a scratch tree -- in every
        permission mode, bypass included (deny outranks the mode), with no
        reason shown and right after the CP-RMRF speed bump had promised
        passage on re-issue. Driven on the self-host tree 2026-09-28 and
        2026-09-29, three probes. The wipe it was written for is walled at the
        hook layer (`write_guard`'s catastrophic-rm classifier reads the root
        glob as the root itself; tests/test_write_guard.py pins it), so the
        rule was redundant for its target and over-broad for everything else.
        Red at HEAD before the fix; the rule is retired below. Two pins: the
        mechanism (a trailing star) and the house rule (a star right after a
        path separator is a path prefix wherever it sits)."""
        trailing = [rule for rule in deny_defaults() if rule.endswith("*)")]
        assert not trailing, (
            f"deny default(s) end in a star: {trailing}. A trailing star is a "
            "prefix match over everything that begins with the text before it; "
            "deny the exact spelling, or wall the class in write_guard."
        )
        after_slash = [rule for rule in deny_defaults() if "/*" in rule]
        assert not after_slash, (
            "deny default(s) put a wildcard right after a path separator: "
            f"{after_slash}. That is a path prefix wherever it sits; deny the "
            "exact spelling, or wall the class in write_guard."
        )

    def test_the_trailing_star_rm_rule_is_retired_and_the_exact_root_rule_stays(self):
        """The retired rule is remembered, not forgotten: `doctor`,
        `merge-settings` and the `upgrade` preview name it on a settings.json
        that still carries it (the merge never removes an operator's rule, so
        the delete is theirs), and its reason is operator-facing text -- 7-bit
        ASCII, the engine's rule for anything it prints. The exact root rule
        matches only the literal `rm -rf /` and stays."""
        from espalier.settings_profiles import retired_deny_rules

        deny = deny_defaults()
        retired = {rule: (shipped, why) for rule, shipped, why in retired_deny_rules()}
        assert "Bash(rm -rf /*)" not in deny
        assert "Bash(rm -rf /*)" in retired, retired
        assert "Bash(rm -rf /)" in deny, "the exact root rule is harmless and stays"
        assert not set(retired) & set(deny), "a retired rule cannot also be a default"
        for rule, (shipped, why) in retired.items():
            assert why and why.isascii(), (rule, why)
            # The provenance contract: a row names the last version whose init
            # WROTE the rule (a failure-mode review: without it a merely bad
            # rule could be filed as "retired" and an operator's own rule
            # accused). A release-shaped token, never empty.
            assert re.fullmatch(r"\d+\.\d+\.\d+(?:[ab]\d+|rc\d+)?", shipped), (rule, shipped)

    def test_self_host_is_superset_of_workflow_allows(self):
        """TP-40: self-host extends workflow, never narrows it."""
        wf_allows = set(get_profile("workflow").allow)
        sh_allows = set(get_profile("self-host").allow)
        missing = wf_allows - sh_allows
        assert not missing, (
            f"self-host must be a superset of workflow allows; missing: {missing}"
        )

    def test_self_host_is_strict_subset_of_full_breadth(self):
        """TP-40: self-host narrower than full — no bare `python *` or `pip *`."""
        sh_allows = set(get_profile("self-host").allow)
        assert "Bash(python *)" not in sh_allows
        assert "Bash(python3 *)" not in sh_allows
        assert "Bash(pip *)" not in sh_allows
        assert "Bash(git *)" not in sh_allows  # narrower git inspection only

    def test_self_host_adds_espalier_subcommand_allows(self):
        """TP-40: self-host's reason for existence — harness self-edit."""
        sh_allows = set(get_profile("self-host").allow)
        assert "Bash(python -m espalier *)" in sh_allows
        assert "Bash(python3 -m espalier *)" in sh_allows


# Per-profile generated-settings contract (parametrized)

@pytest.mark.integration
@pytest.mark.parametrize("profile_name", ["minimal", "workflow", "self-host", "full"])
class TestProfile:
    def test_has_schema(self, tmp_path, profile_name):
        _git_init(tmp_path)
        _run_init(tmp_path, profile=profile_name)
        settings = _read_settings(tmp_path)
        assert "$schema" in settings, (
            f"Profile {profile_name!r} settings.json missing $schema"
        )
        assert settings["$schema"].startswith("https://"), (
            f"$schema must be an HTTPS URL: {settings['$schema']!r}"
        )

    def test_no_unknown_top_level_keys(self, tmp_path, profile_name):
        """TP-152 C-3: the disableSkillShellExecution omission contract rested
        on prose + an indirect $schema test. Pin the emitted top-level key set
        directly: any key outside the deliberate harness set (a non-schema key
        like disableSkillShellExecution, or a typo) must not appear."""
        _git_init(tmp_path)
        _run_init(tmp_path, profile=profile_name)
        settings = _read_settings(tmp_path)
        known = {"$schema", "_espalier_managed", "permissions", "hooks",
                 "statusLine"}
        unknown = set(settings.keys()) - known
        assert not unknown, (
            f"Profile {profile_name!r} emits unknown top-level key(s): "
            f"{sorted(unknown)} — only {sorted(known)} are deliberate."
        )

    def test_has_deny_rules(self, tmp_path, profile_name):
        _git_init(tmp_path)
        _run_init(tmp_path, profile=profile_name)
        settings = _read_settings(tmp_path)
        deny = settings.get("permissions", {}).get("deny", [])
        assert deny, (
            f"Profile {profile_name!r} has empty deny list — governance "
            f"defaults must still deny the dangerous bash shapes."
        )
        deny_str = " ".join(deny)
        # The pipe-to-shell and catastrophic-rm shapes stay at the permission
        # layer: the prompt-arming condition names `Read()` specifically, so
        # Bash deny rules cost nothing.
        for dangerous in ("curl", "rm -rf /"):
            assert dangerous in deny_str, (
                f"Profile {profile_name!r} does not deny {dangerous!r}."
            )
        # Sensitive-path READS moved to write_guard (see
        # TestProfileModule::test_deny_defaults_no_longer_arms_the_read_deny_prompt).
        # A Read() rule here would re-arm the permission prompt that removal fixed.
        assert not [r for r in deny if r.startswith("Read(")], (
            f"Profile {profile_name!r} emits a Read() deny rule; that re-arms "
            "Claude Code's static-resolvability prompt under bypassPermissions."
        )

    def test_allow_matches_profile(self, tmp_path, profile_name):
        _git_init(tmp_path)
        _run_init(tmp_path, profile=profile_name)
        settings = _read_settings(tmp_path)
        allow = settings.get("permissions", {}).get("allow", [])
        # An empty repository's fingerprint is not a Python one, so the
        # profile's Python-only rules are not rendered (DEF-965).
        profile = PROFILES[profile_name]
        expected = [r for r in profile.allow if r not in profile.python_only]
        if not cli._render_host_is_posix():
            # A Windows render carries the PowerShell twin of every Bash rule;
            # TestPowerShellTwinsFollowTheRenderHost pins the rule itself.
            expected += list(powershell_twins(expected))
        assert set(allow) == set(expected), (
            f"Profile {profile_name!r} allow mismatch.\n"
            f"Got:      {sorted(allow)}\n"
            f"Expected: {sorted(expected)}"
        )

    def test_hooks_present(self, tmp_path, profile_name):
        _git_init(tmp_path)
        _run_init(tmp_path, profile=profile_name)
        settings = _read_settings(tmp_path)
        hooks = settings.get("hooks", {})
        assert hooks, (
            f"Profile {profile_name!r} has no hooks. Hooks are "
            f"profile-independent governance."
        )
        expected_events = {
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "PostToolUse", "Stop", "ConfigChange", "PostCompact",
        }
        assert expected_events.issubset(set(hooks.keys())), (
            f"Profile {profile_name!r} missing hook events: "
            f"{expected_events - set(hooks.keys())}"
        )


# Profile-specific posture invariants

@pytest.mark.integration
class TestMinimalSpecific:
    def test_minimal_has_no_write(self, tmp_path):
        _git_init(tmp_path)
        _run_init(tmp_path, profile="minimal")
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        assert "Write" not in allow, "minimal profile must NOT allow Write."

    def test_minimal_has_no_bash_allows(self, tmp_path):
        _git_init(tmp_path)
        _run_init(tmp_path, profile="minimal")
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        bash_allows = [a for a in allow if a.startswith("Bash(")]
        assert not bash_allows, (
            f"minimal profile must NOT allow any Bash. Found: {bash_allows}"
        )


@pytest.mark.integration
class TestFullSpecific:
    def test_full_preserves_v060_broad_bash(self, tmp_path):
        _git_init(tmp_path)
        _run_init(tmp_path, profile="full")
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        for expected in (
            "Bash(python *)", "Bash(python3 *)", "Bash(pip *)", "Bash(git *)",
        ):
            assert expected in allow, (
                f"full profile must preserve v0.6.x broad bash. "
                f"Missing: {expected!r}"
            )


# Profile selection precedence

@pytest.mark.integration
class TestDefaultProfile:
    def test_init_without_flag_uses_workflow(self, tmp_path):
        _git_init(tmp_path)
        # A Python repository: the pytest rule renders for a Python
        # fingerprint only (DEF-965).
        (tmp_path / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        _run_init(tmp_path)
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        assert "Write" in allow, "Default profile should allow Write."
        assert "Bash(pytest *)" in allow, (
            "Default profile (workflow) should narrowly allow pytest."
        )
        assert "Bash(pip *)" not in allow, (
            "Default profile (workflow) must NOT allow broad pip — that's the full profile."
        )

    def test_espalier_toml_default_profile_honored(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "espalier.toml").write_text(
            'default_profile = "minimal"\n', encoding="utf-8"
        )
        _run_init(tmp_path)
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        assert "Write" not in allow, (
            "espalier.toml default_profile=minimal was ignored"
        )

    def test_cli_flag_overrides_toml(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "espalier.toml").write_text(
            'default_profile = "minimal"\n', encoding="utf-8"
        )
        _run_init(tmp_path, profile="full")
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        assert "Bash(pip *)" in allow, (
            "CLI --profile full should override espalier.toml minimal"
        )

    def test_self_host_via_toml_rejected(self, tmp_path):
        """``default_profile = "self-host"`` in espalier.toml without the
        CLI flag must be rejected.

        Pre-fix (post-v0.6.5 adversarial review finding): the precedence
        ``cli_profile or cfg_profile or DEFAULT_PROFILE`` allowed
        espalier.toml to select self-host without the CLI flag, widening
        permissions silently for every downstream operator. The docstring
        in ``espalier/settings_profiles.py`` promises "Opt-in only via
        ``espalier init --profile self-host``"; this test pins the
        promise.
        """
        _git_init(tmp_path)
        (tmp_path / "espalier.toml").write_text(
            'default_profile = "self-host"\n', encoding="utf-8"
        )
        cmd = [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)]
        result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True)
        assert result.returncode != 0, (
            "espalier.toml default_profile=self-host without --profile flag "
            "should be rejected; got exit 0"
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert "self-host" in stderr and "opt-in" in stderr, (
            f"Error message must name the constraint; got stderr={stderr!r}"
        )

    def test_self_host_via_cli_still_works(self, tmp_path):
        """The CLI flag remains the supported way to opt in to self-host,
        even when espalier.toml has a non-self-host default."""
        _git_init(tmp_path)
        (tmp_path / "espalier.toml").write_text(
            'default_profile = "minimal"\n', encoding="utf-8"
        )
        _run_init(tmp_path, profile="self-host")
        allow = _read_settings(tmp_path).get("permissions", {}).get("allow", [])
        assert any("python -m espalier" in a for a in allow), (
            "CLI --profile self-host should still produce the self-host allow list"
        )

    @pytest.mark.parametrize(
        "toml_value",
        [
            "Self-Host",    # title case
            "SELF-HOST",    # upper case
            "self-Host",    # mixed
            " self-host ",  # whitespace padding
            "Self-host",    # capitalized first word
        ],
    )
    def test_self_host_case_variant_in_toml_rejected_with_named_error(self, tmp_path, toml_value):
        """Post-v0.6.6: case- and whitespace-variants of ``self-host`` in
        espalier.toml must hit the explicit "must be opt-in via CLI"
        error, not the generic ``get_profile`` "Unknown profile" error.

        Pre-fix the comparison was raw equality (``cfg_profile ==
        "self-host"``); a casing variant silently fell through to
        ``get_profile`` which raised a confusing "Unknown profile
        'Self-Host'" instead of telling the operator the actual rule.
        """
        _git_init(tmp_path)
        (tmp_path / "espalier.toml").write_text(
            f'default_profile = "{toml_value}"\n', encoding="utf-8"
        )
        cmd = [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)]
        result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True)
        assert result.returncode != 0, (
            f"espalier.toml default_profile={toml_value!r} without --profile flag "
            f"should be rejected; got exit 0"
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert "self-host" in stderr and "opt-in" in stderr, (
            f"case-variant {toml_value!r} must hit the named opt-in error, not "
            f"the generic 'Unknown profile' error; got stderr={stderr!r}"
        )

    def test_self_host_rejection_stderr_exact_text(self, tmp_path):
        """Pin the canonical error message so downstream tooling that
        parses stderr can rely on the exact string. Refactors that
        change the wording must update this test deliberately."""
        _git_init(tmp_path)
        (tmp_path / "espalier.toml").write_text(
            'default_profile = "self-host"\n', encoding="utf-8"
        )
        cmd = [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)]
        result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True)
        stderr = result.stderr.decode("utf-8", errors="replace")
        expected = (
            "Error: profile 'self-host' must be opt-in via --profile self-host "
            "on the CLI; espalier.toml default_profile cannot select it."
        )
        assert expected in stderr, (
            f"canonical error message has drifted; expected substring "
            f"{expected!r}; got stderr={stderr!r}"
        )


# ── DEF-714: every `python ...` allow rule ships under BOTH interpreter names ──
#
# Stock macOS has no `python`, many Windows installs no `python3`, and the rule
# is for whatever the adopter's Claude types there. The pytest rule shipped in
# the workflow and self-host profiles under `python` alone; the espalier and
# tools/cc pairs were the precedent. The contract is keyed on the leading
# INTERPRETER token and bucketed by the rest of the rule -- not on the `-m`
# shape the defect happened to have -- so every pair the profiles ship is
# pinned, in both directions, and a `python3`-only rule reds too. Presence of
# the pair the row found missing is asserted per profile, so an edit that
# deletes both spellings cannot read as symmetric.

_PY_RULE = re.compile(r"^Bash\((python3?) (.+)\)$")


def _python_rules(allow) -> dict[tuple[str, str], str]:
    """{(interpreter, remainder): rule} for every `Bash(python[3] <rest>)` rule."""
    out = {}
    for rule in allow:
        m = _PY_RULE.match(rule)
        if m:
            out[(m.group(1), m.group(2))] = rule
    return out


def _twinless(rules, interpreter: str, twin: str) -> list[str]:
    return sorted(
        f"Bash({twin} {rest})" for (py, rest) in rules
        if py == interpreter and (twin, rest) not in rules
    )


class TestPythonRulesCarryBothInterpreters:
    @pytest.mark.parametrize("name", sorted(PROFILES))
    def test_every_python_rule_has_its_python3_twin(self, name):
        missing = _twinless(_python_rules(PROFILES[name].allow), "python", "python3")
        assert not missing, f"{name}: python rules without a python3 twin: {missing}"

    @pytest.mark.parametrize("name", sorted(PROFILES))
    def test_every_python3_rule_has_its_python_twin(self, name):
        missing = _twinless(_python_rules(PROFILES[name].allow), "python3", "python")
        assert not missing, f"{name}: python3 rules without a python twin: {missing}"

    @pytest.mark.parametrize("name", ["workflow", "self-host"])
    def test_the_pytest_pair_is_present_where_the_row_found_it_missing(self, name):
        """Presence, not just symmetry: deleting both spellings would pass the
        rows above (code review, 2026-09-07)."""
        rules = _python_rules(PROFILES[name].allow)
        assert ("python", "-m pytest *") in rules and ("python3", "-m pytest *") in rules, rules

    def test_the_rule_shape_is_seen(self):
        """Earn the gate: the profiles DO carry python rules of more than one
        shape, so the rows above are not vacuously green over an empty set."""
        rests = {rest for name in PROFILES for (_, rest) in _python_rules(PROFILES[name].allow)}
        assert {"-m pytest *", "-m espalier *", "tools/cc/* *"} <= rests, rests

    @pytest.mark.parametrize("recorded, rest", [
        ("python -m unittest discover", "-m unittest *"),
        ("python3 -m unittest discover", "-m unittest *"),
        ("python run_tests.py -q", "run_tests.py *"),
        ("python3 run_tests.py", "run_tests.py *"),
    ])
    def test_a_derived_rule_carries_both_interpreters_and_is_narrow(self, recorded, rest):
        """The fingerprint helper is the other writer of python rules: both
        spellings, narrowed to the first argument, and never the broad
        `Bash(python *)` the self-host list forbids (failure-mode review)."""
        derived = PROFILES["workflow"].fingerprint_allows({"test_commands": [recorded]})
        rules = _python_rules(derived)
        assert {("python", rest), ("python3", rest)} <= set(rules), derived
        assert "Bash(python *)" not in derived and "Bash(python3 *)" not in derived


class TestTheFetchPipeDenyLiteralsStayPosixAndTheClassStaysAtTheHookLayer:
    """The comment beside `_DENY_DEFAULTS` makes two prescriptive claims that
    `espalier/` cannot check by import (it never imports `tools/cc/`): no
    PowerShell twin of the two POSIX fetch-pipe literals is ever emitted,
    because the twins would be green, blind and claim a coverage they do not
    have; and the download-and-execute CLASS is covered on both shells by the
    `CP-FETCHEXEC` speed-bump. Pinned here so a rename or a deletion of the
    checkpoint, or a future `PowerShell(...)` deny entry, reds instead of
    leaving the comment claiming coverage with nothing behind it
    (failure-mode review, 2026-09-10; precedent: the `Read()` seam pin in
    tests/test_write_guard.py)."""

    def test_no_powershell_deny_default_is_emitted(self):
        # Profile-independent by construction (the docstring's own contract:
        # the deny list is shared across profiles), so one call is the whole
        # population.
        rules = list(deny_defaults())
        assert rules, "the deny defaults emptied; this pin would pass vacuously"
        assert not any(r.startswith("PowerShell(") for r in rules), rules

    def test_the_two_posix_fetch_pipe_literals_are_still_the_permission_belt(self):
        rules = set(deny_defaults())
        assert {"Bash(curl * | sh)", "Bash(wget * | sh)"} <= rules, rules

    def test_the_named_checkpoint_exists_in_the_hook_tree(self):
        src = (REPO_ROOT / "tools" / "cc" / "hooks" / "_speedbump.py").read_text(encoding="utf-8")
        assert 'id="CP-FETCHEXEC"' in src, "the checkpoint the deny-defaults comment names is gone"


class TestPowerShellTwinsFollowTheRenderHost:
    """Claude Code's PowerShell tool is a separate tool and permission rules
    are tool-scoped, so on a Windows host every ``Bash(...)`` allow rule needs
    a ``PowerShell(...)`` twin or the profile's allow-list is inert for the
    commands the agent issues through PowerShell (walk 2 finding 3, driven on
    a Windows 11 host 2026-09-09: 14 of 18 rules inert). The twins ride the
    same host seam as the statusLine shim, so a POSIX render never grows them,
    and the one composer behind ``init``, ``doctor`` and ``merge-settings``
    renders them, so the three cannot disagree about a Windows file."""

    @pytest.mark.parametrize("name", sorted(PROFILES))
    def test_every_bash_rule_is_twinned_and_nothing_else_is(self, name):
        allow = PROFILES[name].allow
        expected = tuple(
            "PowerShell(" + rule[len("Bash("):]
            for rule in allow if rule.startswith("Bash(")
        )
        assert powershell_twins(allow) == expected, (name, powershell_twins(allow), expected)
        assert not any(r.startswith("PowerShell(") for r in allow), (
            "profiles hold Bash rules only; the twins are rendered, never stored"
        )

    def test_the_twins_engage_on_the_default_profile(self):
        """Presence, not just symmetry: an emptied allow-list passes the row
        above."""
        twins = set(powershell_twins(PROFILES[DEFAULT_PROFILE].allow))
        assert {"PowerShell(pytest *)", "PowerShell(git status)", "PowerShell(git diff *)"} <= twins, twins

    def test_minimal_renders_no_twins(self):
        assert powershell_twins(PROFILES["minimal"].allow) == ()

    def test_a_twin_already_present_is_not_duplicated(self):
        assert powershell_twins(("Bash(git status)", "PowerShell(git status)")) == ()

    def test_a_windows_render_appends_twins_after_the_derived_rules(self):
        allow = cli._profile_allow_list(
            "workflow",
            fingerprint={"languages": ["python"], "test_commands": ["npm test"]},
            posix=False,
        )
        assert "PowerShell(npm test *)" in allow, allow      # derived rules are twinned too
        assert "PowerShell(pytest *)" in allow, allow
        last_bash = max(i for i, r in enumerate(allow) if r.startswith("Bash("))
        first_ps = min(i for i, r in enumerate(allow) if r.startswith("PowerShell("))
        assert last_bash < first_ps, allow
        assert len(allow) == len(set(allow)), f"duplicate rule in the render: {allow}"

    def test_a_posix_render_carries_no_twin(self):
        allow = cli._profile_allow_list(
            "workflow", fingerprint={"test_commands": ["npm test"]}, posix=True,
        )
        assert not any(r.startswith("PowerShell(") for r in allow), allow
        assert "Bash(npm test *)" in allow, "the row must engage: rules ARE rendered"
        assert "Bash(npm *)" not in allow, "a derived rule is never the bare binary (DEF-965)"

    def test_the_deny_list_is_untouched_by_a_windows_render(self, monkeypatch):
        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: False)
        settings = cli._build_settings_json(profile_name="workflow")
        allow = settings["permissions"]["allow"]
        deny = settings["permissions"]["deny"]
        assert any(r.startswith("PowerShell(") for r in allow), allow
        assert not any(r.startswith("PowerShell(") for r in deny), deny
        assert set(deny) == set(deny_defaults())

    def test_doctor_and_merge_see_the_twins_a_windows_file_lacks(self, tmp_path, monkeypatch):
        """The gap report goes through the same composer, so a Windows host
        holding a Bash-only settings.json is told exactly which twins it lacks
        and ``merge-settings --add-allows`` has them to append."""
        monkeypatch.setattr(cli, "_render_host_is_posix", lambda: False)
        # A Python tree, so every static rule renders (the Python-only ones
        # need a Python fingerprint, DEF-965).
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            json.dumps({"languages": ["python"]}), encoding="utf-8",
        )
        bash_only = list(PROFILES["workflow"].allow)
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": bash_only}}), encoding="utf-8")
        gaps = cli.settings_allow_gaps(path, profile="workflow", repo_root=tmp_path)
        assert gaps is not None
        missing, note = gaps
        assert note == "" and missing == list(powershell_twins(bash_only)), (missing, note)


def test_no_profile_pre_approves_a_workflow(monkeypatch):
    """The three review workflows deploy as a .claude kind, and Claude Code offers a
    `Workflow(<name>)` allow rule that pre-approves one by name. The harness writes
    none, on either host: the first run of each scaffold asks under manual and
    accept-edits permission modes, which is the brake a dozens-of-agents run wants."""
    for posix in (True, False):
        monkeypatch.setattr(cli, "_render_host_is_posix", lambda posix=posix: posix)
        for profile_name in PROFILES:
            settings = cli._build_settings_json(profile_name=profile_name)
            rules = settings["permissions"]["allow"] + settings["permissions"]["deny"]
            assert not any(r.startswith("Workflow(") for r in rules), (profile_name, posix, rules)


@pytest.mark.contract
def test_one_function_renders_the_allow_list_and_one_the_fresh_settings():
    """Every writer and reader of settings.json allow rules -- init's fresh
    write and its parked .new, fuse's re-render, merge-settings, the upgrade
    preview and doctor -- derives the list through `_profile_allow_list`, and
    every fresh render goes through `fresh_settings`. A second copy of either
    is how a fresh fusion came to lack rules its own plan named (2026-10-06):
    read off the AST of every engine module, so a new copy reds here."""
    import ast

    owners: dict[str, set[str]] = {
        "fingerprint_allows": set(), "python_only": set(), "JSON_SENTINEL_KEY=True": set(),
    }
    for path in sorted((REPO_ROOT / "espalier").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and node.attr in ("fingerprint_allows", "python_only"):
                    owners[node.attr].add(f"{path.name}::{fn.name}")
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Subscript)
                        and getattr(node.targets[0].slice, "id", None) == "JSON_SENTINEL_KEY"
                        and isinstance(node.value, ast.Constant) and node.value.value is True):
                    owners["JSON_SENTINEL_KEY=True"].add(f"{path.name}::{fn.name}")
    assert owners["fingerprint_allows"] == {"cli.py::_profile_allow_list"}, owners
    # The superseded-rule reporter reads the flag to decide whether the profile
    # conditions anything; it renders through `_profile_allow_list` itself.
    assert owners["python_only"] == {
        "cli.py::_profile_allow_list", "cli.py::settings_superseded_allows",
    }, owners
    assert owners["JSON_SENTINEL_KEY=True"] == {"cli.py::fresh_settings"}, owners
