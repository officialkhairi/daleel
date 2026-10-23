"""The SSE protocol (docs/PLAN.md). Every run's stream ends with exactly one `run.completed`;
an `error` event, when present, comes right before it."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel


class StreamEvent(BaseModel):
    name: ClassVar[str]


class RunStarted(StreamEvent):
    name: ClassVar[str] = "run.started"
    run_id: uuid.UUID
    model: str


class Token(StreamEvent):
    name: ClassVar[str] = "token"
    text: str


class UsageEvent(StreamEvent):
    name: ClassVar[str] = "usage"
    tokens_in: int
    tokens_out: int
    cost_usd: float


class Citation(StreamEvent):
    """Sent the first time an answer cites source [n]."""

    name: ClassVar[str] = "citation"
    n: int
    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    title: str
    page: int | None
    bbox: dict[str, float | int] | None  # first box, for a quick jump
    bboxes: list[dict[str, float | int]]  # every box of the passage, for the highlight
    snippet: str


class ToolStarted(StreamEvent):
    name: ClassVar[str] = "tool.started"
    call_id: str
    tool: str
    args: dict[str, Any]


class ToolResult(StreamEvent):
    name: ClassVar[str] = "tool.result"
    call_id: str
    tool: str
    summary: str
    ok: bool
    duration_ms: int
    data: dict[str, Any] = {}


class ApprovalRequired(StreamEvent):
    """The run pauses here until a person decides (POST /api/approvals/{approval_id})."""

    name: ClassVar[str] = "approval.required"
    approval_id: uuid.UUID
    call_id: str
    tool: str
    args: dict[str, Any]
    json_schema: dict[str, Any]
    risk: str
    expires_at: datetime


class ErrorEvent(StreamEvent):
    name: ClassVar[str] = "error"
    code: str
    message: str
    retryable: bool


class RunCompleted(StreamEvent):
    name: ClassVar[str] = "run.completed"
    message_id: uuid.UUID | None
    # stop | length | cancelled | error | awaiting_approval (the run resumes on this same stream
    # after the decision, ending with another run.completed)
    finish_reason: str


TERMINAL_EVENT = RunCompleted.name


def encode_sse(event_id: str, name: str, data: str) -> bytes:
    # `data` is single-line JSON, so one `data:` field is enough.
    return f"id: {event_id}\nevent: {name}\ndata: {data}\n\n".encode()


HEARTBEAT = b": ping\n\n"
