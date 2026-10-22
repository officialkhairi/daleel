"""Executes one run: streams the model into the run's event stream, then persists the answer.

Runs outlive the HTTP request that started them, so a client can drop and resume (Last-Event-ID)
or cancel from another request. Phase 4 grows this into the agent loop."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.language import Language
from app.db.models import Chat, Message, Run
from app.db.session import tenant_session
from app.llm.base import ChatMessage, Finish, LLMError, LLMProvider, TextDelta, Usage
from app.rag.citations import CitationFilter
from app.rag.prompt import sources_prompt
from app.rag.retrieve import RetrievedChunk
from app.streaming.bus import RunBus
from app.streaming.events import Citation, ErrorEvent, RunCompleted, Token, UsageEvent

log = logging.getLogger(__name__)

CANCEL_POLL_SECONDS = 0.2
SNIPPET_CHARS = 240

Retriever = Callable[[str], Awaitable[list[RetrievedChunk]]]


@dataclass(frozen=True)
class RunSpec:
    run_id: uuid.UUID
    chat_id: uuid.UUID
    tenant_id: uuid.UUID
    model: str
    history: list[ChatMessage]  # system prompt first, question last
    question: str
    language: Language


@dataclass(frozen=True)
class Pricing:
    in_per_mtok: float
    out_per_mtok: float

    def cost(self, usage: Usage) -> float:
        return round(
            (usage.tokens_in * self.in_per_mtok + usage.tokens_out * self.out_per_mtok) / 1e6, 6
        )


@dataclass
class _Answer:
    parts: list[str] = field(default_factory=list)
    sources: list[RetrievedChunk] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    dropped_citations: int = 0


def _citation(n: int, chunk: RetrievedChunk) -> Citation:
    snippet = chunk.text if len(chunk.text) <= SNIPPET_CHARS else chunk.text[:SNIPPET_CHARS] + "…"
    return Citation(
        n=n,
        chunk_id=chunk.chunk_id,
        doc_id=chunk.document_id,
        title=chunk.title,
        page=chunk.page,
        bbox=chunk.bboxes[0] if chunk.bboxes else None,
        bboxes=chunk.bboxes,
        snippet=snippet,
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
    retriever: Retriever | None = None,
) -> None:
    answer = _Answer()
    parts = answer.parts
    usage: Usage | None = None
    finish = "stop"
    error: ErrorEvent | None = None
    next_cancel_check = 0.0
    citations = CitationFilter(valid=set())

    async def emit(text: str, new_citations: list[int]) -> None:
        if text:
            parts.append(text)
            await bus.publish(spec.run_id, Token(text=text))
        for n in new_citations:
            citation = _citation(n, answer.sources[n - 1])
            answer.citations.append(citation)
            await bus.publish(spec.run_id, citation)

    try:
        messages = spec.history
        if retriever is not None:
            answer.sources = await retriever(spec.question)
            if answer.sources:
                system = messages[0]
                grounded = f"{system.content}\n\n{sources_prompt(answer.sources, spec.language)}"
                messages = [system.model_copy(update={"content": grounded}), *messages[1:]]
                citations = CitationFilter(valid=set(range(1, len(answer.sources) + 1)))

        async for event in provider.stream(messages, [], model=spec.model):
            now = time.monotonic()
            if now >= next_cancel_check:
                next_cancel_check = now + CANCEL_POLL_SECONDS
                if await bus.cancel_requested(spec.run_id):
                    finish = "cancelled"
                    break
            if isinstance(event, TextDelta):
                await emit(*citations.feed(event.text))
            elif isinstance(event, Usage):
                usage = event
            elif isinstance(event, Finish):
                finish = event.reason
            # Tool-call events are ignored until the agent loop (Phase 4).
        await emit(*citations.flush())
    except LLMError as exc:
        finish = "error"
        error = ErrorEvent(code=exc.code, message=exc.message, retryable=exc.retryable)
    except asyncio.CancelledError:
        # The API is shutting down. Record what we have, then let cancellation proceed.
        finish = "error"
        error = ErrorEvent(code="server_shutdown", message="The server restarted.", retryable=True)
        answer.dropped_citations = citations.dropped
        await _finish(spec, sessions, bus, answer, usage, finish, error, pricing)
        raise
    except Exception:
        log.exception("run %s failed", spec.run_id)
        finish = "error"
        error = ErrorEvent(code="internal_error", message="Something went wrong.", retryable=True)

    if error is None and finish != "cancelled" and not "".join(parts).strip():
        # Small models sometimes stop at once or emit only whitespace; that is not an answer.
        finish = "error"
        error = ErrorEvent(
            code="empty_answer", message="The model returned an empty answer.", retryable=True
        )

    answer.dropped_citations = citations.dropped
    if citations.dropped:
        log.info(
            "run %s: removed %d citations to unretrieved sources", spec.run_id, citations.dropped
        )
    await _finish(spec, sessions, bus, answer, usage, finish, error, pricing)


async def _finish(
    spec: RunSpec,
    sessions: async_sessionmaker[AsyncSession],
    bus: RunBus,
    answer: _Answer,
    usage: Usage | None,
    finish: str,
    error: ErrorEvent | None,
    pricing: Pricing,
) -> None:
    run_status, message_status = _STATUS.get(finish, ("completed", "complete"))
    content = "".join(answer.parts)
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
        if content.strip() or error is None:
            message = Message(
                tenant_id=spec.tenant_id,
                chat_id=spec.chat_id,
                role="assistant",
                content=content,
                status=message_status,
                model=spec.model,
                tokens_in=usage.tokens_in if usage else None,
                tokens_out=usage.tokens_out if usage else None,
                citations=[c.model_dump(mode="json") for c in answer.citations] or None,
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
                state={
                    "retrieved_chunk_ids": [str(c.chunk_id) for c in answer.sources],
                    "dropped_citations": answer.dropped_citations,
                },
            )
        )
        await session.execute(
            update(Chat).where(Chat.id == spec.chat_id).values(updated_at=func.now())
        )

    await bus.publish(spec.run_id, RunCompleted(message_id=message_id, finish_reason=finish))
