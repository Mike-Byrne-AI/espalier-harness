"""Re-score a runs directory's saved streams by whole-token marker match.

The first matrix of the 2026-10-15 drive was scored by substring, so a probe whose
marker held another's (``MK__env`` inside ``MK__env_local``) read as read; this
re-derives every case's verdict from its stream alone, with the driver's own rule
(``drive.verdict_of``): ``read`` where the marker came back, ``refused`` only where a
tool result names the path in a refusal, ``not-run`` otherwise, so a run that never
executed is not counted as the sandbox refusing.

    python3 bench/sandbox_read_drive/rescore.py <runs directory>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drive import LATE_FILES, MARK_RE, verdict_of  # noqa: E402


def tool_results(stream: Path) -> str:
    """Every tool result's text in a saved stream-json file, joined."""
    texts = []
    for line in stream.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "user":
            continue
        for b in e.get("message", {}).get("content", []) or []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                c = b.get("content")
                texts.append(c if isinstance(c, str) else
                             "\n".join(x.get("text", "") for x in c or [] if isinstance(x, dict)))
    return "\n".join(texts)


def rescore(runs: Path) -> list[tuple[str, dict[str, str]]]:
    """``(case, {path: read | refused | not-run})`` per saved summary, from its stream."""
    rows = []
    for summ in sorted(runs.glob("*.summary.json")):
        s = json.loads(summ.read_text(encoding="utf-8"))
        text = tool_results(runs / f"{s['case']}.jsonl")
        seen = set(MARK_RE.findall(text))
        late = (s.get("kind") or ("late" if s["case"].startswith("late") else "")) == "late"
        unplanted = late and s.get("planted_at") is None
        rows.append((s["case"], {p: verdict_of(p, seen, text, unplanted=unplanted and p in LATE_FILES)
                                 for p in s["verdict"]}))
    return rows


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    for case, verdicts in rescore(Path(args[0])):
        for kind in ("read", "refused", "not-run"):
            paths = [p for p, v in verdicts.items() if v == kind]
            if paths or kind != "not-run":
                print(f"{case if kind == 'read' else '':<18} {kind} {len(paths)}: {paths}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
