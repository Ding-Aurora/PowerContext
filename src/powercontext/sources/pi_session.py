"""Import the visible events of an offline Pi v3 session branch."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from typing import Never

from pydantic import BaseModel, JsonValue

from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

_SOURCE_TYPE = "pi-event"


class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _compact(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value: JsonValue) -> str:
    return hashlib.sha256(_compact(value).encode("utf-8")).hexdigest()


def _identity(event: PiEventInput) -> str:
    return "pi:" + _digest([event.session_id, event.event_id])


def _invalid_constant(value: str) -> Never:
    raise ValueError(f"Invalid JSON constant in Pi session: {value}")


def _parse_branch(
    value: PiSessionInput,
) -> tuple[str, dict[str, dict[str, JsonValue]], list[str]]:
    # Decode one physical JSONL record at a time instead of retaining a decoded
    # copy of the entire log plus a list of every line alongside parsed records.
    stream = io.TextIOWrapper(io.BytesIO(value.content), encoding="utf-8-sig", newline="")
    lines = (line for line in stream if line.strip())
    header = json.loads(next(lines, "null"), parse_constant=_invalid_constant)
    if not isinstance(header, dict) or header.get("type") != "session" or type(header.get("version")) is not int:
        raise ValueError("Pi session must start with a version 3 session header")
    session_id = header.get("id")
    if header["version"] != 3 or not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session must have version 3 and a non-blank session ID")

    records: dict[str, dict[str, JsonValue]] = {}
    parents: dict[str, str | None] = {}
    for line in lines:
        record = json.loads(line, parse_constant=_invalid_constant)
        if not isinstance(record, dict):
            raise ValueError("Pi session entries must be JSON objects")
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip() or event_id in records:
            raise ValueError("Pi session entries must have unique non-blank IDs")
        parent = record.get("parentId")
        if "parentId" not in record or (parent is not None and (not isinstance(parent, str) or parent not in records)):
            raise ValueError(f"Pi event {event_id!r} must reference an earlier parent or null")
        records[event_id] = record
        parents[event_id] = parent

    leaf = value.leaf_id
    if leaf is None:
        leaf = next(reversed(records), None)
    elif leaf not in records:
        raise ValueError(f"Pi session has no leaf with ID {leaf!r}")
    path = []
    while leaf is not None:
        path.append(leaf)
        leaf = parents[leaf]
    path.reverse()
    return session_id, records, path


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _visible_blocks(content: JsonValue, *, tool_calls: bool = False) -> str:
    if not isinstance(content, list):
        return _text(content)
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(_text(block.get("text")))
        elif tool_calls and block.get("type") == "toolCall":
            name = _text(block.get("name"))
            call_id = _text(block.get("id"))
            arguments = _compact(block.get("arguments", {}))
            parts.append(f"[tool_call {name} {call_id}] {arguments}")
    return "\n".join(parts)


def _event_text(record: dict[str, JsonValue]) -> tuple[str, str]:
    kind = record.get("type")
    if kind in ("compaction", "branch_summary"):
        return _text(kind), _text(record.get("summary"))
    if kind == "custom_message":
        return "custom", _visible_blocks(record.get("content"))
    message = record.get("message")
    if kind != "message" or not isinstance(message, dict):
        return "", ""
    role = _text(message.get("role"))
    if role == "bashExecution":
        command, output = _text(message.get("command")), _text(message.get("output"))
        return role, f"$ {command}\n{output}" if command.strip() or output.strip() else ""
    body = _visible_blocks(message.get("content"), tool_calls=True)
    if role == "toolResult" and body.strip():
        name = _text(message.get("toolName"))
        call_id = _text(message.get("toolCallId"))
        body = f"[tool_result {name} {call_id}] {body}"
    return role, body


def _events(
    session_id: str, records: dict[str, dict[str, JsonValue]], path: list[str]
) -> tuple[PiEventInput, ...]:
    events = []
    for event_id in path:
        record = records[event_id]
        role, body = _event_text(record)
        if role.strip() and body.strip():
            events.append(PiEventInput(
                session_id=session_id,
                event_id=event_id,
                parent_id=record["parentId"],
                event_type=_text(record.get("type")),
                role=role,
                content=f"{role}: {body}",
                record=record,
            ))
    return tuple(events)


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Return visible evidence on the selected path, including pre-compaction events."""
    return _events(*_parse_branch(value))


class _PiEventAdapter:
    name = _SOURCE_TYPE
    input_class = PiEventInput
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(name=_identity(value), materialization=SourceMaterialization.CAPTURED, **value.model_dump())

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput.model_validate(source.model_dump(include=set(PiEventInput.model_fields)))


class _PiTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=_SOURCE_TYPE,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    _PiEventAdapter(), projections=(_PiTextEvidence(),),
)


class _PiCheckpoint(BaseModel):
    session_id: str
    imported: dict[str, str]


class PiSessionConnector:
    """Import selected events through the lifecycle's durable checkpoint."""

    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({_SOURCE_TYPE})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = await asyncio.to_thread(self.path.read_bytes)
        session_id, records, path = _parse_branch(PiSessionInput(content=raw, leaf_id=self.leaf_id))
        imported: dict[str, str] = {}
        if session.checkpoint is not None:
            checkpoint = _PiCheckpoint.model_validate(session.checkpoint)
            if checkpoint.session_id != session_id:
                raise ValueError("Pi session ID changed for this connector binding")
            imported = checkpoint.imported.copy()
        # Compare even the events no longer on the selected branch before submitting anything.
        for event_id, fingerprint in imported.items():
            if event_id not in records or _digest(records[event_id]) != fingerprint:
                raise ValueError(f"Previously imported Pi event {event_id!r} was removed or rewritten")
        pending_path = [event_id for event_id in path if event_id not in imported]
        for event in _events(session_id, records, pending_path):
            fingerprint = _digest(event.record)
            outcome = await session.submit(_identity(event), _SOURCE_TYPE, event)
            if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE)
            imported[event.event_id] = fingerprint
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint=_PiCheckpoint(session_id=session_id, imported=imported).model_dump(mode="json"),
        )
