"""Pin the hook-authoring SKILL.md against the canonical hook wiring.

SKILL.md is the authoring contract but had no mechanical guard; TP-328 added
this after two matcher claims (plan_guard, post_write_check) and four event
rows drifted from CANONICAL_HOOK_WIRING undetected. The checks are attribution-
aware on purpose: a whole-document substring search false-passes because the
same matcher/event strings appear elsewhere in the file for other hooks.
"""
import re
from pathlib import Path

import pytest

from espalier.harness_config import CANONICAL_HOOK_WIRING

_REPO = Path(__file__).resolve().parents[1]

# Class-fix scope: every shipped copy of the skill. Filter to those that exist
# so the example/asset trees can be reorganized without breaking this test.
_SKILL_PATHS = [
    p
    for p in (
        _REPO / ".claude/skills/hook-authoring/SKILL.md",
        _REPO / "examples/dogfooding/.claude/skills/hook-authoring/SKILL.md",
        _REPO / "espalier/assets/claude/skills/hook-authoring/SKILL.md",
    )
    if p.exists()
]


def _event_table(text: str) -> str:
    """The markdown table rows under the '## Hook event types' heading.

    Scoped to table rows (lines starting with '|') so the check can't be
    satisfied by an event name that merely appears in surrounding prose.
    """
    lines = text.splitlines()
    start = next(
        (i for i, l in enumerate(lines) if l.strip().startswith("## Hook event types")),
        None,
    )
    assert start is not None, "SKILL.md missing '## Hook event types' section"
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("## ")),
        len(lines),
    )
    return "\n".join(l for l in lines[start:end] if l.lstrip().startswith("|"))


@pytest.mark.parametrize("skill_path", _SKILL_PATHS, ids=lambda p: str(p.relative_to(_REPO)))
def test_skill_table_lists_every_governed_event(skill_path):
    table = _event_table(skill_path.read_text(encoding="utf-8"))
    events = {spec["event"] for spec in CANONICAL_HOOK_WIRING.values()}
    missing = sorted(e for e in events if f"`{e}`" not in table)
    assert not missing, (
        f"{skill_path.relative_to(_REPO)} 'Hook event types' table omits: {missing}"
    )


@pytest.mark.parametrize("skill_path", _SKILL_PATHS, ids=lambda p: str(p.relative_to(_REPO)))
def test_skill_matchers_attributed_to_correct_script(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    wrong = []
    for script, spec in CANONICAL_HOOK_WIRING.items():
        matcher = spec.get("matcher") or ""
        if not matcher:
            continue  # empty-matcher events carry no matcher string to attribute
        # `script.py` ... then the FIRST backtick-delimited matcher after it,
        # optionally wrapped in double quotes (`"X"` or `X`). [^`]*? cannot
        # cross into another hook's backticked name, so the match is attributed.
        pattern = re.escape(f"`{script}`") + r'[^`]*?`"?' + re.escape(matcher) + r'"?`'
        if not re.search(pattern, text):
            wrong.append(f"{script} -> {matcher!r}")
    assert not wrong, (
        f"{skill_path.relative_to(_REPO)} does not attribute the canonical "
        f"matcher to: {wrong} (SKILL.md drifted from CANONICAL_HOOK_WIRING)"
    )


def _binding_name_class() -> str:
    """The reader's own binding-name character class, loaded by path: modules
    under ``tools/cc/`` are never imported as a package (they must stay
    espalier-free), and the module is registered in ``sys.modules`` before
    ``exec_module`` per the 3.14 dataclass rule."""
    import importlib.util
    import sys

    path = _REPO / "tools" / "cc" / "hooks" / "_bash_patterns.py"
    spec = importlib.util.spec_from_file_location("_bash_patterns_for_skill_parity", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod._BINDING_NAME


def _variable_indirect_bullet(text: str) -> str:
    """The `Variable-indirect:` bullet, whole: from its line to the next bullet
    or blank line, so a claim continued on the next line is read."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if "Variable-indirect:" in l)
    end = start + 1
    while end < len(lines) and lines[end].strip() and not lines[end].lstrip().startswith("- "):
        end += 1
    return " ".join(l.strip() for l in lines[start:end])


@pytest.mark.parametrize("skill_path", _SKILL_PATHS, ids=lambda p: str(p.relative_to(_REPO)))
def test_skill_binding_sentence_carries_no_case_restriction(skill_path):
    """The skill's variable-indirect bullet and the reader's binding-name class
    agree that a binding's NAME CASE is not a limit. Until 2026-09-19 the
    pre-pass read uppercase names only and the bullet said so; the widening
    (`DEF-847`) corrected the bullet, and nothing pinned the sentence to the
    reader -- the pre-cut review found the shipped skill still declaring the
    closed limit in one copy. Two halves: the reader admits a lowercase name
    (a narrowing reds here, naming the class), and the bullet states the
    widened scope without a case word (a re-declared limit reds here, naming
    the copy). The named user: the adopter authoring a hook from the skill,
    who would design around a limit the reader no longer has."""
    name_class = _binding_name_class()
    assert re.fullmatch(name_class, "lower_case") and re.fullmatch(name_class, "UPPER"), (
        f"_BINDING_NAME no longer admits both cases: {name_class!r}"
    )
    bullet = _variable_indirect_bullet(skill_path.read_text(encoding="utf-8"))
    assert "any name case" in bullet, (
        f"{skill_path.relative_to(_REPO)}: the Variable-indirect bullet no longer "
        f"states the widened scope (expected 'any name case'): {bullet!r}"
    )
    assert not re.search(r"upper-?case", bullet, re.IGNORECASE), (
        f"{skill_path.relative_to(_REPO)}: the Variable-indirect bullet declares a "
        f"case limit the reader closed on 2026-09-19: {bullet!r}"
    )


@pytest.mark.parametrize("skill_path", _SKILL_PATHS, ids=lambda p: str(p.relative_to(_REPO)))
def test_skill_events_attributed_to_correct_script(skill_path):
    """Every hook script's canonical *event* must be attributed to that script
    in the wiring prose. Catches an event mislabel (e.g. documenting
    `config_guard.py` under SessionStart) that the other two checks miss: the
    matcher check is blind to the six empty-matcher hooks, and the table check
    only verifies an event name appears *somewhere*, not which script owns it.
    """
    text = skill_path.read_text(encoding="utf-8")
    wrong = []
    for script, spec in CANONICAL_HOOK_WIRING.items():
        event = spec["event"]
        # `script.py` then, after optional whitespace, `(<Event>` — closed by a
        # comma or paren so a prefix event can't satisfy a longer one (e.g.
        # `PostToolUse` must not match a `PostToolUseFailure` mislabel).
        pattern = re.escape(f"`{script}`") + r"\s*\(" + re.escape(event) + r"[,)]"
        if not re.search(pattern, text):
            wrong.append(f"{script} -> {event}")
    assert not wrong, (
        f"{skill_path.relative_to(_REPO)} does not attribute the canonical "
        f"event to: {wrong} (SKILL.md wiring prose drifted from CANONICAL_HOOK_WIRING)"
    )
