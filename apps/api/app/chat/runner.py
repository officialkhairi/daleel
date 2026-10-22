"""Executes one run: streams the model into the run's event stream, then persists the answer.

Runs outlive the HTTP request that started them, so a client can drop and resume (Last-Event-ID)
or cancel from another request. Phase 4 grows this into the agent loop."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chat, Message, Run
from app.db.session import tenant_session
from app.llm.base import ChatMessage, Finish, LLMError, LLMProvider, TextDelta, Usage
from app.streaming.bus import RunBus
from app.streaming.events import ErrorEvent, RunCompleted, Token, UsageEvent

log = logging.getLogger(__name__)

CANCEL_POLL_SECONDS = 0.2

SYSTEM_PROMPT = (
    "You are Daleel, an assistant for enterprise documents. "
    "Reply in the language of the user's latest message (Arabic or English). "
    "Use Markdown for lists, tables and emphasis. If you are not sure, say so plainly."
)


@dataclass(frozen=True)
class RunSpec:
    run_id: uuid.UUID
    chat_id: uuid.UUID
    tenant_id: uuid.UUID
    model: str
    history: list[ChatMessage]


@dataclass(frozen=True)
class Pricing:
    in_per_mtok: float
    out_per_mtok: float

    def cost(self, usage: Usage) -> float:
        return round(
            (usage.tokens_in * self.in_per_mtok + usage.tokens_out * self.out_per_mtok) / 1e6, 6
        )


_STATUS = {
    # finish_reason -> (run status, assistant message status)
    "stop": ("completed", "complete"),
    "length": ("completed", "complete"),
    "tool_calls": ("completed", "complete"),
    "cancelled": ("cancelled", "cancelled"),
    "error": ("failed", "error"),
}


async def execute_run(
    spec: RunSpec,
    *,
    provider: LLMProvider,
    bus: RunBus,
    sessions: async_sessionmaker[AsyncSession],
    pricing: Pricing,
) -> None:
    parts: list[str] = []
    usage: Usage | None = None
    finish = "stop"
    error: ErrorEvent | None = None
    next_cancel_check = 0.0

    try:
        async for event in provider.stream(spec.history, [], model=spec.model):
            now = time.monotonic()
            if now >= next_cancel_check:
                next_cancel_check = now + CANCEL_POLL_SECONDS
                if await bus.cancel_requested(spec.run_id):
                    finish = "cancelled"
                    break
            if isinstance(event, TextDelta):
                parts.append(event.text)
                await bus.publish(spec.run_id, Token(text=event.text))
            elif isinstance(event, Usage):
                usage = event
            elif isinstance(event, Finish):
                finish = event.reason
            # Tool-call events are ignored until the agent loop (Phase 4).
    except LLMError as exc:
        finish = "error"
        error = ErrorEvent(code=exc.code, message=exc.message, retryable=exc.retryable)
    except asyncio.CancelledError:
        # The API is shutting down. Record what we have, then let cancellation proceed.
        finish = "error"
        error = ErrorEvent(code="server_shutdown", message="The server restarted.", retryable=True)
        await _finish(spec, sessions, bus, parts, usage, finish, error, pricing)
        raise
    except Exception:
        log.exception("run %s failed", spec.run_id)
        finish = "error"
        error = ErrorEvent(code="internal_error", message="Something went wrong.", retryable=True)

    await _finish(spec, sessions, bus, parts, usage, finish, error, pricing)


async def _finish(
    spec: RunSpec,
    sessions: async_sessionmaker[AsyncSession],
    bus: RunBus,
    parts: list[str],
    usage: Usage | None,
    finish: str,
    error: ErrorEvent | None,
    pricing: Pricing,
) -> None:
    run_status, message_status = _STATUS.get(finish, ("completed", "complete"))
    content = "".join(parts)
    message_id: uuid.UUID | None = None

    if error is not None:
        await bus.publish(spec.run_id, error)
    if usage is not None:
        await bus.publish(
            spec.run_id,
            UsageEvent(
                tokens_in=usage.tokens_in, tokens_out=usage.tokens_out, cost_usd=pricing.cost(usage)
            ),
        )

    async with tenant_session(sessions, spec.tenant_id) as session:
        # An error before any text leaves no assistant message; the client offers a retry.
        if content or error is None:
            message = Message(
                tenant_id=spec.tenant_id,
                chat_id=spec.chat_id,
                role="assistant",
                content=content,
                status=message_status,
                model=spec.model,
                tokens_in=usage.tokens_in if usage else None,
                tokens_out=usage.tokens_out if usage else None,
            )
            session.add(message)
            await session.flush()
            message_id = message.id
        await session.execute(
            update(Run)
            .where(Run.id == spec.run_id)
            .values(
                status=run_status,
                assistant_message_id=message_id,
                finished_at=func.now(),
                error=error.model_dump() if error else None,
            )
        )
        await session.execute(
            update(Chat).where(Chat.id == spec.chat_id).values(updated_at=func.now())
        )

    await bus.publish(spec.run_id, RunCompleted(message_id=message_id, finish_reason=finish))
