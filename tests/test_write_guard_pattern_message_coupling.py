"""Regression: pattern + deny-message must be coupled in the same record.

Pre-TP-100 shape: ``_BASH_PATTERN_MESSAGES`` was a ``dict[re.Pattern, str]``
keyed by ``re.Pattern`` *object identity*. A future entry that re-compiled
the same regex source inline (instead of referencing the module-level
constant) would silently miss the dict lookup — the deny still fired, but
the custom operator-hint message was lost and the auto-generated
"matches pattern '...'" fallback ran instead. No test caught this.

The refactor replaced parallel structures with ``BashPatternRecord``
NamedTuple entries where ``pattern`` and ``message`` travel together.
This file pins the coupling shape so a future reintroduction of the
parallel-dict pattern fails loudly.

Stem registers under ``unit`` by default in conftest.py. Pure AST +
in-process import; no subprocess, no Bash execution path.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
WRITE_GUARD = HOOKS_DIR / "write_guard.py"

# Import the hook module under test. write_guard imports its sibling
# helpers (`_bash_patterns`, `_protected_zones`, etc.) by adjusting
# sys.path itself, so adding HOOKS_DIR up front lets the import succeed
# without dragging in espalier/.
sys.path.insert(0, str(HOOKS_DIR))
import write_guard  # noqa: E402
import _denial_reasons  # noqa: E402


class TestBashPatternMessageCoupling:
    """The pattern-message dict (object-identity keyed) must not reappear,
    and each record's message must survive regex recompilation."""

    def test_pattern_message_dict_does_not_reappear(self):
        """No ``dict[re.Pattern, ...]`` shape should exist in write_guard.py.

        Walks the AST for AnnAssign / Assign nodes whose RHS is a Dict
        literal with at least one key that is an ``re.compile(...)`` call
        OR a Name resolving to a module-level Pattern constant. Either
        shape signals the pre-TP-100 coupling has crept back in.

        The check also catches the literal name ``_BASH_PATTERN_MESSAGES``
        in case a future maintainer reintroduces the exact symbol.
        """
        source = WRITE_GUARD.read_text(encoding="utf-8")
        assert "_BASH_PATTERN_MESSAGES" not in source, (
            "_BASH_PATTERN_MESSAGES symbol reintroduced — the parallel "
            "dict[Pattern, str] shape was the bug TP-100 closed; "
            "messages belong on the BashPatternRecord, not in a "
            "side-table keyed by Pattern object identity."
        )

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if key is None:  # **kwargs unpacking; not a literal key
                    continue
                if _looks_like_pattern_key(key):
                    raise AssertionError(
                        f"write_guard.py line {key.lineno}: dict literal "
                        f"keyed by re.Pattern detected. This is the "
                        f"object-identity coupling shape that TP-100 "
                        f"retired. Put the message on the "
                        f"BashPatternRecord instead."
                    )

    def test_every_record_has_pattern_and_resolvable_message(self):
        """Each BashPatternRecord must have a non-None pattern and a
        message that resolves to a non-empty string at deny time.

        Empty ``message`` is allowed in the record (the auto-generated
        default fires); the resolved deny message must still be
        non-empty.
        """
        for entry in write_guard.DANGEROUS_BASH_PATTERNS:
            assert entry.pattern is not None, (
                f"BashPatternRecord {entry.pid!r} has no pattern"
            )
            resolved = entry.message or (
                f"Dangerous command blocked: matches pattern "
                f"'{entry.pattern.pattern}'"
            )
            assert resolved.strip(), (
                f"BashPatternRecord {entry.pid!r} resolves to an empty "
                f"deny message"
            )

    def test_every_record_emits_its_own_message_on_match(self, capsys):
        """Each record's deny text must come out of the hook when its
        pattern matches — never the auto-generated fallback for a
        record that has a custom message.

        This is the structural proof TP-100 was about. Under the
        pre-refactor parallel-dict shape, the message-pattern coupling
        relied on object identity of the Pattern key. The bug would
        surface if any future entry inlined ``re.compile(...)`` into
        ``DANGEROUS_BASH_PATTERNS`` instead of referencing a
        module-level constant — the dict lookup would miss and the
        custom message would silently drop to the fallback. The record
        shape forecloses that bug-class entirely; this test verifies
        the binding holds by exercising every record through the real
        ``check_bash_dangerous_patterns`` code path.

        Why not recompilation-based: Python's ``re`` module caches
        ``re.compile(source)`` results, so a "new Pattern object from
        the same source" assertion can't reliably demonstrate the
        bug-class. Behavior-by-record is the right surface.
        """
        for entry in write_guard.DANGEROUS_BASH_PATTERNS:
            synth_command = _synthesize_match_for(entry.pattern)
            rc = write_guard.check_bash_dangerous_patterns(
                {"command": synth_command}
            )
            assert rc == 0  # deny() = exit 0 + JSON-on-stdout (channel-XOR)
            captured = capsys.readouterr()
            payload = json.loads(captured.out)
            reason = payload["hookSpecificOutput"]["permissionDecisionReason"]

            if entry.message:
                # Custom-message records must emit their own text.
                assert entry.message in reason, (
                    f"Custom message for record {entry.pid!r} not in "
                    f"deny reason. Got: {reason!r}"
                )
            else:
                # Default-message records must emit the auto-generated
                # form (preserves the "Dangerous command blocked"
                # prefix that test_write_guard.py:900 pins).
                assert "Dangerous command blocked" in reason, (
                    f"Default-message record {entry.pid!r} lost the "
                    f"'Dangerous command blocked' prefix. "
                    f"Got: {reason!r}"
                )
                # TP-189-B (FRICTION-2): the auto-generated bash fallback now
                # emits a plain-English description keyed by pid, NOT the raw
                # regex source — the operator sees intent, not a pattern.
                assert entry.pattern.pattern not in reason, (
                    f"Default-message record {entry.pid!r} leaked the raw "
                    f"regex source into the deny text. Got: {reason!r}"
                )
                plain = _denial_reasons.DANGEROUS_BASH_PLAIN.get(entry.pid)
                if plain is not None:
                    assert plain in reason, (
                        f"Default-message record {entry.pid!r} should include "
                        f"its plain-English description in the deny text. "
                        f"Got: {reason!r}"
                    )

    def test_every_ps_record_emits_its_own_message_on_match(self, capsys):
        """Mirror of the Bash binding contract for ``DANGEROUS_PS_PATTERNS``.

        TP-103 NIT1 brought the PS side to tuple-of-records parity. The
        same coupling contract must hold: each record's deny text must
        come out of the hook when its pattern matches; default-message
        records must produce the auto-generated "Dangerous PowerShell
        command blocked" form with a plain-English description embedded
        (parity with the Bash side -- never the raw regex source).

        Pre-NIT1 ``DANGEROUS_PS_PATTERNS`` was a plain ``list[re.Pattern]``
        with no per-entry message. A future PS entry needing a custom
        message would have reached for the same parallel-dict shape
        TP-100 closed on the Bash side. This test pins the binding.
        """
        for entry in write_guard.DANGEROUS_PS_PATTERNS:
            synth_command = _synthesize_match_for(entry.pattern)
            rc = write_guard.check_powershell({"command": synth_command})
            assert rc == 0  # deny() = exit 0 + JSON-on-stdout
            captured = capsys.readouterr()
            payload = json.loads(captured.out)
            reason = payload["hookSpecificOutput"]["permissionDecisionReason"]

            if entry.message:
                assert entry.message in reason, (
                    f"Custom message for PS record {entry.pid!r} not in "
                    f"deny reason. Got: {reason!r}"
                )
            else:
                # PS-side default uses "Dangerous PowerShell command
                # blocked" prefix (mirrors Bash side but distinct).
                assert "Dangerous PowerShell command blocked" in reason, (
                    f"Default-message PS record {entry.pid!r} lost the "
                    f"'Dangerous PowerShell command blocked' prefix. "
                    f"Got: {reason!r}"
                )
                # Parity with the Bash side (TP-189 / TP-343): the
                # auto-generated PS fallback emits a plain-English
                # description keyed by pid, NOT the raw regex source --
                # the operator sees intent, not a pattern.
                assert entry.pattern.pattern not in reason, (
                    f"Default-message PS record {entry.pid!r} leaked the raw "
                    f"regex source into the deny text. Got: {reason!r}"
                )
                plain = _denial_reasons.DANGEROUS_PS_PLAIN.get(entry.pid)
                if plain is not None:
                    assert plain in reason, (
                        f"Default-message PS record {entry.pid!r} should "
                        f"include its plain-English description in the deny "
                        f"text. Got: {reason!r}"
                    )

    def test_every_default_message_ps_record_has_a_plain_description(self):
        """Completeness guard (TP-343): every default-message PS record MUST
        have a ``DANGEROUS_PS_PLAIN`` entry. Without it, ``format_dangerous_ps``
        falls back to the generic non-discriminating "a dangerous command
        pattern" and the coupling test above silently skips its ``if plain is
        not None`` discrimination assert -- reopening the §14.2 UX-opacity this
        map exists to close. This converts that born-weak conditional guard
        into an unconditional guarantee."""
        for entry in write_guard.DANGEROUS_PS_PATTERNS:
            if not entry.message:
                assert entry.pid in _denial_reasons.DANGEROUS_PS_PLAIN, (
                    f"PS record {entry.pid!r} has no DANGEROUS_PS_PLAIN entry; "
                    f"format_dangerous_ps would fall back to the generic, "
                    f"non-discriminating 'a dangerous command pattern'."
                )

    def test_every_default_message_bash_record_has_a_plain_description(self):
        """Symmetric completeness guard for the Bash side (TP-343 closes the
        born-weak ``if plain is not None`` hole on both maps, not just PS)."""
        for entry in write_guard.DANGEROUS_BASH_PATTERNS:
            if not entry.message:
                assert entry.pid in _denial_reasons.DANGEROUS_BASH_PLAIN, (
                    f"Bash record {entry.pid!r} has no DANGEROUS_BASH_PLAIN "
                    f"entry; format_dangerous_bash would fall back to the "
                    f"generic, non-discriminating 'a dangerous command pattern'."
                )

    def test_ps_patterns_is_tuple_of_records_not_list_of_patterns(self):
        """``DANGEROUS_PS_PATTERNS`` is a tuple of ``BashPatternRecord``
        instances post-NIT1, not a list of bare ``re.Pattern`` objects.

        The tuple-of-records shape forecloses the parallel-dict
        reintroduction class on the PowerShell side. If a future
        contributor reverts to a list (or a list of records, or a tuple
        of bare Patterns), this fires.
        """
        assert isinstance(write_guard.DANGEROUS_PS_PATTERNS, tuple), (
            "DANGEROUS_PS_PATTERNS must be a tuple (immutable), not a list. "
            "TP-103 NIT1 brought this to parity with DANGEROUS_BASH_PATTERNS."
        )
        for entry in write_guard.DANGEROUS_PS_PATTERNS:
            assert isinstance(entry, write_guard.BashPatternRecord), (
                f"Every DANGEROUS_PS_PATTERNS entry must be a "
                f"BashPatternRecord; got {type(entry).__name__}: {entry!r}"
            )


def _looks_like_pattern_key(node: ast.expr) -> bool:
    """True if the AST key node looks like a compiled-pattern reference.

    Catches both ``re.compile(...)`` inline keys and bare-Name references
    to module-level Pattern constants (e.g., ``_HARNESS_ENV_PREFIX_RE``).
    A Name lookup is heuristic — we can't resolve types from AST alone —
    so we restrict to names that look like Pattern constants by
    convention (``_RE``, ``_PATTERN``, ``_PAT`` suffix on the upper-case
    portion).
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "compile":
            if isinstance(func.value, ast.Name) and func.value.id == "re":
                return True
    if isinstance(node, ast.Name):
        upper = node.id.upper()
        if upper.endswith("_RE") or upper.endswith("_PATTERN") or upper.endswith("_PAT"):
            return True
    return False


def _synthesize_match_for(pattern: re.Pattern[str]) -> str:
    """Return a string the given pattern will match.

    The DANGEROUS_BASH_PATTERNS records are small and known; rather
    than ship a general-purpose regex-inverter, we hand-craft matchers
    for the patterns this test exercises. If a new record is added with
    a regex shape this helper doesn't cover, extend the mapping below.
    """
    source = pattern.pattern
    fixtures = {
        r"rm[ \t]+-rf[ \t]+/": "rm -rf /",
        r"rm[ \t]+-rf[ \t]+\*": "rm -rf *",
        r"git\s+reset\s+--hard(?!\s+\S+\s+--\s+)": "git reset --hard",
        # harness-env-prefix regex (TP-154 command-position anchor): matches
        # ESPALIER_MAINTENANCE_MODE= / ESPALIER_STOP_GATE= only at a command
        # position. The matcher below is a bare start-of-string prefix, which
        # BRANCH_A (`^`) matches. This literal key is an intentional tripwire:
        # if _HARNESS_ENV_PREFIX_RE's source changes again, this lookup misses
        # and NotImplementedError fires so the matcher gets re-confirmed.
        # ⚠ TRIPWIRE RE-CONFIRMED 2026-08-03: the source changed when every
        # token run was bounded from `\S` to `[^\s;|&]` to kill an O(n^2)
        # ReDoS (a `\S*` run crosses `;` and backtracks from every start
        # position). The lookup missed and NotImplementedError fired, exactly
        # as this key was designed to do. Matcher re-verified against the NEW
        # pattern before this key was updated -- not assumed to still hold.
        # PowerShell patterns (TP-103 NIT1).
        r"Remove-Item\s+-Recurse\s+-Force": "Remove-Item -Recurse -Force /tmp/x",
        # TP-170 §7b: spans bounded `.{0,200}` (were unbounded `.*`) to kill a
        # hook-runtime ReDoS. The synthesized payload's flag spans sit well
        # inside 200 chars, so detection is unchanged.
        r"Remove-Item\s+.{0,200}-Recurse.{0,200}-Force":
            "Remove-Item /tmp/x -Recurse -Force",
    }
    if source in fixtures:
        return fixtures[source]

    # ⚠ TRIPWIRE ON THE AUTHORED TAIL, NOT THE WHOLE SOURCE. The Bash
    # harness-env-prefix record used to be keyed by its full literal source. It
    # is now anchored on the SHARED `_bash_patterns._CMD_POS_NO_VERB`, so a
    # whole-source key would miss — and therefore demand a re-confirmation —
    # every time anyone adds an unrelated wrapper to `_CMD_POS_WRAPPER`. A
    # tripwire that fires on other people's edits gets satisfied by pasting the
    # new blob in, which is the opposite of re-confirming.
    #
    # So the key is the half THIS module authors: the optional `export`/`declare`
    # run plus the variable alternation. Change that grammar and the lookup still
    # misses. Change the shared anchor and it does not. The matcher itself stays
    # honest either way because the caller drives it through the real
    # `check_bash_dangerous_patterns` and asserts a deny — a stale matcher reds
    # there, not here.
    # ⚠ RE-CONFIRMED 2026-08-23 against the post-anchor pattern before this key
    # was written: `ESPALIER_MAINTENANCE_MODE=1` still matches. Not assumed.
    _BASH_ENV_PREFIX_TAIL = (
        r"(?:(?:export|declare)(?:[ \t]+-[^\s;|&]+)*[ \t]+)?"
        r"(?:ESPALIER_MAINTENANCE_MODE|ESPALIER_STOP_GATE)[ \t]*="   # `[ \t]*`: a newline is not an assignment (DEF-701)
    )
    if source.endswith(_BASH_ENV_PREFIX_TAIL):
        return "ESPALIER_MAINTENANCE_MODE=1"

    # ⚠ THE POWERSHELL TWIN, MOVED OFF ITS WHOLE-SOURCE KEY 2026-08-26 — and the
    # move was FORCED by the tripwire firing, which is the system working.
    # That record hand-inlined its own command-position anchor, so its whole
    # source was stable and a literal key was cheap. It now composes the shared
    # `_bash_patterns._PS_CMD_POS`, which puts it in exactly the position the
    # Bash record was already in: a whole-source key would miss, and demand a
    # re-confirmation, every time somebody adds an alias to the shared exec-quote
    # roster. A tripwire that fires on other people's edits gets satisfied by
    # pasting the new blob in, which is the opposite of re-confirming.
    #
    # So the key is the half THIS module authors — the `$env:` variable
    # alternation plus the two deliberately-unanchored arms. Change that grammar
    # and the lookup still misses; change the shared anchor and it does not.
    # ⚠ RE-CONFIRMED against the post-composition pattern BEFORE this key was
    # written, and the equality was asserted mechanically rather than eyeballed:
    # the payload still matches, still populates `envcolon`, and still denies
    # through the real `check_powershell`. Not assumed.
    _PS_ENV_PREFIX_TAIL = (
        r"\$env:(?:ESPALIER_MAINTENANCE_MODE|ESPALIER_STOP_GATE)\s*=)"
        r"|Set-Item\s+(?:-Path\s+)?[\"']?Env:[\\/]?"
        r"(?:ESPALIER_MAINTENANCE_MODE|ESPALIER_STOP_GATE)\b"
        r"|SetEnvironmentVariable\(\s*[\"']"
        r"(?:ESPALIER_MAINTENANCE_MODE|ESPALIER_STOP_GATE)[\"'])"
    )
    if source.endswith(_PS_ENV_PREFIX_TAIL):
        return '$env:' + "ESPALIER_MAINTENANCE_MODE" + ' = "1"; claude'

    # ⚠ Same authored-tail tripwire, for the two recursive-delete literals. They
    # were bare substrings until 2026-08-24; they now carry `_CMD_POS` (so a
    # MENTION is not an invocation) and a right-anchor (so `rm -rf /tmp/x` is not
    # read as `rm -rf /`). Keying on the tail means a change to THIS grammar still
    # trips the wire, while an unrelated wrapper joining the shared anchor does
    # not. Matchers re-verified against the new patterns before these were added.
    for tail, payload in (
        (r"rm[ \t]+-rf[ \t]+/(?=\s|$)", "rm -rf /"),
        (r"rm[ \t]+-rf[ \t]+\*(?=\s|$)", "rm -rf *"),
        # ⚠ The PowerShell twins, same discipline. From 2026-08-24 they carry
        # `_PS_CMD_POS` (so a MENTION is not an invocation) and are built from
        # the shared `_PS_REMOVE_VERB` alias roster, so their whole source is a
        # composed anchor hundreds of characters long. Keying on the authored
        # tail keeps the tripwire on THIS grammar: change the flag grammar and
        # the lookup misses; add a wrapper to the shared anchor, or an alias to
        # the shared verb, and it does not. The matcher stays honest either way
        # because the caller drives it through the real `check_powershell` and
        # asserts a deny -- a stale payload reds there, not here.
        # ⚠ RE-CONFIRMED against the post-anchor patterns before these were
        # written: both payloads still match, and both still deny. Not assumed.
        # ⚠ RE-KEYED 2026-09-16 (DEF-822), and the tripwire fired first: the
        # records now compose `_bash_patterns._PS_RECURSE_SWITCH` /
        # `_PS_FORCE_SWITCH` (the unambiguous cmdlet prefixes, the long
        # forms, the /bin/rm clusters pwsh hands the native binary on a
        # POSIX host) and the mixed record the shared
        # `_PS_RECURSIVE_FORCE_TAIL`. The key is the LAST AUTHORED PIECE of
        # each -- the force fragment's cluster arm, the tail's both-letters
        # cluster -- spelled literally so a change to that grammar still
        # trips here, while an added alias or wrapper does not. The payloads
        # exercise the new grammar and deny through the real
        # `check_powershell` (an absolute target is the hard tier's).
        (r"|(?-i:-[fvdiIPWxrR]*f[vdIPWxrR]*))(?![\w-])", "ri -r -fo /tmp/x"),
        (r"[fvdiIPWxrR]+)(?![\w-]))", "rm -rf /tmp/x"),
    ):
        if source.endswith(tail):
            return payload

    raise NotImplementedError(
        f"No synthesized matcher for pattern source {source!r}. "
        f"Extend _synthesize_match_for fixtures to cover this record."
    )


# ---------------------------------------------------------------------------
# [396] 2-B — Bash / PowerShell dangerous-pattern parity
#
# `DANGEROUS_BASH_PATTERNS` and `DANGEROUS_PS_PATTERNS` guard the same tier for
# two shells. A record present on one side and absent on the other means the
# same wrong-mental-model action is denied when typed as Bash and allowed when
# typed as PowerShell -- which is how the harness-env-prefix deny came to exist
# on one side only.
#
# ⚠ Why this is a CONCEPT map and not a name-set comparison. The pack sketched
# "the same *named* record set", but the live names do not correspond: Bash
# names the catastrophic-delete concept `rm-rf-root` / `rm-rf-star` while
# PowerShell names it `ps-remove-item-recurse-force-*`. A normalized-name
# comparison would report every record as unmatched and force an exemption for
# each -- a gate that is all exemptions asserts nothing. So the mapping is
# explicit, and the EXEMPTION CALIBRATION is the deliverable: a bare
# count-equality pin would be exactly the born-weak shape this pack exists to
# stop repeating.
#
# The gate is keyed to the LIVE record names, so adding a record to either
# registry without declaring its twin (or exempting it with a reason) reds.

#: concept -> (bash record names, powershell record names)
_PARITY_CONCEPTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "catastrophic-recursive-delete": (
        frozenset({"rm-rf-root", "rm-rf-star"}),
        frozenset({
            "ps-remove-item-recurse-force-prefix",
            "ps-remove-item-recurse-force-mixed",
        }),
    ),
    "harness-env-prefix": (
        frozenset({"harness-env-prefix"}),
        frozenset({"ps-harness-env-prefix"}),
    ),
}

#: Records with NO twin on the other shell, each with a stated reason. Empty is
#: the correct state today; the mapping exists so a genuinely shell-specific
#: record can be declared rather than silently tolerated. Adding a name here
#: without a reason is not possible -- the value IS the reason.
_SHELL_SPECIFIC_EXEMPT: dict[str, str] = {}


def _record_names(records) -> set[str]:
    """Record identity is ``BashPatternRecord.pid``, not ``.name``.

    Read off the live NamedTuple rather than assumed: a first draft of this gate
    used ``.name`` and reddened with an AttributeError, which is a red for the
    wrong reason and would have masked the parity gap it exists to find.
    """
    return {r.pid for r in records}


def test_parity_concept_map_covers_every_live_record():
    """Every live record is claimed by a concept or exempted with a reason.

    This is the self-enrolling half: a record added to either registry with no
    declared twin reds here, rather than shipping a one-shell deny that nobody
    notices until an adopter types the other shell.
    """
    bash_names = _record_names(write_guard.DANGEROUS_BASH_PATTERNS)
    ps_names = _record_names(write_guard.DANGEROUS_PS_PATTERNS)
    claimed_bash: set[str] = set()
    claimed_ps: set[str] = set()
    for bash_side, ps_side in _PARITY_CONCEPTS.values():
        claimed_bash |= set(bash_side)
        claimed_ps |= set(ps_side)

    unclaimed_bash = bash_names - claimed_bash - set(_SHELL_SPECIFIC_EXEMPT)
    unclaimed_ps = ps_names - claimed_ps - set(_SHELL_SPECIFIC_EXEMPT)
    assert not unclaimed_bash, (
        f"Bash records claimed by no parity concept: {sorted(unclaimed_bash)}. "
        f"Declare the PowerShell twin in _PARITY_CONCEPTS, or add the name to "
        f"_SHELL_SPECIFIC_EXEMPT with a reason."
    )
    assert not unclaimed_ps, (
        f"PowerShell records claimed by no parity concept: {sorted(unclaimed_ps)}."
    )


def test_every_parity_concept_is_covered_on_both_shells():
    """A declared concept must actually exist on both sides.

    Earn-the-red: before [396] 2-A lands, `harness-env-prefix` has a Bash record
    and no PowerShell record, so this reds naming exactly that concept.
    """
    bash_names = _record_names(write_guard.DANGEROUS_BASH_PATTERNS)
    ps_names = _record_names(write_guard.DANGEROUS_PS_PATTERNS)
    gaps: list[str] = []
    for concept, (bash_side, ps_side) in _PARITY_CONCEPTS.items():
        if concept in _SHELL_SPECIFIC_EXEMPT:
            continue
        live_bash = bash_side & bash_names
        live_ps = ps_side & ps_names
        if live_bash and not live_ps:
            gaps.append(f"{concept}: Bash has {sorted(live_bash)}, PowerShell has NOTHING")
        elif live_ps and not live_bash:
            gaps.append(f"{concept}: PowerShell has {sorted(live_ps)}, Bash has NOTHING")
    assert not gaps, (
        "dangerous-pattern parity gap — the same action is denied in one shell "
        "and allowed in the other:\n  " + "\n  ".join(gaps)
    )


def test_parity_map_is_not_vacuous():
    """A concept map that drifted empty would make both gates above pass.

    Pin the floor and pin a known member, so an emptied or renamed map reds
    instead of silently asserting nothing.
    """
    assert len(_PARITY_CONCEPTS) >= 2, (
        f"parity concept map collapsed to {len(_PARITY_CONCEPTS)} entries"
    )
    assert "harness-env-prefix" in _PARITY_CONCEPTS, (
        "the harness-env-prefix concept is the one this gate was built for"
    )
    for concept, (bash_side, ps_side) in _PARITY_CONCEPTS.items():
        assert bash_side or ps_side, f"concept {concept!r} declares no records at all"
