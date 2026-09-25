"""TP-112: route hook denial reasons through ``_denial_reasons``.

Three contracts enforce that the four governance hooks (write_guard,
plan_guard, config_guard, stop_gate) compose their ``deny()`` /
``block()`` arguments from the shared
``tools/cc/hooks/_denial_reasons.py`` template module instead of
inlining ad-hoc f-strings:

1. ``denial-reason-fstring`` — direct ``ast.JoinedStr`` argument to
   ``deny()`` / ``block()`` is forbidden. Catches the most common
   drift shape (naive inline f-string). Variable-bound reasons
   composed elsewhere pass; their source is governed by Contract 2.

2. ``denial-reason-import`` — every hook that calls ``deny()`` or
   ``block()`` MUST import ``_denial_reasons`` (bare or from-style).
   Catches hooks that compose reasons inline without using the SoT.

3. ``denial-reason-dead-template`` — every module-level
   ``str``-assigned constant defined in ``_denial_reasons.py`` MUST
   be referenced by at least one hook script. Catches dead templates
   that drift out of sync with actual usage.

**Self-host only.** Gated by ``_hook_utils.is_self_host_repo()`` so
adopter repos with customized denials do not false-fire on upstream
prose. Adopters may edit their copy of ``_denial_reasons.py`` without
breaking this contract.

Failure mode this catches: a new hook ships with inline reason
prose, a refactor inlines a template back into a hook, or an existing
template constant is renamed but stays in ``_denial_reasons.py``
unused. All three drift shapes hit a contract before runtime.
"""
from __future__ import annotations

import ast
import dataclasses
import re
import sys
from pathlib import Path

import pytest

from espalier import cli, managed_inventory

# tests/ sibling helper -- the shared cross-document pointer matchers.
from _doc_pointers import section_citations

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
DENIAL_REASONS_PATH = HOOKS_DIR / "_denial_reasons.py"

sys.path.insert(0, str(HOOKS_DIR))
from _hook_utils import is_self_host_repo  # noqa: E402
import _denial_reasons  # noqa: E402 -- used by TestOperatorFacingTemplatesPairWrongAndRight

# Hooks that emit denial reasons. Each is expected to import
# ``_denial_reasons`` (Contract 2) and call ``deny()`` or ``block()``
# at least once. plan_guard and write_guard call ``deny``; config_guard
# and stop_gate call ``block`` (per the channel-XOR JSON shape).
DENYING_HOOKS: tuple[str, ...] = (
    "write_guard.py",
    "plan_guard.py",
    "config_guard.py",
    "stop_gate.py",
)

DENY_FUNCS: frozenset[str] = frozenset({"deny", "block"})


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_deny_calls(tree: ast.AST) -> list[ast.Call]:
    """Return every ``deny(...)`` / ``block(...)`` Call node."""
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in DENY_FUNCS:
            out.append(node)
    return out


def _arg_is_fstring(call: ast.Call) -> bool:
    if not call.args:
        return False
    return isinstance(call.args[0], ast.JoinedStr)


def _hook_imports_denial_reasons(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "_denial_reasons":
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "_denial_reasons":
                return True
    return False


def _collect_denial_reason_constants() -> set[str]:
    """Module-level names in ``_denial_reasons.py`` whose assigned
    value is a string literal.

    Filter predicate (explicit per pack §112-B Contract 3 — avoids
    false-firing on the ``format_dangerous_bash`` / ``format_dangerous_ps``
    helpers, which are ``def`` nodes, not str assignments): walk
    module-level ``ast.Assign`` nodes only; keep the LHS Name iff the
    RHS is ``ast.Constant`` AND ``isinstance(value, str)``.
    FunctionDef / AsyncFunctionDef / ClassDef nodes are excluded by
    AST type, not by name filter.
    """
    tree = _parse(DENIAL_REASONS_PATH)
    names: set[str] = set()
    # ast.Module.body holds module-level statements; this restricts
    # the walk to module scope (excludes nested defs).
    if not isinstance(tree, ast.Module):
        return names
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not isinstance(value, ast.Constant):
            continue
        if not isinstance(value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _collect_references(
    hook_paths: list[Path], defined: set[str]
) -> set[str]:
    """Names accessed as ``_denial_reasons.X`` in hook source, PLUS
    constants referenced by bare ``Name`` inside helper-function bodies
    within ``_denial_reasons.py`` itself.

    The internal walk handles transitive references: a helper like
    ``format_dangerous_bash`` references ``DANGEROUS_BASH_PATTERN_FALLBACK``
    by bare name (same-module scope, no ``_denial_reasons.`` prefix).
    When a hook calls the helper, the constant is in use even though
    the hook never accesses it directly.
    """
    refs: set[str] = set()
    # External attribute accesses on _denial_reasons (in hook source).
    for hook_path in hook_paths:
        tree = _parse(hook_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id != "_denial_reasons":
                continue
            refs.add(node.attr)
    # Internal self-references inside _denial_reasons.py: walk function
    # bodies for bare Name nodes matching the defined constant set.
    tree = _parse(DENIAL_REASONS_PATH)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in defined:
                refs.add(sub.id)
    return refs


# Contract 4 support. A citation that names a section of the adopter's own
# CLAUDE.md -- `see CLAUDE.md "Plan Guard" section` -- is a pointer, and the
# adopter follows it by searching their CLAUDE.md for the quoted name.
#
# Both real phrasings are covered, because both exist in-tree and a pattern
# that fit only the one I looked at first would have gone quietly blind to the
# other: `CLAUDE.md "X" section` (the hooks) and `` `CLAUDE.md` section "X" ``
# (docs/ENV_CATALOG.md:10, a SEEDED doc that reaches every adopter).
#
# The word "section" is OPTIONAL, and that is a deliberate choice between two
# unequal risks rather than sloppiness. Requiring it was tried and rejected:
# the third live citation (docs/FAILURE_MODES.md, "the repo's settled
# convention (CLAUDE.md "Cross-platform Python invocation") is ...") does not
# use the word at all, so the tight pattern dropped a REAL citation.
#
#   Over-reach  -> a quoted phrase that is not a section name enters the
#                  population, and the contract reds. Loud, and a human sorts
#                  it out in a minute. Both failure messages below name this
#                  possibility explicitly so the fix is not "add a junk
#                  heading".
#   Under-reach -> a citation shape goes unmatched, the pointer ships dangling,
#                  and the suite stays green. That IS the original defect.
#
# Under-reach fails silent, so the pattern errs loose. The nearest live
# near-miss is docs/FAILURE_MODES.md's `CLAUDE.md lists "Session continuity
# (...)" as the priority-3 invariant` -- it does not match today (the word
# `lists` sits between), and if a reword ever makes it match, the result is a
# red that says what to check, not a silent hole.
# The matcher itself now lives in `tests/_doc_pointers.py`, generalized over
# any `*.md` filename, because the same form points across documents and not
# only at CLAUDE.md -- eleven such pointers ship today. This module keeps the
# CLAUDE.md SPECIALIZATION and the reasoning above; the shared version keeps
# the pattern. One spelling, two consumers.
#
# One narrowing came with the generalization and is safe here: the shared
# matcher accepts only double quotes. `'` was fine while the filename was
# fixed (almost nobody writes `CLAUDE.md's`), but across every filename a
# possessive -- `` `cc/GOAL.md`s owed-list `` -- reads as an opening quote.
# Verified byte-identical derivation on the live population before the switch.
def _citations_in(text: str) -> list[str]:
    """CLAUDE.md section names cited in ``text``."""
    return [
        section for filename, section in section_citations(text)
        if filename.lower() == "claude.md"
    ]


# Every surface `espalier init` puts on the adopter's tree that could carry a
# citation, derived from the deploy inventories rather than hand-picked.
#
# NOTE for whoever widens this next: do NOT simply add `espalier/*.py`.
# `espalier/surface_impact.py` contains `CLAUDE.md '## Hooks'` and
# `CLAUDE.md '## Slash Commands'`, which would derive section names of
# `## Hooks` and demand a `## ## Hooks` heading in the skeleton. Those strings
# describe the self-host maintainer's obligation list, not an adopter pointer.
def _adopter_visible_doc_sources() -> list[tuple[str, Path]]:
    assets = REPO_ROOT / "espalier" / "assets"
    # Read each seed's BODY through `get_seed_asset_source`, never `REPO_ROOT /
    # rel`. Two seeds are Tier-3 stubs whose destination path collides with a
    # far larger self-host document of the same name: `docs/SHARP_EDGES.md`
    # ships 26 lines against this repo's 4,295, and `docs/CONVENTIONS.md` ships
    # 30 against 1,999. Resolving by destination reads the self-host copy, so a
    # citation living only in text an adopter never receives is derived as
    # though it were adopter-visible -- the exact substitution the
    # `_SEED_ASSET_SOURCES` indirection exists to prevent, and one this class
    # cannot notice on its own: `test_every_adopter_visible_doc_source_resolves`
    # proves the path is READABLE, which is true of both copies.
    #
    # The label stays the DESTINATION path: that is where the adopter meets the
    # citation, so it is the right thing to name in a failure message.
    sources: list[tuple[str, Path]] = [
        (rel, assets.joinpath(*managed_inventory.get_seed_asset_source(rel).split("/")))
        for rel in managed_inventory.get_seed_docs()
    ]
    # The deploy SOURCE for .claude/{agents,commands,skills}. Byte-mirrored
    # from .claude/, so either side would do; this is the one init copies.
    sources += [
        (str(p.relative_to(REPO_ROOT)), p)
        for p in sorted((assets / "claude").rglob("*.md"))
    ]
    return sources


def _cited_claude_md_sections() -> dict[str, set[str]]:
    """Derive every CLAUDE.md section an adopter-visible surface cites by name.

    Several populations, because the citation reaches the adopter through more
    than one carrier and a fix covering only one would leave the others
    dangling:

    - ``tools/cc/hooks/*.py`` -- hook deny messages and stderr advisories.
    - the SEEDED docs and the deployed ``.claude/`` assets
      (``_adopter_visible_doc_sources``, derived from the deploy inventories
      rather than hand-listed) -- ``init`` copies these onto the adopter's
      tree, so a citation in one is exactly as adopter-visible as a deny
      message.

    The hook scan walks ``ast.Constant`` string values rather than raw source
    text, which is load-bearing in two directions and NOT an optimization:

    - Implicit adjacent-literal concatenation is folded by the parser, so a
      citation split across source lines (``"... CLAUDE.md \\"Maintenance "``
      / ``"mode\\" section."`` in ``_denial_reasons.py``) is still found. A
      regex over raw source misses exactly that one -- and that one was the
      live defect, so a source-text scan would have shipped green.
    - Comments are not Constant nodes, so a source comment mentioning a
      section (``write_guard.py`` has one) is correctly ignored: a comment is
      not adopter-visible and cannot strand anybody.

    The docs are markdown, so they are scanned as text -- every byte of a
    deployed doc is adopter-visible; there is no comment layer to exclude.

    Unreadable doc paths are skipped here rather than raised, because this runs
    at COLLECTION time (it feeds a parametrize) and an exception would abort
    collection instead of failing a test. The skip is not silent:
    ``test_every_adopter_visible_doc_source_resolves`` asserts the population
    is fully resolvable, so a doc carrier that goes dark fails loudly there.
    """
    cited: dict[str, set[str]] = {}
    for path in sorted(HOOKS_DIR.glob("*.py")):
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for name in _citations_in(node.value):
                    cited.setdefault(name, set()).add(path.name)
    for rel, doc in _adopter_visible_doc_sources():
        if not doc.is_file():
            continue
        for name in _citations_in(
            doc.read_text(encoding="utf-8", errors="replace")
        ):
            cited.setdefault(name, set()).add(rel)
    return cited


@pytest.mark.skipif(
    not is_self_host_repo(REPO_ROOT),
    reason=(
        "Compares the engine's own citations to the engine's own CLAUDE.md "
        "renderer -- both are upstream artifacts, so an adopter checkout has "
        "nothing to check. The adopter-side signal is the init/upgrade nudge, "
        "which reports against the CLAUDE.md actually on their tree."
    ),
)
class TestRequiredClaudeMdSectionsAreRendered:
    """Contract 4: ``denial-reason-dangling-citation`` -- a hook may only cite
    a CLAUDE.md section that ``espalier init`` actually puts on the adopter's
    tree.

    The failure this closes (DEF-428 / DEF-494): ``_denial_reasons.py`` told a
    blocked adopter to ``See CLAUDE.md "Maintenance mode" section`` while
    ``_build_claude_md`` rendered no such section -- dead on *every* adopter
    tree, including a clean first install. Nothing in init, doctor, audit or
    the SessionStart banner noticed, because nothing compared the two sides.

    Neither side is hand-maintained here: the citations are derived from the
    hook tree and the sections from the real template renderer, so a new deny
    message that cites a new section fails until the section exists.
    """

    def test_every_adopter_visible_doc_source_resolves(self) -> None:
        """The doc half of the population must actually be readable.

        ``_cited_claude_md_sections`` skips an unresolvable path (it runs at
        collection time and cannot raise), so without this the whole doc
        carrier could go dark -- e.g. if ``get_seed_docs()`` were refactored to
        return paths relative to ``espalier/assets/`` instead of the repo root
        -- and every downstream check would stay green on the hook citations
        alone.
        """
        missing = [
            rel for rel, path in _adopter_visible_doc_sources()
            if not path.is_file()
        ]
        assert not missing, (
            f"{len(missing)} adopter-visible doc source(s) do not resolve "
            f"under {REPO_ROOT}: {missing[:5]}. The citation scan skips what "
            f"it cannot read, so this carrier is silently contributing "
            f"nothing."
        )

    def test_each_citation_carrier_is_still_producing(self) -> None:
        """Per-carrier vacuity guard.

        A single non-empty assertion over the UNION is not enough: either
        carrier can go to zero while the other keeps the total non-empty, and
        the sections only that carrier cited then vanish from the derived set
        -- which reads as "citation legitimately removed" rather than "scanner
        broke".
        """
        cited = _cited_claude_md_sections()
        sources = {src for srcs in cited.values() for src in srcs}
        from_hooks = {s for s in sources if s.endswith(".py")}
        from_docs = sources - from_hooks
        assert from_hooks, (
            "Zero CLAUDE.md section citations derived from the hook tree "
            f"({HOOKS_DIR}). Either every hook citation was removed, or the "
            "AST walk / pattern broke and the hook carrier is now vacuous."
        )
        assert from_docs, (
            "Zero CLAUDE.md section citations derived from the deployed docs "
            "and .claude/ assets. Either every doc citation was removed, or "
            "the population no longer resolves and that carrier is vacuous."
        )

    def test_every_derived_citation_is_declared_required(self) -> None:
        """SUBSET, deliberately not equality.

        ``cli.REQUIRED_CLAUDE_MD_SECTIONS`` is a ratchet: a new citation must
        be added to it, but losing a citation never forces one out. Equality
        was tried first and had to go -- under `==`, rewording the single
        prose clause that names a section walks the next person through
        un-requiring it, and the "obvious" remedy (shrink the tuple) is the
        wrong side of the equality. This operator removes that hazard
        structurally instead of warning about it in a message: there is no
        `derived shrank` red to mis-answer.
        """
        cited = _cited_claude_md_sections()
        undeclared = set(cited) - set(cli.REQUIRED_CLAUDE_MD_SECTIONS)
        assert not undeclared, (
            f"{sorted(undeclared)} is cited as a CLAUDE.md section but is not "
            f"in cli.REQUIRED_CLAUDE_MD_SECTIONS.\n"
            f"  cited by: "
            f"{ {k: sorted(cited[k]) for k in sorted(undeclared)} }\n"
            f"If it is a real pointer: add it to the tuple AND render the "
            f"section in _build_claude_md. If it is NOT a section reference "
            f"-- the pattern reads any quoted phrase just after 'CLAUDE.md' "
            f"as a section name, so prose like `CLAUDE.md \"...\" is the rule` "
            f"trips it -- fix the prose or the pattern, never by adding a junk "
            f"heading to every adopter's CLAUDE.md."
        )

    @pytest.mark.parametrize(
        "section", sorted(cli.REQUIRED_CLAUDE_MD_SECTIONS)
    )
    def test_every_required_section_is_rendered(self, section: str) -> None:
        skeleton = cli.render_canonical_template("claude")
        citers = sorted(_cited_claude_md_sections().get(section, ())) or [
            "(no live citation -- still required by the tuple)"
        ]
        assert re.search(rf"(?m)^## {re.escape(section)}\b", skeleton), (
            f"{citers} name the CLAUDE.md {section!r} section, but "
            f"`espalier init` renders no '## {section}' heading, so the "
            f"pointer dead-ends on every adopter tree. Three possible fixes, "
            f"in the order worth checking:\n"
            f"  1. It IS a real pointer -> add the section to "
            f"espalier/cli.py::_build_claude_md (and to "
            f"REQUIRED_CLAUDE_MD_SECTIONS).\n"
            f"  2. It is a real pointer nobody needs -> drop the citation at "
            f"the source; each deny already states its remedy inline.\n"
            f"  3. It is NOT a section reference at all -- the pattern reads "
            f"any quoted phrase just after 'CLAUDE.md' as a section name, and "
            f"prose like `CLAUDE.md \"...\" is the rule` trips it. Then the "
            f"fix is the PROSE (or the pattern), never a junk heading in "
            f"every adopter's CLAUDE.md."
        )

    # Every adopter layout the fingerprinter can produce, plus the two
    # degenerate shapes. `harness_layered` is excluded on purpose: that is the
    # self-host repo, whose CLAUDE.md is hand-written and already carries the
    # sections.
    @pytest.mark.parametrize(
        "architecture",
        [
            {"pattern": "src_layout"},
            {"pattern": "flat"},
            {"pattern": "mvc"},
            {"pattern": None},   # fingerprinted, no pattern determined
            {},                  # unfingerprintable / empty tree
        ],
        ids=["src_layout", "flat", "mvc", "pattern-none", "no-architecture"],
    )
    @pytest.mark.parametrize(
        "section", sorted(cli.REQUIRED_CLAUDE_MD_SECTIONS)
    )
    def test_required_section_renders_for_every_adopter_layout(
        self, section: str, architecture: dict
    ) -> None:
        """The citation is unconditional, so the section must be too.

        ``render_canonical_template`` pins one fingerprint. A section rendered
        behind an architecture check would pass that pin and still be missing
        on a real adopter -- which is exactly what happened: the ``## Plan
        Guard`` block was gated on a truthy ``pattern``, and the canonical
        fingerprint hard-coded ``{"pattern": "flat"}`` with a comment saying
        the default "omits it". The snapshot was made representative instead of
        the renderer being made correct, so the gap stayed invisible.
        """
        fp = dataclasses.replace(
            cli._canonical_template_fingerprint(), architecture=architecture
        )
        rendered = cli._build_claude_md(fp, cli._canonical_template_build_plan())
        assert re.search(rf"(?m)^## {re.escape(section)}\b", rendered), (
            f"architecture={architecture!r} renders a CLAUDE.md with no "
            f"'## {section}' heading, but {sorted(_cited_claude_md_sections()[section])} "
            f"require that section. An adopter on this layout "
            f"follows the pointer and finds nothing."
        )


@pytest.mark.skipif(
    not is_self_host_repo(REPO_ROOT),
    reason=(
        "Denial-reason contract is self-host-only; adopters customize "
        "their own _denial_reasons.py without firing this test."
    ),
)
class TestDenialReasons:
    def test_no_fstring_in_deny_call(self):
        """Contract 1: ``deny(f"...")`` / ``block(f"...")`` direct
        f-string arg is forbidden. Catches naive inlining drift.
        """
        offenders: list[str] = []
        for hook_name in DENYING_HOOKS:
            hook_path = HOOKS_DIR / hook_name
            tree = _parse(hook_path)
            source_lines = hook_path.read_text(encoding="utf-8").splitlines()
            for call in _find_deny_calls(tree):
                if not _arg_is_fstring(call):
                    continue
                # Honor opt-out: a `# contract: ok denial-reason-fstring <reason>`
                # marker on the same line passes. Line numbers are 1-indexed.
                lineno = getattr(call, "lineno", 0)
                if 0 < lineno <= len(source_lines):
                    line = source_lines[lineno - 1]
                    if "contract: ok denial-reason-fstring" in line:
                        continue
                offenders.append(
                    f"{hook_name}:{lineno}: deny/block called with "
                    f"inline f-string — compose from _denial_reasons "
                    f"template instead, or annotate with "
                    f"`# contract: ok denial-reason-fstring <reason>`"
                )
        assert not offenders, "\n".join(offenders)

    def test_hooks_with_deny_import_denial_reasons(self):
        """Contract 2: every hook calling deny/block imports
        ``_denial_reasons``. Catches hooks that bypass the SoT entirely.
        """
        missing: list[str] = []
        for hook_name in DENYING_HOOKS:
            hook_path = HOOKS_DIR / hook_name
            tree = _parse(hook_path)
            calls = _find_deny_calls(tree)
            if not calls:
                continue
            if not _hook_imports_denial_reasons(tree):
                missing.append(
                    f"{hook_name}: calls deny/block but does not import "
                    f"_denial_reasons (expected `import _denial_reasons` "
                    f"after the sys.path.insert shim)"
                )
        assert not missing, "\n".join(missing)

    def test_no_dead_template_constants(self):
        """Contract 3: every str-assigned constant in
        ``_denial_reasons.py`` is referenced by at least one hook.
        Catches orphaned templates that drift out of sync.
        """
        defined = _collect_denial_reason_constants()
        hook_paths = [HOOKS_DIR / name for name in DENYING_HOOKS]
        referenced = _collect_references(hook_paths, defined)
        unused = sorted(defined - referenced)
        assert not unused, (
            f"Dead templates in _denial_reasons.py (defined but not "
            f"referenced by any of {list(DENYING_HOOKS)}): {unused}. "
            f"Either delete the constant or wire it into the hook that "
            f"needs it."
        )


class TestOperatorFacingTemplatesPairWrongAndRight:
    """FM-13 close: every operator-facing template must model both
    wrong-shape and right-shape per §1.6 habit-formation contract.

    Asserted via TIGHT substring presence: each template named in
    ``_OPERATOR_FACING_TEMPLATES`` MUST contain the literal ``Don't:``
    AND the literal ``Do:`` marker. Broad markers (``NOT ``, ``Run ``,
    ``Use ``, ``Avoid:``) false-pass on incidental prose (e.g.
    ``does NOT authorize``, ``Run /implement-task``) and let templates
    pass without real wrong/right pairing -- this was caught by the
    TP-144 v1 0-A review and prompted the tight-marker rewrite.

    Future template authors who copy an existing operator-facing
    template inherit the pairing requirement -- adding a new name to
    ``_OPERATOR_FACING_TEMPLATES`` without the markers fails this test
    rather than shipping silently.
    """

    _ANTI_MARKER = "Don't:"
    _POSITIVE_MARKER = "Do:"

    @pytest.mark.parametrize(
        "template_name", list(_denial_reasons._OPERATOR_FACING_TEMPLATES)
    )
    def test_template_contains_both_markers(self, template_name: str) -> None:
        template = getattr(_denial_reasons, template_name)
        has_anti = self._ANTI_MARKER in template
        has_pos = self._POSITIVE_MARKER in template
        assert has_anti and has_pos, (
            f"{template_name} is in _OPERATOR_FACING_TEMPLATES but its "
            f"string body lacks both {self._ANTI_MARKER!r} and "
            f"{self._POSITIVE_MARKER!r}. §1.6 contract requires both. "
            f"Add a 'Don't: ...; Do: ...' pair (with the literal prefix "
            f"+ colon shape), OR remove the template from "
            f"_OPERATOR_FACING_TEMPLATES if it's diagnostic (reports a "
            f"fault) rather than instructional."
        )


class TestKillSwitchRemediation:
    """The kill-switch denial's *remediation* (the ``Do:`` line) must name the
    setting that actually fired (via ``{findings}``), not a hardcoded
    ``disableAllHooks`` line — which may not be the switch that tripped (e.g.
    ``bypassPermissions``), telling the operator to remove a line that isn't there.
    """

    def test_do_line_names_the_fired_setting(self) -> None:
        rendered = _denial_reasons.KILL_SWITCH_DETECTED.format(
            context=" in local change", findings="bypassPermissions: true"
        )
        do_line = next(
            ln for ln in rendered.splitlines() if ln.strip().startswith("Do:")
        )
        assert "bypassPermissions" in do_line, (
            "the Do: remediation should name the fired setting via {findings}, "
            f"got: {do_line!r}"
        )
        assert "disableAllHooks" not in do_line, (
            "the Do: line still hardcodes `disableAllHooks` instead of the "
            "setting that actually fired"
        )

    def test_dont_line_still_names_the_canonical_switch(self) -> None:
        # The Don't: anti-pattern line correctly keeps disableAllHooks as the
        # canonical kill-switch example — only the Do: remediation was wrong.
        rendered = _denial_reasons.KILL_SWITCH_DETECTED.format(
            context="", findings="disableAllHooks: true"
        )
        dont_line = next(
            ln for ln in rendered.splitlines() if ln.strip().startswith("Don't:")
        )
        assert "disableAllHooks" in dont_line


class TestDangerousBashPlainEnglish:
    """TP-189-B (FRICTION-2): the auto-generated dangerous-bash deny no longer
    quotes the raw regex source — it resolves a plain-English description by
    record pid and offers a way forward. ``format_dangerous_bash`` takes the
    stable pid, not the pattern source."""

    # regex metacharacters that must never leak into an operator-facing reason
    _REGEX_METACHARS = ("\\s", "\\b", "+rf", "[/]", ".*")

    def test_plain_english_no_raw_regex(self) -> None:
        reason = _denial_reasons.format_dangerous_bash("rm-rf-root")
        for meta in self._REGEX_METACHARS:
            assert meta not in reason, (
                f"format_dangerous_bash leaked the regex metachar {meta!r} "
                f"into the operator-facing reason: {reason!r}"
            )

    def test_plain_english_describes_intent(self) -> None:
        reason = _denial_reasons.format_dangerous_bash("rm-rf-root")
        assert "recursive delete of the filesystem root itself" in reason, reason

    def test_plain_english_does_not_misreport_the_target(self) -> None:
        """The record is RIGHT-ANCHORED and fires only on the bare root.

        Until the 2026-08-24 re-tier the matcher denied every absolute operand
        and this pin forbade "the filesystem root" as a misreport. The re-tier
        flipped the fact under the pin and nobody moved the pin: for two weeks
        the text told an operator who typed `rm -rf /` that the guard refuses
        an absolute path "whether or not the target is the filesystem root" --
        the old matcher's sentence over the new one (DEF-739). The guarded
        claim is now the inverse: the reason must not describe the target as
        merely absolute, because an absolute target is not what fired.
        """
        reason = _denial_reasons.format_dangerous_bash("rm-rf-root")
        assert "whether or not" not in reason, reason
        assert "of an absolute path" not in reason, reason

    def test_plain_english_offers_way_forward(self) -> None:
        reason = _denial_reasons.format_dangerous_bash("rm-rf-root")
        assert "narrow the target" in reason, reason

    def test_remedy_is_satisfiable(self) -> None:
        """A remedy no input can satisfy is not a way forward.

        Two texts each named an axis that did not clear the deny. "a specific
        path" -- `rm -rf /tmp/scratch` already IS one. Then "relative to the
        repo", true until the 2026-08-24 re-tier and false since: `rm -rf
        <repo>/build` and `rm -rf /tmp/x` are absolute and fall to the soft
        tier, while an absolute `..` step does not. The axis is what the
        target MEANS, so the remedy names what runs and what is refused in
        the operator's terms.
        """
        reason = _denial_reasons.format_dangerous_bash("rm-rf-root")
        assert "relative to the repo" not in reason, reason
        assert "inside the repo" in reason and "temp root" in reason, reason

    def test_hard_tier_texts_name_the_rule_the_classifier_enforces(self) -> None:
        """The vocabulary of ``_bash_patterns._target_is_catastrophic``, on
        both hard-tier texts: what is refused (the root, home, the repo, a
        shallow system path, the unbounded glob, an absolute ``..`` step) and
        what is not (inside the repo or home, under a temp root). A text that
        drops one of these describes a different guard than the one that
        fired; the soft tier's CP-RMRF body says the same split from its side.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_speedbump_for_text", HOOKS_DIR / "_speedbump.py",
        )
        speedbump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(speedbump)
        # Every hard-tier text shares the judge (`_target_is_catastrophic`), so
        # every one shares the vocabulary: the rm text, the find spelling
        # (DEF-815), the PowerShell sweep (DEF-824 / DEF-822), the carrier
        # (DEF-826) and the loop carrier (DEF-830). DERIVED by prefix so a sixth
        # wall's reason is enrolled the day it lands (the DEF-830 review: a
        # hand-listed five would let it ship with no vocabulary check); the
        # five known names are the floor, never the whole.
        catastrophic = {
            name: text for name, text in vars(_denial_reasons).items()
            if name.startswith("CATASTROPHIC_") and isinstance(text, str)
        }
        assert {
            "CATASTROPHIC_RM", "CATASTROPHIC_FIND_DELETE", "CATASTROPHIC_PS_SWEEP",
            "CATASTROPHIC_PIPED_REMOVE", "CATASTROPHIC_LOOP_REMOVE",
        } <= set(catastrophic), sorted(catastrophic)
        for text in (
            _denial_reasons.format_dangerous_bash("rm-rf-root"),
            *(catastrophic[name] for name in sorted(catastrophic)),
        ):
            for phrase in ("filesystem root", "home directory", "the repo",
                           "shallow system path", "'*'", "'..'",
                           "inside the repo", "temp root"):
                assert phrase in text, (phrase, text)
            assert "absolute" not in text.replace("an absolute path with a '..'", ""), text
        soft = speedbump.CP_RMRF.body
        for phrase in ("home directory", "the repo itself", "shallow system paths",
                       "inside the repo", "$VAR path other than $HOME"):
            assert phrase in soft, (phrase, soft)
        assert "absolute/glob" not in soft and " ~ " not in soft, soft

    @pytest.mark.parametrize("spelling, classifier, overrides", [
        ("rm -rf {t}", "has_catastrophic_recursive_rm", {}),
        # DEF-842: the text says "forced or not", so every claim is driven
        # through the unforced spelling too, on both tools; the PowerShell
        # arm's text states the variable rule the defaults already hold ($HOME
        # refused, any other $VAR the nudge's -- operator, 2026-09-18)
        ("rm -r {t}", "has_catastrophic_recursive_rm", {}),
        ("Remove-Item -Recurse {t}", "powershell_recursive_removal_is_catastrophic", {}),
        ("rm -r {t}", "powershell_recursive_removal_is_catastrophic", {}),
        # DEF-815: the enumerator spelling shares the classifier, so the same
        # claims are driven through it (the review: the text was pinned by
        # vocabulary alone, and a re-tier would have left it green)
        ("find {t} -delete", "has_catastrophic_find_delete", {}),
        # DEF-824: the PowerShell tool's sweep classifier, with the one claim
        # its text states differently -- a variable in the root is refused
        # there, as the Remove-Item tier refuses it
        ("find {t} -delete", "has_catastrophic_ps_sweep", {"$VAR": True}),
        # DEF-822: the enumerator pipeline through the same classifier. A
        # root whose leaf is a bare `*` is its directory (the review batch:
        # `gci * -Recurse` takes everything under `.`), so the unbounded
        # glob claims hold as they do for rm; a BOUNDED wildcard root
        # (`*.egg-info`) narrows, as the text says
        ("gci {t} -Recurse | ri -r -fo", "has_catastrophic_ps_sweep", {"$VAR": True}),
        # DEF-826: the enumerator piped through xargs into a remove verb, on
        # the Bash tool's union classifier and the PowerShell tool's
        ("find {t} | xargs rm -rf", "has_catastrophic_bash_sweep", {}),
        ("find {t} | xargs rm -rf", "has_catastrophic_ps_sweep", {"$VAR": True}),
        # DEF-830: the enumerator bound to a loop variable and removed in the
        # body, on its three enumerator heads, through the Bash tool's union
        # classifier; DEF-837: a for loop's own word list, the fourth head --
        # the text names it, so every claim must hold for it too
        ('find {t} | while read f; do rm -rf "$f"; done', "has_catastrophic_bash_sweep", {}),
        ('for f in $(find {t}); do rm -rf "$f"; done', "has_catastrophic_bash_sweep", {}),
        ('while read f; do rm -rf "$f"; done < <(find {t})', "has_catastrophic_bash_sweep", {}),
        ('for f in {t}; do rm -rf "$f"; done', "has_catastrophic_bash_sweep", {}),
    ])
    def test_the_claims_hold_against_the_classifier(
        self, tmp_path, monkeypatch, spelling, classifier, overrides,
    ) -> None:
        """Text-to-code, not text-to-text: each sentence of the hard-tier texts
        is a claim about ``_bash_patterns.has_catastrophic_recursive_rm`` (and
        its find twin), and DEF-739 was exactly a classifier re-tier that left
        the phrases green. One row per claim, in both directions, driven
        through the classifier with the repo at ``tmp_path`` and the home
        directory pinned, so a re-tier reds here beside the text it just
        falsified."""
        import sys
        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        import _bash_patterns
        home = tmp_path / "home"
        home.mkdir()
        repo = tmp_path / "repo"
        (repo / "build").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(_bash_patterns.os.path, "expanduser",
                            lambda p: p.replace("~", str(home), 1))
        # Spelled as a shell would receive them: a backslash path in a Bash
        # command is not a spelling -- quote removal collapses `C:\Users\x`
        # to `C:Usersx` -- and a Windows host types `C:/...` or `/c/...`, so the
        # targets that go INTO the command text are posix-spelled. The ROOT and
        # the cwd handed to the judge stay `str(repo)`, the hook payload's own
        # spelling on every host (backslashes on Windows), which is the form
        # the judge must read right (the bare-glob arm did not, 2026-09-23).
        claims = {
            # refused (the text's "are refused in every flag order" list)
            "/": True,                          # the filesystem root
            "*": True,                          # a bare glob: the directory it expands in
            "/*": True,
            repo.as_posix() + "/*": True,       # the repo by its absolute root (DEF-843)
            "~/*": True,                        # the home directory, likewise
            "~": True,                          # your home directory
            "$HOME": True,
            home.as_posix(): True,
            repo.as_posix(): True,              # the repo itself
            tmp_path.as_posix(): True,          # a parent of either
            "/etc": True,                       # a shallow system path
            "/usr/local": True,
            "/opt/x/../y": True,                # an absolute path with a '..' step
            # not refused here (the soft tier's, or nothing's)
            "/usr/local/share/x": False,        # deeper than shallow
            (repo / "build").as_posix(): False, # inside the repo
            "~/proj/thing": False,              # inside your home directory
            "build": False,                     # a relative build/
            "*.egg-info": False,                # a BOUNDED glob
            "$VAR": False,                      # a $VAR path other than $HOME
        }
        claims.update(overrides)
        judge = getattr(_bash_patterns, classifier)
        wrong = {
            target: got
            for target, want in claims.items()
            if (got := judge(spelling.format(t=target), str(repo))) != want
        }
        assert not wrong, f"the text's claims and the classifier disagree: {wrong}"
        if classifier in ("has_catastrophic_find_delete", "has_catastrophic_ps_sweep") \
                and spelling.startswith("find"):
            # the find text's own remedy claims: a name-or-path predicate
            # placed before the action narrows; placed after, negated, or
            # under an -o it does not; an attribute test never does
            for command, want in (
                ("find " + repo.as_posix() + " -name '*.pyc' -delete", False),
                ("find " + repo.as_posix() + " -delete -name '*.pyc'", True),
                ("find " + repo.as_posix() + " ! -name '*.pyc' -delete", True),
                ("find " + repo.as_posix() + " -name '*.pyc' -o -delete", True),
                ("find " + repo.as_posix() + " -type f -delete", True),
                ("find " + repo.as_posix() + " -size +0c -delete", True),
            ):
                assert judge(command, str(repo)) is want, command
        # DEF-790: the text also says a relative target is read from the
        # directory the command runs in, after its own cd. Driven from the
        # repo, so a re-tier of that reading reds beside the sentence.
        placed = {
            "cd .. && rm -rf repo": True,       # the repo, reached by climbing out
            "cd / && rm -rf etc": True,         # a shallow system path
            "rm -rf build": False,              # a relative build/ there
            "cd .. && rm -rf build": False,     # beside the repo, under the temp root
            # DEF-849 / DEF-843: a bare '*' glob and `$PWD` are the directory
            # the delete runs in -- the repo walls, a directory inside it not
            "rm -rf *": True,
            "cd build && rm -rf *": False,
            'rm -rf "$PWD"': True,
            'cd build && rm -rf "$PWD"': False,
        }
        wrong = {
            cmd: got
            for cmd, want in placed.items()
            if (got := _bash_patterns.has_catastrophic_recursive_rm(
                cmd, str(repo), cwd=repo)) != want
        }
        assert not wrong, f"the text's placement claim and the classifier disagree: {wrong}"

    def test_catastrophic_rm_offers_way_forward(self) -> None:
        # The flag-order-independent hard-stop also points a way forward now.
        assert "narrow the target" in _denial_reasons.CATASTROPHIC_RM

    def test_unknown_pid_falls_back_gracefully(self) -> None:
        # An unrecognized pid must not KeyError; it yields a generic phrase.
        reason = _denial_reasons.format_dangerous_bash("no-such-pid")
        assert "Dangerous command blocked" in reason
        assert "{" not in reason  # template fully formatted, no stray field


class TestDangerousPsPlainEnglish:
    """TP-343: PowerShell parity with TestDangerousBashPlainEnglish. The
    auto-generated dangerous-PowerShell deny resolves a plain-English
    description by record pid (never the raw regex source) and offers a way
    forward. ``format_dangerous_ps`` takes the stable pid, not the pattern
    source."""

    # regex fragments that must never leak into an operator-facing reason
    _REGEX_METACHARS = ("\\s", ".{0,200}", "\\")

    def test_plain_english_no_raw_regex(self) -> None:
        reason = _denial_reasons.format_dangerous_ps(
            "ps-remove-item-recurse-force-prefix"
        )
        for meta in self._REGEX_METACHARS:
            assert meta not in reason, (
                f"format_dangerous_ps leaked the regex fragment {meta!r} "
                f"into the operator-facing reason: {reason!r}"
            )

    def test_plain_english_describes_intent(self) -> None:
        reason = _denial_reasons.format_dangerous_ps(
            "ps-remove-item-recurse-force-prefix"
        )
        assert "recursive force-delete via Remove-Item" in reason, reason

    def test_plain_english_offers_way_forward(self) -> None:
        reason = _denial_reasons.format_dangerous_ps(
            "ps-remove-item-recurse-force-prefix"
        )
        assert "will not clear this deny" in reason, reason

    def test_remedy_does_not_prescribe_an_impossible_narrowing(self) -> None:
        """The PS matcher is strictly broader than its Bash twin, so the twin's
        remedy is wrong here in a worse way.

        Driven 2026-08-22: ``ps-remove-item-recurse-force-*`` fires on EVERY
        ``-Recurse``+``-Force`` invocation -- including a RELATIVE target, which
        the Bash side allows. "Narrow the target to a specific path" therefore
        names an action that cannot clear the deny for ANY input, on the one
        platform this repo has the least execution coverage for.
        """
        reason = _denial_reasons.format_dangerous_ps(
            "ps-remove-item-recurse-force-prefix"
        )
        assert "narrow the target" not in reason, reason

    def test_unknown_pid_falls_back_gracefully(self) -> None:
        # An unrecognized pid must not KeyError; it yields a generic phrase.
        reason = _denial_reasons.format_dangerous_ps("no-such-pid")
        assert "Dangerous PowerShell command blocked" in reason
        assert "{" not in reason  # template fully formatted, no stray field
