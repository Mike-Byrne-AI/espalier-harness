"""TP-343: denial-reason actionability walk -- the §14.2 four-element UX contract.

docs/FAILURE_MODES.md §14.2 (Denial-reason UX opacity) requires that a blocked
tool call surface an ACTIONABLE reason, not opaque debug output. This module is
that contract's mechanical enforcement: it walks every operator-facing template in
``tools/cc/hooks/_denial_reasons._OPERATOR_FACING_TEMPLATES`` and asserts each
carries the four required UX elements --

  1. what was attempted   (a subject: a ``{field}`` target OR a named action)
  2. what rule fired       (a non-empty leading line naming the block)
  3. what the operator can do   (a ``Do:`` remediation line)
  4. what clears the block (a concrete next step: an env-var, a ``/command``, an
     ``espalier`` verb, a subagent dispatch spelled ``subagent_type='<name>'``,
     the hand-recorded judgement the hygiene gates honour, or -- for a hard
     safety stop -- a ``narrow the target`` instruction)

plus a cross-cutting guard: no operator-facing template may interpolate a raw
regex source (a ``{pattern}`` field renders ``matches pattern '<raw regex>'`` into
the reader-facing text -- the TP-189 lesson; the PowerShell dangerous-command
fallback regressed exactly this before TP-343).

Diagnostic templates (``MALFORMED_*``, ``*_INTERNAL_ERROR``, ``GATE_PYTEST_FAILED``,
``GATE_ENV_OVERRIDE_*``, and the ``DANGEROUS_*`` hard-stops that lack the ``Don't:``/
``Do:`` habit-pair -- the Bash fallback and ``CATASTROPHIC_RM``) are correctly ABSENT
from ``_OPERATOR_FACING_TEMPLATES`` and out of scope. The PowerShell dangerous-command
fallback is the exception: it is restructured as a ``Don't:``/``Do:`` pair (the Bash
fallback names a "narrow the target" remediation too, but as a single markerless
sentence), so the PS one is registered and walked here. Element 4 is read as "the concrete mechanism that clears THIS block":
not every deny is env-var-unlockable (a kill-switch or a catastrophic-rm stop has no
bypass), so the check accepts ANY concrete next-step token, not an env-var
specifically -- an honest reading of §14.2's "what env-var/flag unlocks the path."

Sibling of ``tests/test_denial_reasons.py::TestOperatorFacingTemplatesPairWrongAndRight``
(the Don't/Do PAIRING contract); this file adds the CONCRETENESS + raw-regex-field
coverage the pairing check does not see. Ungated (a pure data check over shipped
constant values), matching that sibling class.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

sys.path.insert(0, str(HOOKS_DIR))
import _denial_reasons  # noqa: E402

# Operator-facing templates whose SUBJECT ("what was attempted") is named in fixed
# prose rather than a ``{field}`` placeholder -- the block is categorical (no single
# variable target). A future field-less operator-facing template must be added here
# CONSCIOUSLY; that is the point (it forces the author to confirm the subject is
# named).
_PROSE_SUBJECT_TEMPLATES = frozenset({
    "HARNESS_ENV_PREFIX_INLINE",
    "GATE_DOCS_REFRESH_NEEDED",
    "GATE_DOCS_REFRESH_NO_CHANGES",
    "GATE_CODE_REVIEW_BLOCK",
})

# Keywords proving the leading line NAMES the rule that fired (element 2).
_REASON_KEYWORDS = (
    "blocked", "detected", "No active", "must be", "refresh", "invoke",
    "denied", "failing",
)

# Concrete next-step tokens proving element 4 ("what clears the block"). Any ONE
# suffices: an env-var, a /slash-command, an ``espalier`` verb, an agent dispatch,
# or a hard-safety-stop remediation.
_CONCRETE_STEP_RE = re.compile(
    r"ESPALIER_[A-Z_]+"                  # env-var unlock (maintenance / stop gate)
    r"|/[a-z][a-z-]+"                    # a /slash-command (/implement-task, ...)
    r"|espalier "                       # an `espalier <verb>` CLI remediation
    # A subagent dispatch, spelled the ONE canonical way. DEF-496: this list
    # used to accept `Task(` OR a bare agent name, so a template that named the
    # dispatch two ways in one paragraph passed. The parameter name is what
    # survives the tool's rename (Task became Agent in Claude Code 2.1.63).
    r"|subagent_type='"
    r"|\"agent\": \"operator\""         # the hand-recorded judgement Gates 2/3 honour
    r"|narrow the target"               # hard-safety-stop remediation (no bypass)
    # ⚠ 2026-08-22: `narrow the target` alone made this gate SATISFIABLE BY THE
    # DEFECT. `ps-remove-item-recurse-force-*` fires on every -Recurse+-Force
    # invocation INCLUDING a relative target (driven), so on the PowerShell
    # side "narrow the target" named an action that could not clear the deny
    # for any input -- and this element-4 check accepted it as the proof of
    # actionability. A hard stop whose remediation is a FLAG change rather
    # than a PATH change is the other legitimate shape; it needs its own token
    # or fixing the message reds the gate that exists to keep messages honest.
    r"|drop -Force"                     # hard-safety-stop remediation, flag-level
)

_FORMAT_FIELD_RE = re.compile(r"\{[a-z_][a-z_]*\}")

# The canonical subagent-dispatch spelling, and the roster it may name.
_DISPATCH_RE = re.compile(r"subagent_type='([^']*)'")
_AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
_NAME_LINE_RE = re.compile(r"^name:\s*(\S+)\s*$", re.M)


def _frontmatter(text: str) -> str:
    """The YAML block between the file's opening `---` fences, or `""`."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end > 0 else ""


def _roster() -> frozenset[str]:
    """Agent names from the roster's frontmatter -- the value SubagentStop's
    ``agent_type`` carries, and the only thing a dispatch can name. Derived,
    so a renamed agent reds the template that still spells the old name."""
    names: set[str] = set()
    for path in sorted(_AGENTS_DIR.glob("*.md")):
        match = _NAME_LINE_RE.search(_frontmatter(path.read_text(encoding="utf-8")))
        if match:
            names.add(match.group(1))
    assert names, f"no agent frontmatter names under {_AGENTS_DIR}"
    return frozenset(names)


# The operator-typed spelling (`@agent-<name>`, the documented mention form) in
# the docs and bodies an adopter reads. Its subject is the roster too.
_MENTION_RE = re.compile(r"@agent-([a-z][a-z0-9-]*)")
_MENTION_SURFACES = ("docs/*.md", ".claude/commands/*.md", ".claude/skills/*/SKILL.md",
                     ".claude/agents/*.md", "README.md", "CONTRIBUTING.md")


_ANTI_MARKER = "Don't:"
_POSITIVE_MARKER = "Do:"

_TEMPLATE_NAMES = list(_denial_reasons._OPERATOR_FACING_TEMPLATES)


def _tmpl(name: str) -> str:
    return getattr(_denial_reasons, name)


class TestDenialReasonActionability:
    """§14.2 four-element UX contract over the operator-facing registry."""

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_element_1_names_what_was_attempted(self, name: str) -> None:
        tmpl = _tmpl(name)
        has_field = bool(_FORMAT_FIELD_RE.search(tmpl))
        assert has_field or name in _PROSE_SUBJECT_TEMPLATES, (
            f"{name}: element 1 (what was attempted) -- names no subject: no "
            f"`{{field}}` target and not in _PROSE_SUBJECT_TEMPLATES. Interpolate "
            f"the target, or add the name to _PROSE_SUBJECT_TEMPLATES if the block "
            f"is categorical."
        )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_element_2_names_the_rule(self, name: str) -> None:
        tmpl = _tmpl(name)
        lead = tmpl.split(_ANTI_MARKER, 1)[0]
        assert lead.strip(), f"{name}: element 2 -- no reason prose before Don't:"
        assert any(k in lead for k in _REASON_KEYWORDS), (
            f"{name}: element 2 (what rule fired) -- the leading line names no "
            f"recognizable block reason (expected one of {_REASON_KEYWORDS})."
        )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_element_3_names_a_remediation(self, name: str) -> None:
        tmpl = _tmpl(name)
        assert _POSITIVE_MARKER in tmpl, (
            f"{name}: element 3 (what the operator can do) -- no `Do:` line."
        )
        after = tmpl.split(_POSITIVE_MARKER, 1)[1]
        assert len(after.strip()) >= 20, (
            f"{name}: element 3 -- the `Do:` remediation is too thin to be "
            f"actionable ({after.strip()!r})."
        )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_element_4_offers_a_concrete_next_step(self, name: str) -> None:
        tmpl = _tmpl(name)
        assert _CONCRETE_STEP_RE.search(tmpl), (
            f"{name}: element 4 (what clears the block) -- names no concrete next "
            f"step (env-var, /command, `espalier` verb, agent dispatch, or a "
            f"hard-stop `narrow the target` remediation)."
        )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_no_raw_regex_field(self, name: str) -> None:
        """A ``{pattern}`` field carries ``entry.pattern.pattern`` (raw regex)
        straight into the reader-facing text -- resolve to plain English instead
        (TP-189; cf. format_dangerous_bash). The PowerShell dangerous-command
        fallback regressed exactly this before TP-343."""
        tmpl = _tmpl(name)
        assert "{pattern}" not in tmpl, (
            f"{name}: interpolates a raw-regex `{{pattern}}` field into the "
            f"operator-facing reason (renders `matches pattern '<raw regex>'`). "
            f"Resolve to a plain-English description."
        )


class TestAgentDispatchIsSpelledOneWay:
    """DEF-496: a gate message told the reader to run an agent two ways in one
    paragraph (`Run @docs-maintainer`, then `via the Task tool`), and element 4
    accepted either because its token list named both. One spelling now:
    ``subagent_type='<name>'`` -- it survives the tool's rename (Task became
    Agent in Claude Code 2.1.63), the ``@``-mention form never carried its
    ``@agent-`` prefix, and the parameter names the value SubagentStop reports
    back, which is what the relief records key on.
    """

    _NON_CANONICAL = (
        re.compile(r"@agent-[a-z-]+"),               # the @-mention form
        re.compile(r"(?<![\w/])@[a-z]+-[a-z-]+"),     # the mention form without its prefix
        re.compile(r"\b(?:Task|Agent)\("),           # a tool-call spelling
        re.compile(r"\b(?:Task|Agent) tool\b"),      # naming the tool
    )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_no_template_carries_a_second_dispatch_spelling(self, name: str) -> None:
        tmpl = _tmpl(name)
        hits = [p.pattern for p in self._NON_CANONICAL if p.search(tmpl)]
        assert not hits, (
            f"{name}: spells a subagent dispatch a second way {hits}. Spell it "
            f"subagent_type='<name>' and nothing else."
        )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_every_do_line_that_names_an_agent_dispatches_it_canonically(
        self, name: str
    ) -> None:
        """A remediation that names a roster agent dispatches it in the canonical
        form, in the same `Do:` line -- so a prose mention cannot stand in for
        the instruction."""
        roster = _roster()
        for do_line in _tmpl(name).split(_POSITIVE_MARKER)[1:]:
            named = {agent for agent in roster if agent in do_line}
            dispatched = set(_DISPATCH_RE.findall(do_line))
            assert named <= dispatched, (
                f"{name}: the Do: line names {sorted(named - dispatched)} without "
                f"subagent_type='<name>'."
            )

    @pytest.mark.parametrize("name", _TEMPLATE_NAMES)
    def test_every_dispatch_names_a_roster_agent(self, name: str) -> None:
        unknown = set(_DISPATCH_RE.findall(_tmpl(name))) - _roster()
        assert not unknown, (
            f"{name}: dispatches {sorted(unknown)}, which is not an agent under "
            f"{_AGENTS_DIR} -- a reader following it gets an unknown subagent."
        )

    def test_the_hygiene_gates_do_dispatch(self) -> None:
        """Earn the red: the two gate messages whose remediation IS a dispatch
        carry the canonical form (lead and Do: line), so the rows above are
        not vacuously green over templates that dispatch nothing."""
        assert _DISPATCH_RE.findall(_tmpl("GATE_CODE_REVIEW_BLOCK")) == [
            "code-reviewer", "code-reviewer",
        ]
        assert _DISPATCH_RE.findall(_tmpl("GATE_DOCS_REFRESH_NEEDED")) == [
            "docs-maintainer", "docs-maintainer",
        ]

    def test_the_roster_is_derived_not_typed(self) -> None:
        roster = _roster()
        assert {"code-reviewer", "docs-maintainer"} <= roster
        assert len(roster) >= 5

    def test_every_mention_in_shipped_docs_names_a_roster_agent(self) -> None:
        """The operator-facing spelling is `@agent-<name>` (the documented
        mention); a doc that mentions an agent the roster does not have sends
        the reader to nothing. Same oracle as the templates, one file over."""
        roster = _roster()
        unknown: list[str] = []
        seen = 0
        for pattern in _MENTION_SURFACES:
            for path in sorted(REPO_ROOT.glob(pattern)):
                for name in _MENTION_RE.findall(path.read_text(encoding="utf-8")):
                    seen += 1
                    if name not in roster:
                        unknown.append(f"{path.relative_to(REPO_ROOT)}: @agent-{name}")
        assert seen, "no @agent- mention anywhere -- the surfaces list is stale"
        assert not unknown, unknown


def _templates_carrying_the_habit_pair() -> frozenset[str]:
    """Operator-facing templates, discovered from the BODIES not the registry.

    This module's own docstring records that diagnostic templates are correctly
    ABSENT from ``_OPERATOR_FACING_TEMPLATES`` *because* they lack the
    ``Don't:``/``Do:`` habit-pair. That makes the pair the definition, and a
    definition is derivable without consulting the list it defines -- which is
    the whole point (``docs/FAILURE_MODES.md`` §18.4).
    """
    found = set()
    for name in dir(_denial_reasons):
        if name.startswith("__") or not name.isupper():
            continue
        value = getattr(_denial_reasons, name)
        if not isinstance(value, str):
            continue
        if _ANTI_MARKER in value and _POSITIVE_MARKER in value:
            found.add(name)
    return frozenset(found)


#: A LITERAL, not `len(_OPERATOR_FACING_TEMPLATES)`. This is the tripwire on the
#: wrong fix. The set-equality row below compares two views of the SAME module,
#: so collapsing `_templates_carrying_the_habit_pair()` to
#: `frozenset(_denial_reasons._OPERATOR_FACING_TEMPLATES)` -- a plausible
#: "simplification" -- makes it tautological and restores the pre-fix defect
#: exactly. Measured: with the helper collapsed and 3 names deleted, this file
#: plus its sibling ran 73 passed at rc=0 with nothing red.
#:
#: An earlier version of this fix DECLINED a count here, reasoning that "the
#: registry is allowed to grow." That reasoning was wrong twice over: the
#: sibling fix in `tests/test_release_noise_parity.py` faced the identical
#: question about an equally growable constant and correctly took the pin, and
#: growth is exactly the moment a conscious bump is cheap.
# 10 since 2026-09-03: SECRET_PATH_ACCESS joined when the sensitive-path
# denial moved from settings `Read()` rules to the hook layer. 11 since
# 2026-09-07: GATE_RELIEF_RECORD_INVALID, the hygiene gates' third arm for a
# flag file that is not a relief record (DEF-608 review). 12 since
# 2026-09-14: PROTECTED_ZONE_MUTATION, the remove/relocate twin of the
# protected-zone write template (§C52, DEF-795).
_PINNED_REGISTRY_COUNT = 12


class TestRegistryIsPinnedAgainstDeletion:
    """Removing a name from ``_OPERATOR_FACING_TEMPLATES`` must RED here.

    Every actionability row above parametrizes FROM the registry, so deleting a
    name deletes its own coverage and the suite merely gets SMALLER -- a shrink
    nothing reads as a failure. Measured before this row existed: dropping 3 of
    the 9 names took this file plus ``tests/test_denial_reasons.py`` from 89
    passed to 71 (exactly 18 rows) at rc=0, with nothing red.

    This row derives the EXPECTATION from an axis independent of the registry,
    so the deletion is loud (``docs/FAILURE_MODES.md`` §18.4: derive the
    expectation, not the population).
    """

    def test_registry_equals_the_habit_pair_carriers(self) -> None:
        discovered = _templates_carrying_the_habit_pair()
        registered = frozenset(_denial_reasons._OPERATOR_FACING_TEMPLATES)
        missing = sorted(discovered - registered)
        extra = sorted(registered - discovered)
        assert not missing, (
            f"template(s) carry the {_ANTI_MARKER}/{_POSITIVE_MARKER} pair but "
            f"are ABSENT from _OPERATOR_FACING_TEMPLATES: {missing}. Each is "
            f"operator-facing by this module's own definition and is walked by "
            f"NO actionability row. Register it. Do NOT add an exclusion set to "
            f"clear this -- that reintroduces the hand-list one level up."
        )
        assert not extra, (
            f"registered template(s) whose body lacks the "
            f"{_ANTI_MARKER}/{_POSITIVE_MARKER} pair: {extra}. The likely cause "
            f"is a wording edit that dropped a marker -- RESTORE THE PAIR. "
            f"Removing the name from _OPERATOR_FACING_TEMPLATES also clears this "
            f"row, but it silently deletes ~6 rows of actionability coverage per "
            f"name; do that ONLY if the template is genuinely diagnostic (reports "
            f"a fault rather than instructing the operator), and say so in a "
            f"comment beside it."
        )

    def test_registry_size_matches_the_literal_pin(self) -> None:
        """The equality row above compares two views of the SAME module.

        That makes it satisfiable by editing either side, and tautological if the
        helper is ever collapsed to read the registry directly. This literal is
        what reds then -- and on any plain deletion, regardless.
        """
        live = len(_denial_reasons._OPERATOR_FACING_TEMPLATES)
        assert live == _PINNED_REGISTRY_COUNT, (
            f"_OPERATOR_FACING_TEMPLATES holds {live} names but the pin is "
            f"{_PINNED_REGISTRY_COUNT}. A REMOVAL is the dangerous direction: it "
            f"retires ~6 actionability rows per name with nothing else failing. "
            f"If the change is deliberate, update _PINNED_REGISTRY_COUNT -- do "
            f"NOT replace it with len(_OPERATOR_FACING_TEMPLATES), which makes "
            f"this row tautological and blind to exactly what it exists to catch."
        )

    def test_the_discovery_is_not_vacuous(self) -> None:
        """A resolver that finds nothing would make the equality row pass trivially."""
        assert _templates_carrying_the_habit_pair(), (
            "discovered ZERO templates carrying the habit-pair. The set-equality "
            "row above would pass vacuously against an empty registry. This is a "
            "resolver failure, not a clean tree."
        )


class TestThePinIsALiteralNotADerivation:
    """The anti-regeneration invariant, enforced mechanically rather than by comment.

    ``docs/FAILURE_MODES.md`` §18.4 bullet 4, and it is not belt-and-braces: the
    measured counterfactual on the predecessor was that WITHOUT this check,
    regenerating a pin from its subject *and* deleting a member runs fully green
    with a real hole open. A comment saying "keep this literal" is advice a
    future editor -- or an AI collaborator tidying "magic numbers" -- may
    silently decline.

    Shape ported from ``tests/test_write_guard_command_position.py``
    ``::TestThePinsAreLiteralsNotDerivations``, the attested instance.
    """

    @staticmethod
    def _module_level_assignments() -> dict[str, ast.expr]:
        # encoding pinned: this file carries non-ASCII, and on a runner with an
        # unset locale a bare read_text() resolves to US-ASCII and reds on a
        # CORRECT tree. A false red in a class whose job is to be believed
        # teaches the reader to distrust it.
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        found: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    found[node.target.id] = node.value
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node.value
        return found

    def test_prose_subject_exclusions_are_a_literal_set(self) -> None:
        """`_PROSE_SUBJECT_TEMPLATES` is the §18.4 hole one constant over.

        It is a hand-written EXCLUSION consumed by element 1 as
        ``has_field or name in _PROSE_SUBJECT_TEMPLATES``. Derive it from the
        subject and that predicate becomes ``has_field or not has_field``:
        measured, with the exclusion regenerated AND a real ``{field}`` stripped
        from ``PROTECTED_ZONE_WRITE``, the file ran 50 passed with element-1
        coverage 100% retired.

        This file pinned 1 of its 2 constants; the sibling port and the attested
        original both pin all of theirs. It was the outlier.
        """
        value = self._module_level_assignments()["_PROSE_SUBJECT_TEMPLATES"]
        why = (
            "_PROSE_SUBJECT_TEMPLATES must stay a hand-written frozenset({...}) "
            "of string literals. Computed from _OPERATOR_FACING_TEMPLATES it "
            "excuses exactly the templates that would otherwise fail element 1, "
            "which turns the check into a tautology."
        )
        assert isinstance(value, ast.Call), why
        assert getattr(value.func, "id", None) == "frozenset", why
        assert len(value.args) == 1 and isinstance(value.args[0], ast.Set), why
        assert all(
            isinstance(el, ast.Constant) and isinstance(el.value, str)
            for el in value.args[0].elts
        ), why

    def test_registry_count_is_an_integer_literal(self) -> None:
        value = self._module_level_assignments()["_PINNED_REGISTRY_COUNT"]
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            "_PINNED_REGISTRY_COUNT must stay an integer literal. Written as "
            "len(_OPERATOR_FACING_TEMPLATES) it can never disagree with the "
            "registry -- and disagreeing is its entire job."
        )

    def test_the_discovery_helper_still_walks_the_module(self) -> None:
        """The helper must DISCOVER from bodies, not read the registry.

        Collapsing it to ``frozenset(_denial_reasons._OPERATOR_FACING_TEMPLATES)``
        makes the set-equality row tautological. That edit reads like a
        simplification and restores the pre-fix defect exactly.
        """
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        fn = next(
            n for n in tree.body
            if isinstance(n, ast.FunctionDef)
            and n.name == "_templates_carrying_the_habit_pair"
        )
        # Match on the AST, never on unparsed text. An earlier version stripped
        # the top-level docstring and substring-matched the rest -- which still
        # false-red on a NESTED helper's docstring, i.e. on correct code, and a
        # false red in the one class whose job is to be believed teaches the
        # reader to distrust it. Names/attributes/string-constants are immune to
        # prose at every depth.
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        consts = {
            n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        reads_registry = "_OPERATOR_FACING_TEMPLATES" in (names | attrs | consts)
        assert "dir" in names and not reads_registry, (
            "_templates_carrying_the_habit_pair() must discover templates by "
            "walking the module (dir()) and testing each BODY for the marker "
            "pair. It must NOT read _OPERATOR_FACING_TEMPLATES -- that is the "
            "registry under test, and reading it makes the equality row compare "
            "the registry to itself."
        )
