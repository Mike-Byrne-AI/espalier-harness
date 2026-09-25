"""TP-184 (adversarial follow-up): the engine's interactive operator hints must
not tell an operator to run a bare ``espalier <subcommand>``.

A FUSION vendors ``espalier/`` with NO ``espalier`` console-script — the engine
runs as ``python -m espalier`` — so any printed *hint* of the form
``espalier <verb>`` is command-not-found in a fusion. TP-182 C5 fixed the
deployed command/skill/agent bodies; TP-184 B7 fixed cli.py's ``cmd_init`` + the
hint destinations it routes to. The B7 hand-conversion repeatedly UNDER-counted
the sites (cmd_init's "six" was really eight; doctor.py held ~8 more), which is
the "enumeration under-counts — grep yourself" footgun. This gate is the
MECHANICAL replacement for that hand-grep: it pins the rule so a future hint
cannot silently regress.

Scope = the operator-command surface (``cli.py``, ``fuse.py``, ``doctor.py``).
The subcommand list is derived LIVE from :func:`espalier.cli.build_parser`, so a
newly-added subcommand is covered automatically (no static verb list to drift).

The contract is **interactive hints**, NOT generated content. The scan therefore
excludes:

- **docstrings** — describe, never instruct;
- **comments** — not string constants in the AST;
- ``python -m espalier <verb>`` — the correct form (negative lookbehind on ``-m ``);
- **markdown-document templates** — the strings ``_build_claude_md`` /
  ``_build_memory_md`` / the memory-prune marker emit are generated *docs/data*,
  not interactive hints. They are governed elsewhere: the fusion's own
  ``FINISH_UP_STEPS`` rewrites the overlaid docs host-generic, and example
  commands inside a code block / table are reference material, not a hint the
  operator copy-pastes from a command's stderr. A string carrying markdown
  structure (a heading, a fenced code block, or a table) is treated as a
  template and skipped. (f-strings are reconstructed whole before this test, so
  a marker like ``f"## Pruned {d} (via espalier memory prune)"`` — whose ``##``
  and ``espalier`` live in different literal segments — is correctly seen as a
  template.)

There is intentionally no per-string allowlist on the verb axis: descriptive
prose that NAMES the tool in an interactive (non-markdown) string must be
reworded to avoid the ``espalier <verb>`` shape (the scan cannot tell
instruction from mention).

A second axis (DEF-383a, at the bottom of this file) pins the INTERPRETER the
same hints spell: a literal ``python``/``python3`` before ``-m``, ``-c`` or a
``.py`` path is command-not-found on stock macOS (no ``python``) and wrong on any
host whose interpreter is not the one spelled -- ``cli._detect_python_command``
resolves the name, and every hint threads it in. That axis carries a NAMED,
self-expiring allow-list because one literal is genuinely right (a settings
rule quoted verbatim).
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from espalier.cli import build_parser

REPO_ROOT = Path(__file__).resolve().parent.parent

# The operator-command surface: modules that print runtime operator guidance.
SCANNED_FILES = (
    "espalier/cli.py",
    "espalier/fuse.py",
    "espalier/doctor.py",
)

# Markdown structure that marks a string as a generated DOCUMENT template (not an
# interactive hint): an ATX heading, a fenced code block, or a table separator.
_DOC_TEMPLATE_RE = re.compile(r"(?m)^#{1,6}\s|```|^\s*\|?\s*[-:]{3,}")


def _live_subcommands() -> set[str]:
    """Top-level subcommand names, read live from the argparse parser."""
    parser = build_parser()
    names: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            names.update(action.choices.keys())
    return names


def _bare_espalier_pattern() -> re.Pattern[str]:
    # Longest-first so `espalier audit-accuracy` reports the full verb, not `audit`.
    verbs = sorted(_live_subcommands(), key=len, reverse=True)
    alt = "|".join(re.escape(v) for v in verbs)
    # `espalier <verb>` NOT immediately preceded by `-m ` (python -m espalier ...).
    return re.compile(rf"(?<!-m )\bespalier\s+(?:{alt})\b")


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _joinedstr_child_ids(tree: ast.AST) -> set[int]:
    """ids of Constants that are SEGMENTS of an f-string — processed via the
    whole JoinedStr, never standalone (so the doc-template check sees the f-string
    as one unit, not per-segment)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant):
                    ids.add(id(value))
    return ids


def _reconstruct_joinedstr(node: ast.JoinedStr) -> str:
    """Literal text of an f-string with ``{}`` standing in for each interpolation
    (so the markdown structure of a split template is preserved)."""
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("{}")
    return "".join(parts)


def _scannable_strings(tree: ast.AST):
    """Yield (text, lineno) for each string expression that is neither a docstring
    nor an f-string segment: plain str Constants and reconstructed f-strings."""
    docstrings = _docstring_constant_ids(tree)
    fstring_children = _joinedstr_child_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield _reconstruct_joinedstr(node), node.lineno
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docstrings and id(node) not in fstring_children):
            yield node.value, node.lineno


def test_no_bare_espalier_subcommand_in_engine_runtime_strings():
    pattern = _bare_espalier_pattern()
    offenders: list[str] = []
    for rel in SCANNED_FILES:
        path = REPO_ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for text, lineno in _scannable_strings(tree):
            if _DOC_TEMPLATE_RE.search(text):
                continue  # generated-document template, not an interactive hint
            for match in pattern.finditer(text):
                snippet = " ".join(text.split())[:70]
                offenders.append(
                    f"{rel}:{lineno}: {match.group(0)!r}  (in {snippet!r})"
                )
    assert not offenders, (
        "Bare `espalier <subcommand>` in interactive operator hints — command-"
        "not-found in a fusion (the engine runs as `python -m espalier`). Use "
        "`python -m espalier <subcommand>`:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\n(Descriptive prose that NAMES the tool without instructing the "
        "operator to run it must be reworded to avoid the `espalier <verb>` shape "
        "— the scan cannot tell instruction from mention, and there is no allowlist. "
        "Generated docs are excluded automatically via their markdown structure.)"
    )


# ── Positive controls: prove the gate's MECHANISM can fire (earn-the-gate) ──
# Without these, a future refactor that neutered the pattern/exclusions would
# leave the source-scan test vacuously green forever.


def test_pattern_fires_on_a_bare_hint():
    pattern = _bare_espalier_pattern()
    assert pattern.search("Run `espalier init .` to set up the harness.")
    assert pattern.search("re-run: espalier audit .")


def test_pattern_does_not_fire_on_python_m_form():
    pattern = _bare_espalier_pattern()
    assert not pattern.search("Run `python -m espalier init .` to set up.")
    assert not pattern.search("[sys.executable, '-m', 'espalier', 'fingerprint']")


def test_pattern_ignores_non_subcommand_and_hyphenated_tokens():
    pattern = _bare_espalier_pattern()
    assert not pattern.search("the espalier-harness project")  # no whitespace+verb
    assert not pattern.search("pip install espalier")          # no verb follows


def test_doc_template_with_a_bare_hint_is_excluded():
    # A heading / fenced block / table marks generated-doc content -> skipped,
    # even though it literally contains a bare hint.
    pattern = _bare_espalier_pattern()
    heading_doc = "## Build & Test\n\nespalier audit .\n"
    fenced_doc = "```bash\nespalier init .\n```"
    assert pattern.search(heading_doc)            # the hint IS present...
    assert _DOC_TEMPLATE_RE.search(heading_doc)   # ...but the doc-template guard fires
    assert _DOC_TEMPLATE_RE.search(fenced_doc)


def test_fstring_marker_is_recognised_as_a_template_when_reconstructed():
    # The memory-prune marker splits `## ` and `espalier memory prune` across two
    # f-string segments; reconstruction must rejoin them so the `##` heading marks
    # the whole string as a template (else the second segment would be flagged).
    import ast
    src = 'x = f"## Pruned {today} (via espalier memory prune)\\n\\n"'
    tree = ast.parse(src)
    texts = [t for t, _ in _scannable_strings(tree)]
    assert texts, "f-string was not reconstructed into a scannable string"
    assert all(_DOC_TEMPLATE_RE.search(t) for t in texts), (
        "reconstructed marker not recognised as a doc template"
    )


# ── Second axis: the INTERPRETER the hint spells (DEF-383a) ──────────────────
#
# The gate above catches `espalier <verb>` (command-not-found in a fusion). The
# same files also print `python -m espalier <verb>` hints with the interpreter
# spelled LITERALLY -- and stock macOS ships no `python`, only `python3`, so a
# macOS adopter following the hint gets command-not-found from the harness's
# own remediation text. `cli._detect_python_command()` exists to resolve the
# name on the host, and every hint should thread it in (`f"{py} -m espalier"`);
# this axis pins that a literal never lands in an interactive string again.
# Same scope, same string enumeration, same template exclusion as the verb axis.
#
# The OPPOSITE contract one surface over: tests/test_portability_contract.py
# forbids the token `python3 ` in operator MARKDOWN (README, CHEAT-SHEET,
# SHARP_EDGES, the .claude bodies), where the required spelling is bare
# `python` and the macOS caveat is prose. The two point opposite ways because
# a Python string can resolve the interpreter at runtime and a markdown body
# cannot; the failure message below is for Python strings only.

# An interpreter spelled literally as the COMMAND of something the reader would
# type: `python` / `python3` / `python3.12`, then a module run (`-m x`), an inline
# program (`-c`), or a script path (`x.py`). A bare mention (`python3` IS on
# PATH, symlink -> python3.) has no such tail and is prose, not a command.
_LITERAL_INTERPRETER_RE = re.compile(
    r"(?<![\w{}/.\-])python3?(?:\.\d+)?\s+(?:-m\s+\S+|-c\b|\S+\.py\b)"
)

# Named allow-list: (file, a substring of the STRING the match sits in) -> why
# the literal is right there. Keep it tiny and keep each entry a reason, not a
# waiver; `test_interpreter_allow_list_has_no_dead_entries` deletes one that no
# longer matches anything.
_INTERPRETER_AXIS_ALLOW: dict[tuple[str, str], str] = {
    ("espalier/cli.py", "adds `python -m espalier *`"): (
        "quotes the self-host profile's Bash allow rule verbatim -- a permission "
        "pattern the reader compares against settings.json, not a command they type"
    ),
}


def _literal_interpreter_pattern() -> re.Pattern[str]:
    return _LITERAL_INTERPRETER_RE


def _literal_interpreter_offenders() -> tuple[list[str], set[tuple[str, str]]]:
    """(offender lines, allow-list keys that fired) over the scanned files."""
    pattern = _literal_interpreter_pattern()
    offenders: list[str] = []
    used: set[tuple[str, str]] = set()
    for rel in SCANNED_FILES:
        path = REPO_ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for text, lineno in _scannable_strings(tree):
            if _DOC_TEMPLATE_RE.search(text):
                continue  # generated-document template, not an interactive hint
            for match in pattern.finditer(text):
                # An entry excuses ONE literal -- the match must sit inside the
                # named snippet -- never the whole string it lives in.
                key = next(
                    (k for k in _INTERPRETER_AXIS_ALLOW
                     if k[0] == rel and k[1] in text and match.group(0) in k[1]),
                    None,
                )
                if key is not None:
                    used.add(key)
                    continue
                snippet = " ".join(text.split())[:70]
                offenders.append(
                    f"{rel}:{lineno}: {match.group(0)!r}  (in {snippet!r})"
                )
    return offenders, used


def test_no_literal_interpreter_in_engine_runtime_strings():
    offenders, _ = _literal_interpreter_offenders()
    assert not offenders, (
        "Interpreter spelled literally in an interactive operator hint -- "
        "command-not-found on stock macOS (no `python`), and wrong on any host "
        "whose interpreter is not the one spelled. Thread the host's name in: "
        "`f\"{_remedy_py()} -m espalier <verb>\"` (cli and doctor each define one; "
        "never `_detect_python_command()`, the write answer -- DEF-758), or reword a "
        "descriptive help string so it names no command:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\n(A literal that is genuinely right -- a quoted settings rule, say -- "
        "goes in _INTERPRETER_AXIS_ALLOW with its reason.)"
    )


def test_interpreter_allow_list_has_no_dead_entries():
    """Self-expiry: an allow entry that matches no flagged string is bookkeeping
    rot that would silently excuse the next literal at that site."""
    _, used = _literal_interpreter_offenders()
    dead = sorted(set(_INTERPRETER_AXIS_ALLOW) - used)
    assert not dead, f"allow-list entries that no longer match anything: {dead}"


# Positive controls for the interpreter axis (earn-the-gate, as above).


def test_interpreter_pattern_fires_on_a_literal_command():
    pattern = _literal_interpreter_pattern()
    assert pattern.search("First-time setup: python -m espalier init . (current dir).")
    assert pattern.search("Run `python3 scripts/sync_vendor_cc.py` to carry the changes.")
    assert pattern.search("    python -m pip install -e .\n")
    assert pattern.search("try python3.12 -m espalier doctor .")
    assert pattern.search("python -c 'print(1)'")


def test_interpreter_pattern_ignores_the_resolved_form_and_prose_mentions():
    pattern = _literal_interpreter_pattern()
    # f"{_detect_python_command()} -m espalier ..." reconstructs to `{} -m ...`
    assert not pattern.search("Run `{} -m espalier init .` to create settings.json.")
    assert not pattern.search("a WORKING `python3` IS on PATH -- re-run init")
    assert not pattern.search("or symlink 'python' -> python3.")
    assert not pattern.search("no interpreter answered to 'python' or 'python3'")
    assert not pattern.search("/usr/bin/python3 is 3.9.6 on macOS")
    assert not pattern.search("pip install espalier")
    assert not pattern.search("create a `python3` shim (an App Execution Alias)")
