"""TP-118: bash codeblocks inside shipped command bodies must produce
ASCII output. Pins the invariant that ``echo``/``print`` statements
inside `````bash ... ````` fences in
``espalier/assets/claude/commands/*.md`` contain only ASCII
characters, so that adopters running the commands on Windows cp1252
consoles do not hit ``UnicodeEncodeError``.

Sister-class to ``test_common_tier_asset_availability`` (TP-118): both
contracts gate the adopter-facing tier. This one is scoped to
**runtime stdout** — the bash codeblock surface only. Markdown prose
in the surrounding body remains free to use Unicode (the prose
renders in the agent UI, not in a terminal); only what an adopter's
shell will actually execute is gated.

Without this contract, asset prose can re-introduce ``✓`` /
``✗`` / ``→`` glyphs into shell output (the harness's own
TP-30/TP-32 ASCII-tokens convention forbids them for the same
reason); the regression renders fine locally on macOS/Linux UTF-8
terminals and silently breaks adopter Windows installs.

Failure mode prevented: an asset body author adds a check-mark to a
shell echo for visual clarity; CI on Linux passes; adopter on
Windows hits a ``UnicodeEncodeError`` traceback from the shipped
command. The parametrized matrix here catches the regression at
authoring time.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMAND_ROOT = REPO_ROOT / "espalier" / "assets" / "claude" / "commands"

# Capture the leading indent and require the close fence to match it.
# Without this, an indented ```bash inside a numbered list-item runs
# past the matching indented close fence (which is preceded by
# whitespace the simpler pattern can't see) and gobbles up arbitrary
# prose until the next column-0 fence. Anchored to line start/end via
# re.MULTILINE so prose like "use ```bash``` to mark a block" can't
# accidentally open one.
_BASH_BLOCK = re.compile(
    r"^([ \t]*)```bash\n(.*?)\n\1```$",
    re.MULTILINE | re.DOTALL,
)


def _bash_blocks(md_path: Path) -> list[str]:
    text = md_path.read_text(encoding="utf-8")
    return [m.group(2) for m in _BASH_BLOCK.finditer(text)]


def _non_ascii_chars(text: str) -> list[tuple[int, str]]:
    return [(i, ch) for i, ch in enumerate(text) if ord(ch) > 127]


@pytest.mark.parametrize(
    "cmd_path",
    sorted(COMMAND_ROOT.glob("*.md")),
    ids=lambda p: p.name,
)
def test_command_bash_blocks_are_ascii(cmd_path):
    blocks = _bash_blocks(cmd_path)
    offenders: list[str] = []
    for idx, block in enumerate(blocks):
        bad = _non_ascii_chars(block)
        if bad:
            sample = ", ".join(f"{ch!r} at offset {i}" for i, ch in bad[:5])
            offenders.append(f"block #{idx}: {sample}")
    assert not offenders, (
        f"{cmd_path.relative_to(REPO_ROOT)} has non-ASCII characters in "
        f"bash codeblocks (breaks Windows cp1252 consoles):\n  "
        + "\n  ".join(offenders)
    )
