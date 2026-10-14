"""Transcript query interface.

The runner produces a list of `TranscriptEvent`s from Claude Code's
`--output-format stream-json` output. The assertion framework needs
those events in a normalized, query-friendly form. Separating parsing
from assertion makes both testable.

The load-bearing method is `deny_reason_received()`: it answers the
question that the entire end-to-end bench exists to ask. If a hook's
deny reason never reaches the agent, the friction layer is teaching
nothing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

# Substring markers we recognise as deny reasons surfaced by espalier
# hooks. Keep this in sync with the actual deny() text in
# tools/cc/hooks/*.py (write_guard, plan_guard, config_guard, stop_gate).
_DENY_REASON_MARKERS: tuple[str, ...] = (
    # write_guard's secret-path arm -- the hook-layer replacement for the
    # `Read()` deny rules. Without a marker here BCE-001 reports "the
    # friction layer is not teaching" about a hook that is teaching.
    "Secret-path access blocked",
    "changed no documentation",
    "Write to protected harness zone blocked",
    "protected harness zone",
    # The adopter's own zones (espalier.toml protected_paths / generated_paths):
    # the templates' lead, and the hint sentence they carry.
    "protected zone blocked",
    "This zone is YOURS",
    # A deny hook that could not start on a kept, older helper (DEF-1176; the
    # refusal `_denial_reasons.refuse_on_helper_skew` emits).
    "cannot start: a sibling helper import failed",
    # The stop-time override that could not be split, and the Windows shim remedy.
    "unbalanced quote",
    "resolves it through PATHEXT",
    "active execution plan",
    "kill-switch",
    # config_guard's refusal of a project-settings change that unwires a gate.
    "leaves governance gates unwired",
    # The two stop-gate hygiene blocks, keyed on the HEAD of each message
    # ("<Gate> needed before Claude Code stops"). The code-review one has rotted
    # twice on a rewording -- "Run @code-reviewer", then "invoke the
    # code-reviewer agent" (retired with the Task tool's rename, DEF-496) -- a
    # dead marker reporting success the whole time. The head is the part a
    # remediation rewrite does not touch.
    "Docs refresh needed",
    "Code review needed",
    # Either hygiene gate on a flag file that is not a relief record.
    "is not a relief record",
    "Tests are failing",
    # The test-gate override that cannot be started (the stop gate's one
    # once-a-session block), keyed on the head of the reason: the body names
    # the command and the platform's remedy, which differ per run.
    "Stop blocked once",
    # Inline harness-env assignment (ESPALIER_MAINTENANCE_MODE=1 ... on a tool
    # call). A live, working deny whose text matched ZERO markers, so the bench
    # reported "friction layer is not teaching" about a hook that was teaching.
    # Was "Harness env vars" (plural), which went dead the moment the message was
    # reworded to open on the singular -- the SECOND time this one marker rotted
    # on a rewording. Matching is case-insensitive and this substring survives
    # both the inert-form and the nested-launch halves of the message.
    "harness env var",
    # The speed-bump family (deny-once-then-allow). Only the template's literal
    # head is matchable: the body is interpolated per bump, so a body-specific
    # phrase can never match statically.
    "Speed-bump",
    # Gate 1 on the command it runs as the suite -- the override, the declared
    # [extra_actions] test, or the detected command (since 2026-10-08): every
    # reason opens "Gate 1 (<source phrase>)", and the phrase is interpolated,
    # so the head up to the paren is the part a rewording does not touch.
    "Gate 1 (",
    # write_guard dangerous-pattern denies (rm -rf /, Remove-Item -Recurse).
    "Dangerous command blocked",
    "Dangerous PowerShell command blocked",
    # Malformed tool payload (non-str file_path) + main() umbrella.
    "Malformed Write/Edit payload",
    "write_guard internal error",
    # The time-budget refusal (exit 2, the reason on stderr): a judgment that
    # outran the guard's own budget, refused rather than let through when
    # Claude Code's timeout cancelled the hook.
    "could not finish judging",
    # Malformed MCP payload (non-str path-shaped field).
    "Malformed MCP payload",
    # Class-A2: MCP leaf-walk fail-closed on an unverifiable (too
    # deeply nested / too large) payload.
    "denied fail-closed",
    # Class-A4: hardlink creation-deny + inode write-through backstop
    # (both reasons name the file, not the "zone", so the zone marker misses).
    "hardlink",
    # Sister-site umbrellas on plan_guard + config_guard.
    "plan_guard internal error",
    "config_guard internal error",
    # stop_gate fail-CLOSED umbrella re-blocks on internal crash.
    "stop_gate internal error",
)


@dataclass(frozen=True)
class TranscriptEvent:
    """One event from Claude Code's stream-json transcript."""

    role: str  # 'user' | 'assistant' | 'system' | 'tool_use' | 'tool_result' | 'hook'
    content: str
    metadata: dict[str, Any]


def parse_stream_json(stream: str) -> list[TranscriptEvent]:
    """Parse line-delimited JSON from `claude --output-format stream-json`.

    Claude Code's stream-json shape (excerpted, may vary by version):

      {"type": "user", "message": {...}}
      {"type": "assistant", "message": {"content": [{"type":"text","text":"..."}, ...]}}
      {"type": "system", "subtype": "...", "message": ...}
      {"type": "tool_use", "name": "...", "input": {...}}
      {"type": "tool_result", "tool_use_id": "...", "content": ...}

    Unknown shapes are tolerated — they become events with role='unknown'
    and the raw line in metadata['raw']. Missing or malformed JSON lines
    are skipped silently (the runner saves the raw stream for debugging).
    """
    events: list[TranscriptEvent] = []
    for raw in stream.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        events.append(_event_from_obj(obj))
    return events


def _event_from_obj(obj: dict[str, Any]) -> TranscriptEvent:
    kind = obj.get("type", "unknown")
    if kind == "assistant":
        text = _flatten_assistant_content(obj)
        return TranscriptEvent(role="assistant", content=text, metadata=obj)
    if kind == "user":
        # The live CLI delivers every tool's result -- a hook's deny among them
        # -- as `tool_result` blocks inside a `user` event, never as a top-level
        # `tool_result` event. A user event made only of those is a tool result,
        # so the deny check (which leaves the user's own prompt out) reads it.
        if obj.get("isSynthetic") is True:
            # A user event the CLI wrote itself, not the operator's prompt: a
            # Stop hook's block arrives this way ("Stop hook feedback: ..."), so
            # it is the harness speaking and the deny check reads it.
            return TranscriptEvent(role="hook", content=_flatten_user_content(obj), metadata=obj)
        blocks = _user_blocks(obj)
        if blocks and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
            text = "\n".join(_flatten_tool_result_content(b) for b in blocks)
            return TranscriptEvent(role="tool_result", content=text, metadata=obj)
        text = _flatten_user_content(obj)
        return TranscriptEvent(role="user", content=text, metadata=obj)
    if kind == "system":
        text = _flatten_system_content(obj)
        return TranscriptEvent(role="system", content=text, metadata=obj)
    if kind == "tool_use":
        return TranscriptEvent(role="tool_use", content="", metadata=obj)
    if kind == "tool_result":
        text = _flatten_tool_result_content(obj)
        return TranscriptEvent(role="tool_result", content=text, metadata=obj)
    if kind == "hook":
        text = obj.get("reason", "") or obj.get("message", "")
        return TranscriptEvent(role="hook", content=str(text), metadata=obj)
    return TranscriptEvent(role="unknown", content="", metadata=obj)


def _flatten_assistant_content(obj: dict[str, Any]) -> str:
    msg = obj.get("message", obj)
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    out.append(block["text"])
                elif block.get("type") == "tool_use":
                    out.append(f"[tool_use: {block.get('name', '?')}]")
        return "\n".join(out)
    return ""


def _user_blocks(obj: dict[str, Any]) -> list[Any]:
    msg = obj.get("message", obj)
    content = msg.get("content") if isinstance(msg, dict) else obj.get("content")
    return content if isinstance(content, list) else []


def _flatten_user_content(obj: dict[str, Any]) -> str:
    msg = obj.get("message", obj)
    content = msg.get("content") if isinstance(msg, dict) else obj.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                out.append(block["text"])
            elif isinstance(block, str):
                out.append(block)
        return "\n".join(out)
    return ""


def _flatten_system_content(obj: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("message", "content", "text", "reason"):
        v = obj.get(key)
        if isinstance(v, str):
            parts.append(v)
    return "\n".join(parts)


def _flatten_tool_result_content(obj: dict[str, Any]) -> str:
    content = obj.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                out.append(block["text"])
            elif isinstance(block, str):
                out.append(block)
        return "\n".join(out)
    return ""


class Transcript:
    """Query interface over a scenario run's transcript."""

    def __init__(self, events: Iterable[TranscriptEvent]):
        self._events: list[TranscriptEvent] = list(events)

    @classmethod
    def from_stream_json(cls, stream: str) -> "Transcript":
        return cls(parse_stream_json(stream))

    @property
    def events(self) -> list[TranscriptEvent]:
        return list(self._events)

    def assistant_turns(self) -> list[str]:
        return [e.content for e in self._events if e.role == "assistant"]

    def assistant_turn(self, n: int) -> str:
        turns = self.assistant_turns()
        return turns[n]

    def tool_uses(self, tool_name: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self._events:
            # tool_use can be a top-level event or embedded in an
            # assistant message's content blocks. Cover both shapes.
            if e.role == "tool_use":
                if tool_name is None or e.metadata.get("name") == tool_name:
                    out.append(e.metadata)
                continue
            if e.role == "assistant":
                msg = e.metadata.get("message", {})
                if not isinstance(msg, dict):
                    continue
                blocks = msg.get("content")
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if tool_name is None or block.get("name") == tool_name:
                        out.append(block)
        return out

    def hook_events(self, event_name: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self._events:
            if e.role != "hook":
                continue
            if event_name is None or e.metadata.get("event") == event_name:
                out.append(e.metadata)
        return out

    def system_messages(self) -> list[str]:
        return [e.content for e in self._events if e.role == "system" and e.content]

    def contains_text_in_assistant(self, pattern: "str | re.Pattern[str]") -> bool:
        haystack = "\n".join(self.assistant_turns()).lower()
        if isinstance(pattern, re.Pattern):
            return bool(pattern.search("\n".join(self.assistant_turns())))
        return pattern.lower() in haystack

    def deny_event_index(self) -> int | None:
        """The index of the first event that carries a deny from the harness
        (a system message, an error tool result or a hook event -- never the
        agent's own words), else None."""
        for i, e in enumerate(self._events):
            if _carries_deny(e):
                return i
        return None

    def deny_reason_received(self) -> str | None:
        """Return the deny-reason text if the agent received one, else None.

        We treat 'received' as: any system message OR tool_result OR
        assistant turn that contains a recognised deny-reason marker.
        Substring match is intentionally permissive — Claude Code may
        wrap, paraphrase, or quote the reason. The point is to know that
        the *signal* arrived, not which exact wording carried it.
        """
        for e in self._events:
            if e.role not in {"system", "tool_result", "hook", "assistant"}:
                continue
            if e.role == "tool_result" and not _is_error_result(e):
                # A Read or grep of a hook's own source carries every marker; only
                # a tool call the CLI reports failed can be a hook's deny.
                continue
            for marker in _DENY_REASON_MARKERS:
                if marker.lower() in e.content.lower():
                    return marker
        return None


def _is_error_result(e: TranscriptEvent) -> bool:
    """The CLI marks a refused or failed tool call `is_error: true` (on the
    `tool_result` block of a user event, or on a top-level result event)."""
    if e.metadata.get("is_error") is True:
        return True
    msg = e.metadata.get("message")
    blocks = msg.get("content") if isinstance(msg, dict) else None
    return isinstance(blocks, list) and any(isinstance(b, dict) and b.get("is_error") is True for b in blocks)


def _carries_deny(e: TranscriptEvent) -> bool:
    if e.role not in {"system", "tool_result", "hook"}:
        return False
    if e.role == "tool_result" and not _is_error_result(e):
        return False
    return any(m.lower() in e.content.lower() for m in _DENY_REASON_MARKERS)
