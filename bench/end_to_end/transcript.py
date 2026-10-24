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
    # A deny hook that could not start (DEF-1176, DEF-2010, DEF-3008): every
    # text `_start_refusal.refuse_on_helper_skew` emits ends on this clause,
    # its plain-words fallback and each hook's own last resort included.
    "this hook judges is refused until then",
    # The one call a wedged write_guard lets through, a restore to HEAD of a
    # file its refusal names (DEF-4025): context, not a deny, and it teaches.
    "so it refuses every call but one",
    # The stop-time override that could not be split, and the Windows shim remedy.
    "unbalanced quote",
    "resolves it through PATHEXT",
    "active execution plan",
    "kill-switch",
    # config_guard's refusal of a project-settings change that unwires a gate.
    "leaves governance gates unwired",
    # The stop-gate handoff gate (Gate 5, 2026-10-24), keyed on the HEAD of its
    # message like the two hygiene blocks below.
    "Handoff owed before Claude Code stops",
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


#: The CLI's own prefix when it relays a hook to the agent in a user event.
_HOOK_FEEDBACK = re.compile(r"\s*\w+ hook feedback:", re.IGNORECASE)


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
        if obj.get("isSynthetic") is True and _HOOK_FEEDBACK.match(_flatten_user_content(obj)):
            # A user event the CLI wrote itself to relay a hook ("Stop hook
            # feedback: ..."): the harness speaking, so the deny check reads it.
            # Other synthetic events (an interrupt notice) stay the user's.
            return TranscriptEvent(role="hook", content=_flatten_user_content(obj), metadata=obj)
        results = [b for b in _user_blocks(obj) if isinstance(b, dict) and b.get("type") == "tool_result"]
        if results:
            # Any tool_result block makes this a tool result (a text block beside
            # it must not hide a deny); only the result blocks are its text.
            text = "\n".join(_flatten_tool_result_content(b) for b in results)
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

    def unreached_model_error(self) -> str | None:
        """The run's error when it never reached the model, else None: its
        `result` event is an error and every assistant message in it is the
        CLI's own API-error message, never a model's. CLI 2.1.299 with no
        usable login sends an init, one such message (`is_api_error_message`,
        `error: authentication_failed`, `api_error_status: 401`) and an
        `is_error` result, then exits 1 with nothing on stderr; no hook can
        fire before a model turn, so such a run measured none."""
        result = next((e.metadata for e in reversed(self._events) if e.metadata.get("type") == "result"), None)
        if result is None or result.get("is_error") is not True:
            return None
        if any(e.role == "assistant" and not _is_api_error_message(e.metadata) for e in self._events):
            return None
        text = result.get("result")
        return text if isinstance(text, str) and text else str(result.get("terminal_reason") or "is_error")

    def deny_records(self) -> list[tuple[int, str | None, str, str | None]]:
        """``(event index, tool_use_id, text, timestamp)`` for every deny the
        harness delivered, in stream order: a hook's refusal of a tool call (its
        tool_use_id names the call it answers), or a hook or system message
        carrying a deny marker (no id); with the deny's text (write_guard's and
        plan_guard's name the path) and the time the CLI stamped on its event
        (every user and assistant event carries one, 2.1.299). Never the
        agent's own words."""
        out: list[tuple[int, str | None, str, str | None]] = []
        for i, e in enumerate(self._events):
            stamp = e.metadata.get("timestamp")
            stamp = stamp if isinstance(stamp, str) else None
            if e.role == "tool_result":
                out += [(i, tid, text, stamp) for tid, text in _hook_denials(e)]
            elif e.role in {"system", "hook"} and _marker_in(e.content):
                out.append((i, None, e.content, stamp))
        return out

    def permission_refusals(self) -> list[dict[str, Any]]:
        """The calls the CLI's own permission layer refused, not a hook, in
        stream order: ``{"index", "tool_use_id", "tool_name", "tool_input"}``.
        Read from the CLI's records, never a refusal's prose: a tool result's
        `tool_result_meta` entry (`permission_decision: {decision: reject,
        source: config}`), and the result event's `permission_denials`, which
        lists every refused call with its input (the meta alone is left when a
        timeout cuts the run before its result). `permission_denials` lists a
        hook's denials too, so a call a hook denied is left out."""
        hooked = {tid for _i, tid, _text, _stamp in self.deny_records() if tid}
        out: dict[str, dict[str, Any]] = {}
        for i, e in enumerate(self._events):
            for m in e.metadata.get("tool_result_meta") or []:
                decision = m.get("permission_decision") if isinstance(m, dict) else None
                if not isinstance(decision, dict) or not isinstance(m.get("id"), str):
                    continue
                if decision.get("source") == "hook":
                    hooked.add(m["id"])
                elif decision.get("source") == "config" and decision.get("decision") == "reject":
                    out.setdefault(m["id"], {"index": i, "tool_use_id": m["id"], "tool_name": None, "tool_input": None})
            if e.metadata.get("type") == "result":
                for d in e.metadata.get("permission_denials") or []:
                    if isinstance(d, dict) and isinstance(d.get("tool_use_id"), str):
                        rec = out.setdefault(d["tool_use_id"], {"index": i, "tool_use_id": d["tool_use_id"],
                                                                "tool_name": None, "tool_input": None})
                        rec["tool_name"] = rec["tool_name"] or d.get("tool_name")
                        if rec["tool_input"] is None and isinstance(d.get("tool_input"), dict):
                            rec["tool_input"] = d["tool_input"]
        return [rec for tid, rec in out.items() if tid not in hooked]

    def deny_events(self) -> list[tuple[int, str | None]]:
        """``(event index, tool_use_id)`` for every deny (`deny_records`)."""
        return [(i, tid) for i, tid, _text, _stamp in self.deny_records()]

    def deny_event_index(self) -> int | None:
        """The index of the first deny the harness delivered, else None."""
        events = self.deny_events()
        return events[0][0] if events else None

    def deny_reason_received(self) -> str | None:
        """The deny marker the agent received from the harness, else None.

        'Received' means a hook's refusal of a tool call (judged from the CLI's
        own record of the call, below) or a hook or system message carrying a
        recognised marker. The agent's own turns never count: an agent that
        read a hook's source can quote every marker without any hook firing,
        which once let a run PASS with the deny removed from its stream.
        Substring match stays permissive about the wording that carried it.
        """
        for e in self._events:
            if e.role == "tool_result":
                texts = [text for _tid, text in _hook_denials(e)]
            elif e.role in {"system", "hook"}:
                texts = [e.content]
            else:
                continue
            for t in texts:
                marker = _marker_in(t)
                if marker:
                    return marker
        return None


def _is_api_error_message(event: dict[str, Any]) -> bool:
    """An assistant event the CLI wrote for a failed API call, not the model."""
    msg = event.get("message")
    return event.get("is_api_error_message") is True or (isinstance(msg, dict) and msg.get("model") == "<synthetic>")


def _marker_in(text: str) -> str | None:
    lower = text.lower()
    return next((m for m in _DENY_REASON_MARKERS if m.lower() in lower), None)


def _result_blocks(e: TranscriptEvent) -> list[dict[str, Any]]:
    """The tool_result blocks of a tool-result event (a user event's blocks, or
    a top-level legacy `tool_result` event as its own single block)."""
    if e.metadata.get("type") == "tool_result":
        return [e.metadata]
    msg = e.metadata.get("message")
    blocks = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in blocks or [] if isinstance(b, dict) and b.get("type") == "tool_result"]


def _hook_denials(e: TranscriptEvent) -> list[tuple[str | None, str]]:
    """``(tool_use_id, text)`` for each block that is a hook's refusal. Where
    the CLI records the decision (`tool_result_meta[].permission_decision`,
    CLI 2.1.299), that record decides: `decision: reject, source: hook` is a
    hook's deny, and anything else is not, whatever its text (a failed grep of
    a hook's source carries every marker). Without a record (an older CLI), a
    block counts when it is itself an error AND carries a marker -- the flag and
    the marker on the same block, never one block's flag and another's text."""
    records = e.metadata.get("tool_result_meta")
    meta = {m.get("id"): m for m in records or [] if isinstance(m, dict)}
    out: list[tuple[str | None, str]] = []
    for block in _result_blocks(e):
        tid = block.get("tool_use_id")
        text = _flatten_tool_result_content(block)
        if isinstance(records, list):
            # The CLI records its calls here: a block it did not record as a
            # hook's reject is not one, whatever its text or error flag.
            record = meta.get(tid, {}).get("permission_decision")
            if isinstance(record, dict) and record.get("source") == "hook" and record.get("decision") == "reject":
                out.append((tid, text))
        elif block.get("is_error") is True and _marker_in(text):
            out.append((tid, text))
    return out
