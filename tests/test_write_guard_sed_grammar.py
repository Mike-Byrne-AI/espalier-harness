"""In-place edit extractors must model an option GRAMMAR, not a spelling.

`_SED_INPLACE_RE` modelled sed's option grammar in a single regex, and the model
was wrong in both directions. Its optional backup-extension group does double
duty: with GNU `-i` it happens to consume the script so the capture lands on the
file; with BSD/macOS `-i ''` it consumes the `''`, and the expression-skip that
follows handles only QUOTED scripts -- so an unquoted script is captured as the
target and the real file is never checked against the protected zone. A glued
`-i.bak` leaves no whitespace for the backup arm and does not match the pattern
AT ALL. And `perl`, which spells the same idiom with a different verb, had no arm
in `_candidate_paths_from_bash` at any point.

THE POPULATION IS DERIVED, AND THAT IS THE POINT. The pack that opened this work
listed 14 spellings by hand. Built instead as a cross-product over primitives --
pre-flag run x in-place spelling x script delivery x target count -- and driven at
the live hook with maintenance OFF (enforcement, not friction), 237 of 333 sed
spellings and 37 of 37 perl spellings wrote to a protected path unchecked. The
hand roster was 5% of the truth, and every form it missed (bundled `-Ei.bak`,
a flag BEFORE `-i`, `--in-place=.bak`, multi-target) is an ordinary spelling. A
hand-written roster is the same failure the regex made, one level up -- so the
gate below enumerates from an ALPHABET rather than from a list of sentences.

⚠ BE PRECISE ABOUT WHAT THAT BUYS, because the first version of this docstring
over-claimed and an adversarial pass collected on it. A cross-product is only as
wide as its NARROWEST AXIS, and size is not exhaustiveness: the first alphabet
here produced 333 rows while carrying one delimiter (`/`), no `-I`, and no verb
spelling axis at all -- so it reported full coverage while `sed -i.bak 's|a|b|'
<protected>` wrote unchecked. Delimiters, `-I` and verb spelling are axes now
because that pass made them axes. The honest claim is "derived from a declared
alphabet, and the alphabet is the thing to attack" -- not "exhaustive."

⚠ THE MUST-ALLOW POPULATION MATTERS MORE THAN THE MUST-DENY ONE. Every recent
defect in this layer was a false positive introduced by the repair, not a survivor
of the original defect. `sed -i '' 's|<protected>|x|' notes.txt` names a protected
path INSIDE the expression and writes nothing protected; an extractor that yields
every post-option token denies it, which is friction on exactly the population
this layer serves. That row is why Fix shape B was refuted before it was built.

⚠ AND THE TWO VERBS' GRAMMARS DIVERGE, so a shared tokenizer must key on the verb:
perl has NO bare-script slot (absent `-e`/`-E` its first non-option token is a
script FILE), and perl's `-i` suffix is GLUED-ONLY where BSD sed's is separable.
Inherit sed's "no -e seen -> consume the next token as the script" rule for perl
and `perl -i '' <protected>` swallows the protected file itself as "the script",
yielding zero candidates -- a silent fail-open with the same shape as the original
bug. `test_perl_without_a_script_flag_still_finds_its_target` pins that directly.

Not a security boundary (docs/STANDING_PRINCIPLES.md §2) -- `harness-guard.yml`
still gates a committed write. The value is catching the everyday slip, and
`sed -i ''` is THE macOS idiom.
"""
# slow-exempt: pure in-process extractor calls, no child processes.
from __future__ import annotations

import itertools

import pytest

from tools.cc.hooks import _bash_patterns as bp

PROTECTED = "tools/cc/hooks/write_guard.py"
PROTECTED_ALT = ".claude/settings.json"
UNPROTECTED = "notes/scratch.md"


def _extracts(command: str, target: str = PROTECTED) -> bool:
    return target in list(bp._candidate_paths_from_bash(command))


# ── PRIMITIVES — the population is generated from these, never listed ─────────
# Every element is an ordinary spelling. `--posix` and `-s` are in the alphabet
# precisely because nobody listed them: the pack's red-team named "an option form
# nobody listed" as the most likely surviving defect.
SED_PREFLAGS = ("", "-n", "-E", "-n -E", "-s", "--posix")
SED_INPLACE = (
    "-i", "-i ''", '-i ""', "-i.bak", "-i.orig",
    # `-I` is BSD sed's in-place flag -- real on macOS, one shift key from `-i`,
    # and absent from the first cut of this alphabet. An adversarial pass found
    # it; `-Ei` was already here and PASSED (the scan sees the lowercase `i`),
    # which is exactly what made `-I` look covered when it was not.
    "-I ''", "-I.bak",
    "--in-place", "--in-place ''", "--in-place=.bak",
)
SED_GLUED = ("-Ei", "-Ei.bak", "-ni", "-ni.bak", "-nEi", "-nI")
SED_SCRIPT = (
    "s/a/b/", "'s/a/b/'", '"s/a/b/"',
    "-e s/a/b/", "-e 's/a/b/'", "--expression=s/a/b/",
    # ⚠ ALTERNATE DELIMITERS AND `&`. The first cut of this alphabet was
    # `/`-delimited only, and the segment span truncated at the first `|`, `;` or
    # `&` -- so `sed -i.bak 's|a|b|' <protected>` wrote unchecked while a 333-row
    # cross-product reported full coverage. `s|...|...|` is the STANDARD idiom for
    # substituting paths (it avoids escaping every `/`), and `&` is the matched
    # text. Size is not exhaustiveness: a cross-product is only as wide as its
    # narrowest axis.
    "'s|a|b|'", "'s;a;b;'", "'s#a#b#'", "'s/a/X&Y/'", "-e 's|a|b|'",
)
# ⚠ VERB SPELLING IS AN AXIS, and it was not one until an adversarial pass made
# it one. A quoted verb survives shell quote-removal (`'sed'` runs sed) and an
# uppercase verb resolves on a case-insensitive filesystem (APFS, NTFS) -- both
# verified to really write on this host.
VERB_SPELLINGS = ("sed", "'sed'", "SED")
# perl bundles the in-place flag with -p/-n/-l in either order.
PERL_INPLACE = (
    "-i", "-i.bak", "-pi", "-pi.bak", "-ni", "-lpi", "-i -p", "-p -i", "-i.bak -p",
)
PERL_SCRIPT = ("-e s/a/b/", "-e 's/a/b/'", "-pe s/a/b/", "-ne 's/a/b/'")


def _sed_population():
    for pre, inplace, script in itertools.product(SED_PREFLAGS, SED_INPLACE, SED_SCRIPT):
        pre_s = f"{pre} " if pre else ""
        yield f"sed {pre_s}{inplace} {script} {PROTECTED}"
    for verb, inplace in itertools.product(VERB_SPELLINGS, SED_INPLACE):
        yield f"{verb} {inplace} 's/a/b/' {PROTECTED}"
    for glued, script in itertools.product(SED_GLUED, SED_SCRIPT):
        yield f"sed {glued} {script} {PROTECTED}"
    for inplace in SED_INPLACE:
        # the real file is NOT the first operand
        yield f"sed {inplace} s/a/b/ f1.py {PROTECTED}"


def _perl_population():
    for inplace, script in itertools.product(PERL_INPLACE, PERL_SCRIPT):
        yield f"perl {inplace} {script} {PROTECTED}"


class TestTheDerivedPopulationIsExtracted:
    """The release gate. One test over the whole cross-product, reporting every
    miss -- not a sample, and not a hand-written roster."""

    def test_the_population_is_large_enough_to_be_a_population(self):
        # A generator that silently collapses would make every assertion below
        # pass vacuously. Floor, not an exact pin, so adding a primitive does not
        # red an unrelated commit.
        sed, perl = list(_sed_population()), list(_perl_population())
        assert len(sed) >= 300, f"sed population collapsed to {len(sed)}"
        assert len(perl) >= 36, f"perl population collapsed to {len(perl)}"

    def test_every_derived_sed_spelling_extracts_its_target(self):
        missed = [c for c in _sed_population() if not _extracts(c)]
        assert not missed, (
            f"{len(missed)} of {len(list(_sed_population()))} in-place sed "
            f"spellings write to a protected path the extractor never sees. "
            f"First 5: {missed[:5]}"
        )

    def test_every_derived_perl_spelling_extracts_its_target(self):
        missed = [c for c in _perl_population() if not _extracts(c)]
        assert not missed, (
            f"{len(missed)} of {len(list(_perl_population()))} in-place perl "
            f"spellings write to a protected path the extractor never sees. "
            f"First 5: {missed[:5]}"
        )

    def test_a_second_protected_zone_is_reached_too(self):
        # Proves the finding is not shaped by one zone's matching rules.
        assert _extracts(f"sed -i '' s/a/b/ {PROTECTED_ALT}", PROTECTED_ALT)
        assert _extracts(f"perl -pi -e s/a/b/ {PROTECTED_ALT}", PROTECTED_ALT)


# (label, command) -- the named shapes, kept parametrized so a failure names the
# spelling rather than reporting "one of 370".
_NAMED_MISSES = [
    ("bsd-unquoted-script", f"sed -i '' s/a/b/ {PROTECTED}"),
    ("bsd-dash-e", f"sed -i '' -e s/a/b/ {PROTECTED}"),
    ("glued-backup-suffix", f"sed -i.bak s/a/b/ {PROTECTED}"),
    ("long-flag-bsd", f"sed --in-place '' s/a/b/ {PROTECTED}"),
    ("multi-target", f"sed -i '' s/a/b/ f1.py {PROTECTED}"),
    ("bundled-short-flags", f"sed -Ei.bak s/a/b/ {PROTECTED}"),
    ("flag-before-i", f"sed -n -i.bak s/a/b/ {PROTECTED}"),
    ("glued-suffix-dash-e", f"sed -i.orig -e s/a/b/ {PROTECTED}"),
    ("separate-flag-bsd", f"sed -E -i '' s/a/b/ {PROTECTED}"),
    ("long-option-equals", f"sed --in-place=.bak s/a/b/ {PROTECTED}"),
    ("perl-pi-e", f"perl -pi -e s/a/b/ {PROTECTED}"),
    ("perl-glued-suffix", f"perl -i.bak -pe s/a/b/ {PROTECTED}"),
    ("perl-i-pe", f"perl -i -pe s/a/b/ {PROTECTED}"),
    ("perl-pi-bak", f"perl -pi.bak -e s/a/b/ {PROTECTED}"),
]


@pytest.mark.parametrize("label,command", _NAMED_MISSES, ids=[m[0] for m in _NAMED_MISSES])
def test_named_in_place_spelling_extracts_its_target(label, command):
    assert _extracts(command), (
        f"{label}: {command!r} writes to a protected path and the extractor "
        f"missed it"
    )


class TestTheDivergenceBetweenSedAndPerl:
    """A shared tokenizer must key `-i`'s argument grammar and the script slot on
    the VERB. Both rows below are fail-opens with the same shape as the original
    defect, reachable by an ordinary slip rather than by an attacker."""

    def test_perl_without_a_script_flag_still_finds_its_target(self):
        # perl has NO bare-script slot. If the tokenizer inherits sed's
        # "no -e seen -> the next token is the script" rule, `''` is eaten as the
        # backup suffix and the PROTECTED FILE ITSELF is eaten as the script,
        # leaving zero candidates.
        assert _extracts(f"perl -i '' {PROTECTED}"), (
            "perl -i '' <protected>: the protected file was consumed as though it "
            "were a script argument -- perl has no bare-script slot, so sed's "
            "positional rule must not be shared with it"
        )
        assert _extracts(f"perl -pi {PROTECTED}"), (
            "perl -pi <protected>: same shape, bundled spelling"
        )

    def test_sed_still_accepts_both_suffix_grammars(self):
        # sed must accept BSD-separable and GNU-glued; the extractor cannot know
        # which dialect will run. Collapsing to one reintroduces the original bug.
        assert _extracts(f"sed -i '' s/a/b/ {PROTECTED}"), "BSD separable form"
        assert _extracts(f"sed -i.bak s/a/b/ {PROTECTED}"), "GNU glued form"


class TestControlsAndMustAllow:
    """These matter more than the must-deny rows: every recent defect in this
    layer was a false positive introduced by the repair."""

    def test_the_known_good_spellings_still_extract(self):
        # If these regress, every assertion above proves nothing.
        assert _extracts(f"sed -i '' 's/a/b/' {PROTECTED}"), "quoted script (control)"
        assert _extracts(f"sed -i s/a/b/ {PROTECTED}"), "GNU form (control)"

    def test_an_unprotected_target_is_not_manufactured(self):
        assert not _extracts(f"sed -i '' 's/x/y/' {UNPROTECTED}")
        assert not _extracts(f"sed -i '' s/x/y/ {UNPROTECTED}")
        assert not _extracts(f"perl -pi -e s/x/y/ {UNPROTECTED}")

    def test_a_protected_path_inside_the_script_is_not_a_target(self):
        """The row that refuted Fix shape B before it was built.

        The command edits `notes/scratch.md`. The protected path is a literal in
        the substitution expression and nothing writes to it. An extractor that
        yields every post-option token denies this -- friction on exactly the
        population this layer serves.
        """
        assert not _extracts(f"sed -i '' 's|{PROTECTED}|x|' {UNPROTECTED}"), (
            "a protected path quoted INSIDE the sed expression was treated as a "
            "write target -- this is the Fix-shape-B false positive"
        )
        assert not _extracts(f"perl -pi -e 's|{PROTECTED}|x|' {UNPROTECTED}"), (
            "same shape on the perl leg"
        )

    def test_a_read_is_not_a_write(self):
        assert not _extracts(f"sed -n '1,5p' {PROTECTED}"), "sed read, no -i"
        assert not _extracts(f"sed 's/a/b/' {PROTECTED}"), "sed to stdout, no -i"
        assert not _extracts(f"perl -ne 'print' {PROTECTED}"), "perl read, no -i"

    def test_an_unrelated_dash_i_is_not_an_in_place_edit(self):
        """`-i` means something else on other verbs, and neither is a write."""
        assert not _extracts(f"grep -i pattern {PROTECTED}"), "grep -i is case-insensitive"
        assert not _extracts(f"sort -i {PROTECTED}"), "sort -i is ignore-nonprinting"


class TestTheVerbSetsCannotDiverge:
    """Two hand-maintained verb sets that must agree, pinned against each other.

    `_INPLACE_SEGMENT_RE` carries a `(?:sed|perl)` alternation and
    `_INPLACE_PROFILES` carries the per-verb grammar. BOTH must name a verb for it
    to be extracted, and divergence in EITHER direction is silent and fail-open:
    a profile added without an alternation entry never matches a segment, and an
    alternation entry without a profile hits `.get() -> None` and is skipped. The
    corpus row for this class told a future reader that a new verb is "one table
    row away", which was false in exactly this way until this test existed.

    The alternation is a declared module-level constant rather than a computed
    `"|".join(_INPLACE_PROFILES)` on purpose: `tests/test_redos.py` statically
    reconstructs every hook regex to prove it carries no unbounded dot-quantifier,
    and its reconstructor resolves literals, `+` concatenation and module-level
    Name references but NOT a general function call. Deriving the alternation
    would make the pattern unresolvable and silently drop it from that gate --
    trading one enumeration-integrity hole for another. A declared constant plus
    this contract keeps both gates live.
    """

    def test_the_alternation_and_the_profile_table_name_the_same_verbs(self):
        import re as _re

        alternation = set(
            _re.fullmatch(r"\(\?:(.+)\)", bp._INPLACE_VERB_ALT).group(1).split("|")
        )
        assert alternation == set(bp._INPLACE_PROFILES), (
            f"_INPLACE_VERB_ALT names {sorted(alternation)} but _INPLACE_PROFILES "
            f"names {sorted(bp._INPLACE_PROFILES)}. A verb in only one of them is "
            f"SILENTLY inert -- the segment never matches, or the profile lookup "
            f"misses and the segment is skipped. Update both."
        )

    def test_every_profile_declares_every_key_the_tokenizer_reads(self):
        # A typo'd key raises KeyError at call time, which the hook's umbrella
        # guard converts into a fail-CLOSED deny -- right direction, but it
        # surfaces on first sed/perl use rather than here. Catch it here.
        required = {
            "long_inplace", "long_script", "script_letters",
            "inplace_letters", "positional_script", "separable_suffix",
        }
        for verb, profile in bp._INPLACE_PROFILES.items():
            assert set(profile) == required, (
                f"profile {verb!r} declares {sorted(profile)}, expected "
                f"{sorted(required)}"
            )


class TestTheRetainedRegexIsWitnessed:
    """`_SED_INPLACE_RE` is retained; this pins WHY, so the reason cannot rot.

    An adversarial pass showed the stated reason was a pure LINKAGE reason
    (`write_guard` re-exports it, `test_redos` imports it by name) and that
    linkage is trivially dischargeable: replacing the regex with a never-matching
    pattern left 708 tests green. So the question "does deleting it lose
    coverage?" had no witness at all.

    Measured answer, driven through a real `/bin/bash`: it loses NOTHING real.
    Over a delimiter x in-place x pre-flag population the regex catches rows the
    tokenizer does not, and every one is a shape that never writes --
    `sed -i s|a|b| victim.txt` is a PIPELINE and `sed -i s;a;b; victim.txt` is
    three commands; victim.txt is unmodified in both. The tokenizer is RIGHT to
    truncate at an unquoted separator. The regex's extra hits are harmless
    over-extraction, and its retention is linkage plus a fail-safe net.
    """

    def test_the_tokenizer_covers_every_real_invocation_the_regex_does(self):
        # QUOTED delimiters are real invocations and the tokenizer must catch
        # them; UNQUOTED ones are shell pipelines and it is correct not to.
        for script in ("'s|a|b|'", "'s;a;b;'", "'s/a/X&Y/'"):
            command = f"sed -i.bak {script} {PROTECTED}"
            assert PROTECTED in list(bp.iter_inplace_edit_targets(command)), (
                f"{command!r} is a REAL write (quoted script, separator is script "
                f"text) and the tokenizer missed it -- the span stopped being "
                f"quote-aware"
            )

    def test_an_unquoted_separator_is_a_shell_separator_not_script_text(self):
        # Verified against /bin/bash: victim.txt is UNMODIFIED by either of these.
        # If the tokenizer ever starts yielding here it has stopped modelling the
        # shell and started guessing.
        for command in (f"sed -i s|a|b| {PROTECTED}", f"sed -i s;a;b; {PROTECTED}"):
            assert PROTECTED not in list(bp.iter_inplace_edit_targets(command)), (
                f"{command!r} is a shell pipeline/command-list, not a write -- the "
                f"tokenizer must stop at an unquoted separator"
            )


class TestTheSegmentBoundIsAnExtractionCliff:
    """The `{0,512}` span bound fails OPEN, unlike its siblings -- pin the edge.

    `_DD_OF_RE` and `_TAR_C_RE` use the same bound but anchor on a REQUIRED
    trailing token, so overflow means "no match, no claim". Here the segment IS
    the operand list, so a target pushed past the bound drops every operand and
    the command is allowed. That is a documented residual, not a defect to fix by
    raising the bound (which just moves the cliff) -- but it must be pinned so a
    future reader meets it as a decision rather than a surprise.
    """

    def test_a_target_inside_the_bound_is_extracted(self):
        script = "s/" + "x" * 400 + "/y/"
        assert _extracts(f"sed -i.bak '{script}' {PROTECTED}")

    def test_a_target_past_the_bound_is_the_documented_residual(self):
        script = "s/" + "x" * 900 + "/y/"
        assert not _extracts(f"sed -i.bak '{script}' {PROTECTED}"), (
            "a target past the 512-char span bound is expected to be MISSED "
            "(documented fail-open residual). If this now passes, the bound "
            "changed -- update the comment at _INPLACE_SEGMENT_RE and this test "
            "together, and re-run the ReDoS budget."
        )
