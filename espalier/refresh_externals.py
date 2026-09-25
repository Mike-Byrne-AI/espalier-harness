"""External-pin refresh subsystem.

`espalier refresh-externals` enumerates every pin under
`docs/external/`, fetches its source URL, classifies drift (none /
cosmetic / semantic / fetch_error), and either:

- prints a dry-run summary (default),
- writes `.candidate.md` files for review and re-runs bound tests
  (`--apply`),
- prompts accept/reject/skip per pin (`--interactive`).

Auto-apply is intentionally absent: every refresh path that touches a
pin requires either an explicit operator confirmation or a
post-candidate test re-run that the operator must inspect before
renaming the candidate over the pin. See docs/external/README.md for
the operator workflow.

Network calls happen only inside `espalier.external_fetch.fetch_url`.
The CLI command is invoked from `espalier/cli.py::cmd_refresh_externals`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from espalier._atomic_io import atomic_write_text
from espalier.external_diff import (
    DRIFT_FETCH_ERROR,
    DRIFT_NONE,
    DriftReport,
    compare_pin_to_fetched,
    write_candidate,
)
from espalier.external_fetch import FetchResult, fetch_url
from espalier.external_pins import ExternalPin, _frontmatter_block, list_pins
from espalier._text import os_error_text


@dataclass(frozen=True, slots=True)
class PinReport:
    pin_name: str
    source_url: str
    drift_kind: str
    summary: str
    age_days: int
    candidate_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin": self.pin_name,
            "source_url": self.source_url,
            "drift_kind": self.drift_kind,
            "summary": self.summary,
            "age_days": self.age_days,
            "candidate_path": self.candidate_path,
        }


@dataclass(frozen=True, slots=True)
class RefreshReport:
    pins: list[PinReport] = field(default_factory=list)
    bound_tests_status: str | None = None  # "pass" | "fail" | None (not run)
    bound_tests_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pins": [p.to_dict() for p in self.pins],
            "bound_tests": {
                "status": self.bound_tests_status,
                "output_tail": self.bound_tests_output[-1500:] if self.bound_tests_output else "",
            },
        }


def _age_days(pin: ExternalPin) -> int:
    from datetime import date

    return (date.today() - pin.fetched).days


def refresh_pin(pin: ExternalPin, *, fetcher=fetch_url) -> tuple[DriftReport, FetchResult]:
    """Fetch the pin's source URL and compute drift. Pure of side effects."""
    fetched = fetcher(pin.source_url)
    return compare_pin_to_fetched(pin, fetched), fetched


def run_bound_tests(repo_root: Path) -> tuple[str, str]:
    """Run the pin-bound tests after a refresh. Returns (status, output)."""
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_documented_claims.py",
        "tests/test_hook_protocol.py",
        "-q", "--tb=short",
    ]
    try:
        result = subprocess.run(
            cmd, cwd=str(repo_root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError) as e:
        return "fail", f"could not run bound tests: {os_error_text(e)}"
    output = result.stdout + result.stderr
    return ("pass" if result.returncode == 0 else "fail"), output


def run_refresh(
    repo_root: Path,
    *,
    apply: bool = False,
    pin_name: str | None = None,
    fetcher=fetch_url,
) -> RefreshReport:
    """Core refresh logic, side-effect-bounded.

    `apply=False` (default): no files written, no tests run. Pure dry-run.
    `apply=True`: writes `.candidate.md` for any non-`none` drift and runs
      the pin-bound test suite. Original pins are never overwritten.
    """
    report = RefreshReport()
    pins = list_pins(repo_root)
    if pin_name is not None:
        pins = [p for p in pins if p.name == pin_name]
        if not pins:
            return report  # caller decides how to surface "no such pin"

    candidate_written = False
    for pin in pins:
        drift, fetched = refresh_pin(pin, fetcher=fetcher)
        candidate_path: Path | None = None
        if apply and drift.drift_kind not in {DRIFT_NONE, DRIFT_FETCH_ERROR}:
            candidate_path = write_candidate(pin, fetched.content)
            candidate_written = True
        report.pins.append(
            PinReport(
                pin_name=pin.name,
                source_url=pin.source_url,
                drift_kind=drift.drift_kind,
                summary=drift.summary,
                age_days=_age_days(pin),
                candidate_path=str(candidate_path.relative_to(repo_root)).replace("\\", "/") if candidate_path else None,
            )
        )

    if apply and candidate_written:
        status, output = run_bound_tests(repo_root)
        report = replace(report, bound_tests_status=status, bound_tests_output=output)
    return report


# ── CLI rendering ────────────────────────────────────────────────────


def render_summary_table(report: RefreshReport) -> str:
    """Plain-text table for `espalier refresh-externals` stdout."""
    if not report.pins:
        return "No pins matched."
    width = max(len(p.pin_name) for p in report.pins) + 2
    lines = [
        f"{'pin':<{width}}{'drift':<11}{'age':<8}summary",
        "-" * (width + 11 + 8 + 40),
    ]
    for p in report.pins:
        age = f"{p.age_days}d"
        lines.append(f"{p.pin_name:<{width}}{p.drift_kind:<11}{age:<8}{p.summary}")
    if report.bound_tests_status is not None:
        lines.append("")
        if report.bound_tests_status == "pass":
            lines.append("Bound tests: PASS -- refresh is safe to commit.")
        else:
            lines.append("Bound tests: FAIL -- refresh surfaced drift in espalier claims.")
            tail = "\n".join(report.bound_tests_output.splitlines()[-20:])
            lines.append(tail)
    return "\n".join(lines)


def render_json(report: RefreshReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def cli_main(args) -> int:
    """Entry point invoked by espalier/cli.py::cmd_refresh_externals."""
    repo_root = Path(getattr(args, "repo", ".")).resolve()
    pin_name = getattr(args, "pin", None)
    apply = getattr(args, "apply", False)
    interactive = getattr(args, "interactive", False)
    json_mode = getattr(args, "json", False)

    if interactive:
        return _interactive_loop(repo_root, pin_name)

    report = run_refresh(repo_root, apply=apply, pin_name=pin_name)
    if json_mode:
        print(render_json(report))
    else:
        print(render_summary_table(report))

    # Exit non-zero only on fetch errors or bound-test failures during apply.
    if any(p.drift_kind == DRIFT_FETCH_ERROR for p in report.pins):
        return 1
    if apply and report.bound_tests_status == "fail":
        return 1
    return 0


def _interactive_loop(repo_root: Path, pin_name: str | None) -> int:
    """Per-pin accept/reject/skip prompt. Stdin-bound; not used by CI."""
    pins = list_pins(repo_root)
    if pin_name is not None:
        pins = [p for p in pins if p.name == pin_name]
    if not pins:
        print("No pins matched.")
        return 1
    log_path = repo_root / "cc" / "external_refresh_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    decisions: list[dict[str, Any]] = []
    for pin in pins:
        drift, fetched = refresh_pin(pin)
        if drift.drift_kind in {DRIFT_NONE, DRIFT_FETCH_ERROR}:
            print(f"[{pin.name}] {drift.summary} -- skipping prompt")
            continue
        print(f"\n=== {pin.name} ({drift.drift_kind}) ===")
        print(drift.summary)
        print()
        print(drift.unified_diff)
        try:
            choice = input("[a]ccept / [r]eject / [s]kip > ").strip().lower()
        except EOFError:
            print("no input (stdin is not interactive) -- aborting interactive refresh.")
            return 1
        if choice == "a":
            # Load-modify-save: the helper prevents a torn pin, not a lost
            # update. Unguarded because the loop is interactive -- one operator,
            # one pin at a time.
            atomic_write_text(
                pin.path,
                _rebuild_with_new_body(pin, fetched.content, fetched.fetched_at.date()),
            )
            decisions.append({"pin": pin.name, "decision": "accept",
                              "fetched_at": fetched.fetched_at.isoformat()})
            print("ACCEPTED -- pin updated.")
        elif choice == "r":
            decisions.append({"pin": pin.name, "decision": "reject",
                              "fetched_at": fetched.fetched_at.isoformat()})
            print("REJECTED -- pin left unchanged.")
        else:
            print("SKIPPED.")
    if decisions:
        with log_path.open("a", encoding="utf-8") as f:
            for d in decisions:
                f.write(json.dumps(d, sort_keys=True) + "\n")
    return 0


def _rebuild_with_new_body(pin: ExternalPin, new_body: str, new_fetched) -> str:
    """Reconstruct the pin file with new body + bumped `fetched` field."""
    # Read original frontmatter block (both delimiters) via the shared writers'
    # helper, then swap the fetched line. No leading `---\n` guard here: every
    # caller passes an already-validated pin.
    original = pin.path.read_text(encoding="utf-8")
    fm = _frontmatter_block(original, malformed_msg=f"{pin.path}: malformed frontmatter")
    import re as _re
    fm = _re.sub(
        r"^fetched:.*$",
        f"fetched: {new_fetched.isoformat()}",
        fm,
        count=1,
        flags=_re.MULTILINE,
    )
    # Clear old content_hash (operator can re-fill via hash util).
    fm = _re.sub(
        r"^content_hash:.*$",
        'content_hash: ""',
        fm,
        count=1,
        flags=_re.MULTILINE,
    )
    return fm + "\n\n" + new_body
