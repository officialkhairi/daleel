"""The SSE protocol (docs/PLAN.md). Every run's stream ends with exactly one `run.completed`;
an `error` event, when present, comes right before it."""

import uuid
from typing import ClassVar

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


class ErrorEvent(StreamEvent):
    name: ClassVar[str] = "error"
    code: str
    message: str
    retryable: bool


class RunCompleted(StreamEvent):
    name: ClassVar[str] = "run.completed"
    message_id: uuid.UUID | None
    finish_reason: str  # stop | length | cancelled | error


TERMINAL_EVENT = RunCompleted.name


def encode_sse(event_id: str, name: str, data: str) -> bytes:
    # `data` is single-line JSON, so one `data:` field is enough.
    return f"id: {event_id}\nevent: {name}\ndata: {data}\n\n".encode()


HEARTBEAT = b": ping\n\n"
