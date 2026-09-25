"""The one definition of "the `-p` launch form quoted as the DENIED shape",
shared by the two relaunch gates (`test_onboarding_doc_honesty.py` and
`test_maintenance_mode.py`).

`_denial_reasons.HARNESS_ENV_PREFIX_INLINE` quotes `... claude -p ...` as what
NOT to run, and both gates must let that quote through while catching a
REMEDY spelled with `-p` (the one-shot form drops the session it was given
in; DEF-692). Three cuts of the exemption were driven wrong by a code-reviewer
before this one, each wider than the quotes it existed for: a denied-context
WORD anywhere on the line (`do not forget to relaunch with ...` passed on an
unrelated `not`); a distance window (the real quote puts more prose between
its `don't` and the form than that launder does); a grammar of "negation
governs a launch verb somewhere in the window" (`never use --continue,
relaunch with ...`, `do not launch it any other way than ...`, `if not run
with ...`, `...; anything else is refused` all read as denials of the form).

So the exemption is an ALLOW-LIST of the shapes the real quotes take, each
anchored at the form itself with nothing but the verb's object and an opening
quote or paren between -- and anything else fails CLOSED: a line the list does
not recognise is a prescribed launch, and the author rewrites it into one of
the recognised shapes. Incompleteness here costs a doc author one red, never
a remedy that slips past (FAILURE_MODES 13.38). Both gates read it from here
so the shapes cannot drift between them.
"""
from __future__ import annotations

import re

#: Characters before the form's start, or after its end, that the anchored
#: shapes may span. The real quote's object phrase (``launch `claude` with
#: one (```) is 22 characters; the window leaves room without admitting a
#: second clause.
DENIED_CONTEXT_WINDOW = 48

#: The form is the OBJECT of a negated launch verb: `Don't run `FORM`,
#: `never launch with FORM`, `don't launch `claude` with one (`FORM`,
#: `you should not run FORM`. Anchored at the form (`$` is the form's start),
#: so a second clause between the negation and the form (`never use
#: --continue, relaunch with FORM`) breaks the match.
_NEGATED_LAUNCH_OF_THE_FORM_RE = re.compile(
    r"\b(?:don'?t|never|(?:do|should|must|may)\s+not)\s+"
    r"(?:run|launch|invoke|use)\s+"
    r"(?:it\s+|`claude`\s+)?(?:with\s+(?:one\s+)?)?\(?`?\s*$",
    re.I,
)
#: The form named as the refused thing: `the denied form (`FORM`.
_NAMED_AS_DENIED_FORM_RE = re.compile(
    r"\b(?:denied|refused|blocked)\s+(?:form|shape|spelling|one|invocation)\s*\(?`?\s*$",
    re.I,
)
#: A refusal predicated of the form itself, immediately after it:
#: `FORM`) is refused by write_guard`. Anchored at the form's end (`^`), so
#: `FORM; anything else is refused` -- a refusal of the complement -- fails;
#: and bounded at the far end too (an optional `by <agent>`, then
#: punctuation or the end of the window), so a qualifier that turns the
#: refusal into a condition (`is refused unless you pass ...`) fails as well.
_REFUSAL_OF_THE_FORM_RE = re.compile(
    r"^\s*`?\)?\s*(?:is|are|was|were|gets?|will be)\s+(?:refused|denied|blocked)"
    r"(?:\s+by\s+[`\w./-]+)?\s*(?:[.;,)]|--|$)",
    re.I,
)


def denied_form_in_context(text: str, form: re.Match[str]) -> bool:
    """True when the `-p` launch ``form`` (a match inside ``text``) is quoted
    as the denied shape, by one of the anchored shapes above. Anything the
    list does not recognise is NOT exempt -- the fail-closed direction."""
    before = text[max(0, form.start() - DENIED_CONTEXT_WINDOW):form.start()]
    after = text[form.end():form.end() + DENIED_CONTEXT_WINDOW]
    return bool(
        _NEGATED_LAUNCH_OF_THE_FORM_RE.search(before)
        or _NAMED_AS_DENIED_FORM_RE.search(before)
        or _REFUSAL_OF_THE_FORM_RE.search(after)
    )


def every_form_is_denied(text: str, form_re: re.Pattern[str]) -> bool:
    """True when ``text`` holds at least one `-p` form and EVERY one of them
    is quoted as the denied shape. A gate that checked only the first form
    let a second, bare remedy hide behind an exempted quote on the same line
    (`the denied form (`FORM`) misleads people; just run FORM directly` --
    code-reviewer, driven). False when there is no form at all."""
    forms = list(form_re.finditer(text))
    return bool(forms) and all(denied_form_in_context(text, f) for f in forms)
