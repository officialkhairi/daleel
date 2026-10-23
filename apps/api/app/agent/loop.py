"""The agent loop: up to `max_steps` model turns, each of which may call tools.

Read-only tools run at once (in parallel). A tool that changes anything outside Daleel pauses
the run: its state is saved, approval rows are created, `approval.required` is emitted and the
stream ends with `run.completed(finish_reason="awaiting_approval")`. When every approval of the
run is decided, `resume_run` executes the approved calls (at most once each, keyed by approval)
or tells the model they were rejected, and continues on the same event stream.

Runs outlive the HTTP requests that start them, so clients can drop and resume (Last-Event-ID)
or cancel from another request."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import audit
from app.agent.effects import Mailer, Ticketing
from app.agent.tools import (
    TOOLS,
    Invocation,
    SourcePool,
    ToolContext,
    ToolOutcome,
    execute,
    prepare,
    tools_for,
)
from app.chat.language import Language
from app.db.models import Approval, Chat, Message, Run, ToolExecution
from app.db.session import tenant_session
from app.documents.progress import ApprovalNotice, publish
from app.embeddings.base import Embedder
from app.llm.base import (
    ChatMessage,
    Finish,
    LLMError,
    LLMProvider,
    TextDelta,
    ToolCallDone,
    Usage,
)
from app.rag.citations import CitationFilter
from app.rag.prompt import sources_prompt
from app.rag.retrieve import RetrievedChunk
from app.streaming.bus import RunBus
from app.streaming.events import (
    ApprovalRequired,
    Citation,
    ErrorEvent,
    RunCompleted,
    StreamEvent,
    Token,
    ToolResult,
    ToolStarted,
    UsageEvent,
)

log = logging.getLogger(__name__)

CANCEL_POLL_SECONDS = 0.2
SNIPPET_CHARS = 240
PREFETCH_CALL_ID = "prefetch"

Retriever = Callable[[str], Awaitable[list[RetrievedChunk]]]

_AGENT_INSTRUCTIONS: dict[Language, str] = {
    "en": (
        "You can use tools. Use search_documents before answering questions about policies or "
        "documents, and cite passages as [n]. Sending email, opening tickets and flagging "
        "clauses need a person's approval: call the tool to propose the action, and never say "
        "it is done until a tool result confirms it."
    ),
    "ar": (
        "يمكنك استخدام الأدوات. استخدم search_documents قبل الإجابة عن أسئلة السياسات أو "
        "المستندات، واذكر المقاطع بأرقامها [n]. إرسال البريد وفتح التذاكر ووضع علامات على البنود "
        "يحتاج إلى موافقة شخص: استدعِ الأداة لاقتراح الإجراء، ولا تقل إنه تم حتى تؤكد ذلك نتيجة "
        "الأداة."
    ),
}


@dataclass(frozen=True)
class Pricing:
    in_per_mtok: float
    out_per_mtok: float

    def cost(self, usage: Usage) -> float:
        return round(
            (usage.tokens_in * self.in_per_mtok + usage.tokens_out * self.out_per_mtok) / 1e6, 6
        )


@dataclass(frozen=True)
class RunSpec:
    run_id: uuid.UUID
    chat_id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    roles: frozenset[str]
    model: str
    history: list[ChatMessage]  # system prompt first, question last
    question: str
    language: Language

    def dump(self) -> dict[str, Any]:
        return {
            "chat_id": str(self.chat_id),
            "user_id": str(self.user_id),
            "username": self.username,
            "roles": sorted(self.roles),
            "model": self.model,
            "question": self.question,
            "language": self.language,
        }

    @classmethod
    def load(cls, run: Run) -> "RunSpec":
        data = run.state["spec"]
        return cls(
            run_id=run.id,
            chat_id=uuid.UUID(data["chat_id"]),
            tenant_id=run.tenant_id,
            user_id=uuid.UUID(data["user_id"]),
            username=data["username"],
            roles=frozenset(data["roles"]),
            model=data["model"],
            history=[],
            question=data["question"],
            language=data["language"],
        )


@dataclass(frozen=True)
class AgentDeps:
    provider: LLMProvider
    bus: RunBus
    redis: Redis
    sessions: async_sessionmaker[AsyncSession]
    embedder: Embedder
    mailer: Mailer
    ticketing: Ticketing
    pricing: Pricing
    retriever: Retriever | None = None
    max_steps: int = 6
    approval_ttl: timedelta = timedelta(hours=24)
    retrieval: dict[str, int] = field(
        default_factory=lambda: {"candidates": 20, "top_k": 6, "rrf_k": 60}
    )


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
    "awaiting_approval": ("awaiting_approval", "complete"),
}


class _Segment:
    """One stretch of a run between pauses: streams text, runs tools, and saves what it said."""

    def __init__(
        self,
        spec: RunSpec,
        deps: AgentDeps,
        messages: list[ChatMessage],
        pool: SourcePool,
        step: int,
    ) -> None:
        self.spec = spec
        self.deps = deps
        self.messages = messages
        self.pool = pool
        self.step = step
        self.parts: list[str] = []
        self.citations: list[Citation] = []
        self.calls: list[dict[str, Any]] = []  # tool calls shown with this answer
        self.filter = CitationFilter(valid=set(range(1, len(pool.chunks) + 1)))
        self.usage = Usage(tokens_in=0, tokens_out=0)
        self.saw_usage = False
        self.finish = "stop"
        self.error: ErrorEvent | None = None
        self.next_cancel_check = 0.0
        self.roles = spec.roles

    async def publish(self, event: StreamEvent) -> None:
        await self.deps.bus.publish(self.spec.run_id, event)

    def context(self, approval_id: uuid.UUID | None = None) -> ToolContext:
        return ToolContext(
            sessions=self.deps.sessions,
            tenant_id=self.spec.tenant_id,
            user_id=self.spec.user_id,
            username=self.spec.username,
            roles=self.roles,
            embedder=self.deps.embedder,
            sources=self.pool,
            mailer=self.deps.mailer,
            ticketing=self.deps.ticketing,
            retrieval=self.deps.retrieval,
            approval_id=approval_id,
        )

    async def emit(self, text: str, new: list[int]) -> None:
        if text:
            self.parts.append(text)
            await self.publish(Token(text=text))
        for n in new:
            citation = _citation(n, self.pool.chunks[n - 1])
            self.citations.append(citation)
            await self.publish(citation)

    async def cancelled(self) -> bool:
        now = time.monotonic()
        if now < self.next_cancel_check:
            return False
        self.next_cancel_check = now + CANCEL_POLL_SECONDS
        return await self.deps.bus.cancel_requested(self.spec.run_id)

    async def model_step(self) -> tuple[str, list[ToolCallDone]] | None:
        """Streams one model turn. None means the run was cancelled."""
        self.filter.valid = set(range(1, len(self.pool.chunks) + 1))
        specs = [t.spec() for t in tools_for(self.roles)]
        start = len(self.parts)
        calls: list[ToolCallDone] = []
        async for event in self.deps.provider.stream(self.messages, specs, model=self.spec.model):
            if await self.cancelled():
                self.finish = "cancelled"
                return None
            if isinstance(event, TextDelta):
                await self.emit(*self.filter.feed(event.text))
            elif isinstance(event, ToolCallDone):
                calls.append(event)
            elif isinstance(event, Usage):
                self.saw_usage = True
                self.usage = Usage(
                    tokens_in=self.usage.tokens_in + event.tokens_in,
                    tokens_out=self.usage.tokens_out + event.tokens_out,
                )
            elif isinstance(event, Finish):
                self.finish = "stop" if event.reason == "tool_calls" else event.reason
        await self.emit(*self.filter.flush())
        return "".join(self.parts[start:]), calls

    async def run_auto(self, invocation: Invocation) -> None:
        tool, args = invocation.ready()
        outcome, ms = await execute(tool, args, self.context())
        await self.tool_result(invocation.call_id, tool.name, outcome, ms)

    async def tool_result(
        self, call_id: str, tool: str, outcome: ToolOutcome, duration_ms: int
    ) -> None:
        self.messages.append(
            ChatMessage(role="tool", tool_call_id=call_id, content=outcome.content)
        )
        for call in self.calls:
            if call["call_id"] == call_id:
                call.update(summary=outcome.summary, ok=outcome.ok, data=outcome.data)
        await self.publish(
            ToolResult(
                call_id=call_id,
                tool=tool,
                summary=outcome.summary,
                ok=outcome.ok,
                duration_ms=duration_ms,
                data=outcome.data,
            )
        )

    async def drive(self) -> list[Invocation]:
        """Runs model turns until an answer, a pause, or the step limit. Returns calls that need
        approval (empty when the run is finished)."""
        while self.step < self.deps.max_steps:
            self.step += 1
            result = await self.model_step()
            if result is None:
                return []
            text, calls = result
            if not calls:
                return []
            self.messages.append(ChatMessage(role="assistant", content=text, tool_calls=calls))
            invocations = [prepare(c.call_id, c.name, c.args, self.roles) for c in calls]
            for inv in invocations:
                name = inv.tool.name if inv.tool else "unknown"
                self.calls.append({"call_id": inv.call_id, "tool": name, "args": inv.raw_args})
                await self.publish(ToolStarted(call_id=inv.call_id, tool=name, args=inv.raw_args))
            for inv in invocations:
                if inv.error is not None:
                    outcome = ToolOutcome(content=inv.error, summary=inv.error, ok=False)
                    await self.tool_result(
                        inv.call_id, inv.tool.name if inv.tool else "", outcome, 0
                    )
            auto = [
                i for i in invocations if i.error is None and i.tool and i.tool.policy == "auto"
            ]
            await asyncio.gather(*(self.run_auto(i) for i in auto))
            pending = [
                i for i in invocations if i.error is None and i.tool and i.tool.policy == "approve"
            ]
            if pending:
                return pending
        self.finish = "length"
        return []


def _system_prompt(spec: RunSpec, base: str, pool: SourcePool) -> str:
    prompt = f"{base}\n\n{_AGENT_INSTRUCTIONS[spec.language]}"
    if pool.chunks:
        prompt += f"\n\n{sources_prompt(pool.chunks, spec.language)}"
    return prompt


async def start_run(spec: RunSpec, deps: AgentDeps) -> None:
    pool = SourcePool()
    segment = _Segment(spec, deps, list(spec.history), pool, step=0)
    await _guard(segment, lambda: _first_segment(segment))


async def _first_segment(segment: _Segment) -> list[Invocation]:
    spec, deps = segment.spec, segment.deps
    if deps.retriever is not None:
        # Search for the question up front (shown as a search_documents call), so even models
        # that never call tools answer from the documents.
        await segment.publish(
            ToolStarted(
                call_id=PREFETCH_CALL_ID, tool="search_documents", args={"query": spec.question}
            )
        )
        started = time.perf_counter()
        found = await deps.retriever(spec.question)
        segment.pool.add(found)
        documents = len({c.document_id for c in found})
        segment.calls.append(
            {
                "call_id": PREFETCH_CALL_ID,
                "tool": "search_documents",
                "args": {"query": spec.question},
                "summary": f"Found {len(found)} passages in {documents} documents",
                "ok": True,
                "data": {"passages": len(found), "documents": documents},
            }
        )
        await segment.publish(
            ToolResult(
                call_id=PREFETCH_CALL_ID,
                tool="search_documents",
                summary=f"Found {len(found)} passages in {documents} documents",
                ok=True,
                duration_ms=round((time.perf_counter() - started) * 1000),
                data={"passages": len(found), "documents": documents},
            )
        )
    system = segment.messages[0]
    segment.messages[0] = system.model_copy(
        update={"content": _system_prompt(spec, system.content, segment.pool)}
    )
    return await segment.drive()


async def resume_run(run_id: uuid.UUID, tenant_id: uuid.UUID, deps: AgentDeps) -> None:
    """Continues a run whose approvals are all decided (the caller set it back to running)."""
    async with tenant_session(deps.sessions, tenant_id) as session:
        run = await session.scalar(select(Run).where(Run.id == run_id))
        if run is None:
            return
        approvals = {
            a.call_id: a
            for a in await session.scalars(select(Approval).where(Approval.run_id == run_id))
        }
    if run.status != "running" or "messages" not in run.state:
        log.info("run %s has nothing to resume", run_id)
        return
    spec = RunSpec.load(run)
    pool = SourcePool.load(run.state.get("sources", []))
    messages = [ChatMessage.model_validate(m) for m in run.state["messages"]]
    segment = _Segment(spec, deps, messages, pool, step=run.state.get("step", 0))

    async def continue_() -> list[Invocation]:
        for call_id in run.state.get("pending", []):
            approval = approvals[call_id]
            tool = TOOLS[approval.tool]
            segment.calls.append(
                {"call_id": call_id, "tool": tool.name, "args": approval.effective_args}
            )
            if approval.status == "approved":
                outcome, ms = await _execute_once(segment, approval)
            else:
                verdict = (
                    "rejected" if approval.status == "rejected" else "expired without a decision"
                )
                reason = f" Reason: {approval.reason}" if approval.reason else ""
                outcome = ToolOutcome(
                    content=f"A person {verdict} this action, so it was not carried out.{reason}",
                    summary=f"Not carried out ({approval.status})",
                    ok=False,
                )
                ms = 0
            await segment.tool_result(call_id, tool.name, outcome, ms)
        return await segment.drive()

    await _guard(segment, continue_)


async def _execute_once(segment: _Segment, approval: Approval) -> tuple[ToolOutcome, int]:
    """Claims the approval's execution row first, so a second attempt (retry, double click,
    restart) finds it and never repeats the side effect."""
    deps, spec = segment.deps, segment.spec
    args = approval.effective_args
    async with tenant_session(deps.sessions, spec.tenant_id) as session:
        claimed = await session.scalar(
            insert(ToolExecution)
            .values(
                tenant_id=spec.tenant_id,
                approval_id=approval.id,
                tool=approval.tool,
                args=args,
                status="running",
            )
            .on_conflict_do_nothing(index_elements=[ToolExecution.approval_id])
            .returning(ToolExecution.id)
        )
        if claimed is None:
            existing = await session.scalar(
                select(ToolExecution).where(ToolExecution.approval_id == approval.id)
            )
    if claimed is None:
        result = (existing.result if existing else None) or {}
        summary = result.get("summary", "Already carried out")
        return ToolOutcome(content=result.get("content", summary), summary=summary), 0

    tool = TOOLS[approval.tool]
    outcome, ms = await execute(tool, tool.parse(args), segment.context(approval.id))
    async with tenant_session(deps.sessions, spec.tenant_id) as session:
        await session.execute(
            update(ToolExecution)
            .where(ToolExecution.approval_id == approval.id)
            .values(
                status="succeeded" if outcome.ok else "failed",
                result={"content": outcome.content, "summary": outcome.summary, **outcome.data},
            )
        )
        await audit.record(
            session,
            tenant_id=spec.tenant_id,
            actor_id=approval.decided_by,
            actor="system",
            action="tool.executed" if outcome.ok else "tool.failed",
            target_type="approval",
            target_id=approval.id,
            details={"tool": approval.tool, "args": args, "summary": outcome.summary},
        )
    return outcome, ms


async def _guard(segment: _Segment, body: Callable[[], Awaitable[list[Invocation]]]) -> None:
    """Runs a segment and always ends its stream: paused, finished, failed or cancelled."""
    pending: list[Invocation] = []
    try:
        pending = await body()
    except LLMError as exc:
        segment.finish = "error"
        segment.error = ErrorEvent(code=exc.code, message=exc.message, retryable=exc.retryable)
    except asyncio.CancelledError:
        # The API is shutting down. Record what we have, then let cancellation proceed.
        segment.finish = "error"
        segment.error = ErrorEvent(
            code="server_shutdown", message="The server restarted.", retryable=True
        )
        await _finish(segment, [])
        raise
    except Exception:
        log.exception("run %s failed", segment.spec.run_id)
        segment.finish = "error"
        segment.error = ErrorEvent(
            code="internal_error", message="Something went wrong.", retryable=True
        )

    if pending:
        segment.finish = "awaiting_approval"
    elif (
        segment.error is None
        and segment.finish != "cancelled"
        and not "".join(segment.parts).strip()
    ):
        # Small models sometimes stop at once or emit only whitespace; that is not an answer.
        segment.finish = "error"
        segment.error = ErrorEvent(
            code="empty_answer", message="The model returned an empty answer.", retryable=True
        )
    if segment.filter.dropped:
        log.info(
            "run %s: removed %d citations to unretrieved sources",
            segment.spec.run_id,
            segment.filter.dropped,
        )
    await _finish(segment, pending)


async def _finish(segment: _Segment, pending: list[Invocation]) -> None:
    spec, deps = segment.spec, segment.deps
    run_status, message_status = _STATUS.get(segment.finish, ("completed", "complete"))
    content = "".join(segment.parts)
    message_id: uuid.UUID | None = None
    approvals: list[Approval] = []

    if segment.error is not None:
        await segment.publish(segment.error)
    if segment.saw_usage:
        await segment.publish(
            UsageEvent(
                tokens_in=segment.usage.tokens_in,
                tokens_out=segment.usage.tokens_out,
                cost_usd=deps.pricing.cost(segment.usage),
            )
        )

    async with tenant_session(deps.sessions, spec.tenant_id) as session:
        expires_at = await session.scalar(select(func.now() + deps.approval_ttl))
        for inv in pending:
            tool, args = inv.ready()
            approval = Approval(
                tenant_id=spec.tenant_id,
                run_id=spec.run_id,
                chat_id=spec.chat_id,
                requested_by=spec.user_id,
                call_id=inv.call_id,
                tool=tool.name,
                args=args.model_dump(mode="json"),
                json_schema=tool.json_schema(),
                risk=tool.risk,
                expires_at=expires_at,
            )
            session.add(approval)
            approvals.append(approval)
        await session.flush()
        for approval in approvals:
            for call in segment.calls:
                if call["call_id"] == approval.call_id:
                    call.update(approval_id=str(approval.id), args=approval.args)
            await audit.record(
                session,
                tenant_id=spec.tenant_id,
                actor_id=spec.user_id,
                actor=spec.username,
                action="approval.requested",
                target_type="approval",
                target_id=approval.id,
                details={"tool": approval.tool, "args": approval.args, "run_id": str(spec.run_id)},
            )

        # An error before any text leaves no assistant message; the client offers a retry.
        if content.strip() or approvals or segment.error is None:
            message = Message(
                tenant_id=spec.tenant_id,
                chat_id=spec.chat_id,
                role="assistant",
                content=content,
                status=message_status,
                model=spec.model,
                tokens_in=segment.usage.tokens_in if segment.saw_usage else None,
                tokens_out=segment.usage.tokens_out if segment.saw_usage else None,
                citations=[c.model_dump(mode="json") for c in segment.citations] or None,
                tool_calls=segment.calls or None,
            )
            session.add(message)
            await session.flush()
            message_id = message.id

        state: dict[str, Any] = {
            "spec": spec.dump(),
            "retrieved_chunk_ids": [str(c.chunk_id) for c in segment.pool.chunks],
            "dropped_citations": segment.filter.dropped,
        }
        if approvals:
            state.update(
                messages=[m.model_dump(mode="json") for m in segment.messages],
                sources=segment.pool.dump(),
                step=segment.step,
                pending=[a.call_id for a in approvals],
            )
        await session.execute(
            update(Run)
            .where(Run.id == spec.run_id)
            .values(
                status=run_status,
                assistant_message_id=message_id,
                step=segment.step,
                finished_at=None if approvals else func.now(),
                error=segment.error.model_dump() if segment.error else None,
                state=state,
            )
        )
        await session.execute(
            update(Chat).where(Chat.id == spec.chat_id).values(updated_at=func.now())
        )

    for approval in approvals:
        await segment.publish(
            ApprovalRequired(
                approval_id=approval.id,
                call_id=approval.call_id,
                tool=approval.tool,
                args=approval.args,
                json_schema=approval.json_schema,
                risk=approval.risk,
                expires_at=approval.expires_at,
            )
        )
        await publish(
            deps.redis,
            spec.tenant_id,
            ApprovalNotice(
                type="approval.created",
                approval_id=approval.id,
                run_id=spec.run_id,
                chat_id=spec.chat_id,
                tool=approval.tool,
                status="pending",
                requested_by=spec.user_id,
            ),
        )
    await segment.publish(RunCompleted(message_id=message_id, finish_reason=segment.finish))
