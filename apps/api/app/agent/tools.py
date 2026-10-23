"""The tools the agent may call. Each has a Pydantic argument model (its JSON Schema is what the
model sees and what the approval form is generated from) and a fixed policy:

- auto: runs as soon as the model asks (read-only: searching and reading documents);
- approve: never runs until a person with the approver role approves it, whatever the model says.

The policy lives here, in code, so no prompt or document can change it."""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from html import escape
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.effects import EffectError, Mailer, Ticketing
from app.db.models import Chunk, ClauseFlag, Document
from app.db.session import tenant_session
from app.embeddings.base import Embedder
from app.llm.base import ToolSpec
from app.rag.retrieve import RetrievedChunk, retrieve

Policy = Literal["auto", "approve"]
Risk = Literal["low", "medium", "high"]
EDITORS = frozenset({"editor", "admin"})
EVERYONE = frozenset({"viewer", "editor", "approver", "admin"})


class SourcePool:
    """Every passage shown to the model during a run, numbered once, so [n] means the same
    passage across tool calls and across an approval pause."""

    def __init__(self, chunks: Sequence[RetrievedChunk] = ()) -> None:
        self.chunks: list[RetrievedChunk] = list(chunks)

    def add(self, chunks: Sequence[RetrievedChunk]) -> list[tuple[int, RetrievedChunk]]:
        numbered = []
        for chunk in chunks:
            existing = next(
                (i for i, c in enumerate(self.chunks) if c.chunk_id == chunk.chunk_id), None
            )
            if existing is None:
                self.chunks.append(chunk)
                existing = len(self.chunks) - 1
            numbered.append((existing + 1, self.chunks[existing]))
        return numbered

    @staticmethod
    def render(numbered: Sequence[tuple[int, RetrievedChunk]]) -> str:
        """Escaped, so a document can't close the tag and pose as instructions."""
        if not numbered:
            return "No matching passages."
        blocks = []
        for n, chunk in numbered:
            attrs = f'n="{n}" title="{escape(chunk.title)}"'
            if chunk.page is not None:
                attrs += f' page="{chunk.page}"'
            body = f"{chunk.heading}\n{chunk.text}" if chunk.heading else chunk.text
            blocks.append(f"<source {attrs}>\n{escape(body, quote=False)}\n</source>")
        return "\n".join(blocks)

    def dump(self) -> list[dict[str, Any]]:
        return [
            {**c.__dict__, "chunk_id": str(c.chunk_id), "document_id": str(c.document_id)}
            for c in self.chunks
        ]

    @classmethod
    def load(cls, data: list[dict[str, Any]]) -> "SourcePool":
        return cls(
            [
                RetrievedChunk(
                    **{
                        **d,
                        "chunk_id": uuid.UUID(d["chunk_id"]),
                        "document_id": uuid.UUID(d["document_id"]),
                    }
                )
                for d in data
            ]
        )


@dataclass
class ToolContext:
    """What a tool may touch: the caller's tenant (RLS) and the documents their roles may read."""

    sessions: async_sessionmaker[AsyncSession]
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    roles: frozenset[str]
    embedder: Embedder
    sources: SourcePool
    mailer: Mailer
    ticketing: Ticketing
    retrieval: dict[str, int] = field(
        default_factory=lambda: {"candidates": 20, "top_k": 6, "rrf_k": 60}
    )
    approval_id: uuid.UUID | None = None


@dataclass
class ToolOutcome:
    content: str  # what the model reads
    summary: str  # what the person sees
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = True


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- argument models ------------------------------------------------------------------------


class SearchDocumentsArgs(_Args):
    query: Annotated[str, Field(min_length=1, max_length=500, description="What to look for.")]
    document_ids: list[uuid.UUID] | None = Field(
        default=None, description="Only search these documents."
    )


class GetDocumentArgs(_Args):
    document_id: uuid.UUID
    pages: list[Annotated[int, Field(ge=1)]] | None = Field(
        default=None, max_length=10, description="Pages to read; the first pages when omitted."
    )


class CompareClausesArgs(_Args):
    document_a: uuid.UUID
    document_b: uuid.UUID
    topic: Annotated[str, Field(min_length=1, max_length=300)]


class SummarizeDocumentArgs(_Args):
    document_id: uuid.UUID
    lang: Literal["ar", "en"] = Field(default="en", description="Language of the summary.")


class CreateTicketArgs(_Args):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=5000)]
    priority: Literal["low", "medium", "high"] = "medium"


class SendEmailArgs(_Args):
    to: list[EmailStr] = Field(min_length=1, max_length=10, description="Recipients.")
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=10_000)]


class FlagClauseArgs(_Args):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


# --- implementations ------------------------------------------------------------------------


async def _search(ctx: ToolContext, args: SearchDocumentsArgs) -> ToolOutcome:
    found = await retrieve(
        ctx.sessions,
        tenant_id=ctx.tenant_id,
        roles=sorted(ctx.roles),
        query=args.query,
        embedder=ctx.embedder,
        document_ids=args.document_ids,
        **ctx.retrieval,
    )
    numbered = ctx.sources.add(found)
    documents = len({c.document_id for c in found})
    return ToolOutcome(
        content=SourcePool.render(numbered),
        summary=f"Found {len(found)} passages in {documents} documents",
        data={"passages": len(found), "documents": documents},
    )


async def _visible_document(
    ctx: ToolContext, session: AsyncSession, document_id: uuid.UUID
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.status == "ready",
            Document.acl_roles.overlap(sorted(ctx.roles)),
        )
    )
    if document is None:
        raise ToolError("No such document, or you don't have access to it.")
    return document


async def _chunks(
    ctx: ToolContext, document_id: uuid.UUID, *, pages: list[int] | None, limit: int
) -> tuple[Document, list[RetrievedChunk]]:
    async with tenant_session(ctx.sessions, ctx.tenant_id) as session:
        document = await _visible_document(ctx, session, document_id)
        stmt = select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.ord)
        if pages:
            stmt = stmt.where(Chunk.page.in_(pages))
        rows = (await session.scalars(stmt.limit(limit))).all()
    return document, [
        RetrievedChunk(
            chunk_id=c.id,
            document_id=c.document_id,
            title=document.title,
            text=c.text,
            heading=c.heading,
            page=c.page,
            bboxes=c.bboxes,
        )
        for c in rows
    ]


async def _get_document(ctx: ToolContext, args: GetDocumentArgs) -> ToolOutcome:
    document, chunks = await _chunks(ctx, args.document_id, pages=args.pages, limit=12)
    numbered = ctx.sources.add(chunks)
    return ToolOutcome(
        content=SourcePool.render(numbered),
        summary=f"Read {len(chunks)} passages of {document.title}",
        data={"passages": len(chunks), "title": document.title},
    )


async def _compare(ctx: ToolContext, args: CompareClausesArgs) -> ToolOutcome:
    async def side(document_id: uuid.UUID) -> list[RetrievedChunk]:
        return await retrieve(
            ctx.sessions,
            tenant_id=ctx.tenant_id,
            roles=sorted(ctx.roles),
            query=args.topic,
            embedder=ctx.embedder,
            document_ids=[document_id],
            candidates=ctx.retrieval["candidates"],
            top_k=3,
            rrf_k=ctx.retrieval["rrf_k"],
        )

    a, b = await asyncio.gather(side(args.document_a), side(args.document_b))
    if not a or not b:
        raise ToolError("Couldn't find that topic in both documents (or one isn't accessible).")
    first, second = ctx.sources.add(a), ctx.sources.add(b)
    return ToolOutcome(
        content=(
            f"From {escape(a[0].title)}:\n{SourcePool.render(first)}\n\n"
            f"From {escape(b[0].title)}:\n{SourcePool.render(second)}"
        ),
        summary=f"Compared {a[0].title} with {b[0].title}",
        data={"documents": [a[0].title, b[0].title], "a": a[0].title, "b": b[0].title},
    )


async def _summarize(ctx: ToolContext, args: SummarizeDocumentArgs) -> ToolOutcome:
    document, chunks = await _chunks(ctx, args.document_id, pages=None, limit=12)
    numbered = ctx.sources.add(chunks)
    language = "Arabic" if args.lang == "ar" else "English"
    return ToolOutcome(
        content=f"Summarize this in {language}, citing passages:\n{SourcePool.render(numbered)}",
        summary=f"Read {document.title} to summarize it",
        data={"title": document.title},
    )


async def _create_ticket(ctx: ToolContext, args: CreateTicketArgs) -> ToolOutcome:
    ticket = await ctx.ticketing.create(
        title=args.title, body=args.body, priority=args.priority, requester=ctx.username
    )
    key = str(ticket.get("key") or ticket.get("id"))
    return ToolOutcome(
        content=f"Ticket {key} was created.",
        summary=f"Created ticket {key}",
        data={"ticket": ticket, "key": key},
    )


async def _send_email(ctx: ToolContext, args: SendEmailArgs) -> ToolOutcome:
    recipients = [str(a) for a in args.to]
    message_id = await ctx.mailer.send(
        to=recipients,
        subject=args.subject,
        body=args.body,
        headers={"X-Daleel-Approval": str(ctx.approval_id or "")},
    )
    return ToolOutcome(
        content=f"The email was sent to {', '.join(recipients)}.",
        summary=f"Sent email to {', '.join(recipients)}",
        data={"to": recipients, "recipients": ", ".join(recipients), "message_id": message_id},
    )


async def _flag_clause(ctx: ToolContext, args: FlagClauseArgs) -> ToolOutcome:
    async with tenant_session(ctx.sessions, ctx.tenant_id) as session:
        document = await _visible_document(ctx, session, args.document_id)
        chunk = await session.scalar(
            select(Chunk).where(Chunk.id == args.chunk_id, Chunk.document_id == document.id)
        )
        if chunk is None:
            raise ToolError("That passage isn't in that document.")
        session.add(
            ClauseFlag(
                tenant_id=ctx.tenant_id,
                document_id=document.id,
                chunk_id=chunk.id,
                reason=args.reason,
                flagged_by=ctx.user_id,
            )
        )
    return ToolOutcome(
        content="The clause was flagged for review.",
        summary=f"Flagged a clause in {document.title}",
        data={"title": document.title},
    )


# --- registry -------------------------------------------------------------------------------


class ToolError(Exception):
    """A tool couldn't do what was asked; the message is returned to the model."""


Runner = Callable[[ToolContext, Any], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    policy: Policy
    run: Runner
    risk: Risk = "low"
    # Who may have the agent use this tool (checked when offering it and when executing it).
    roles: frozenset[str] = EVERYONE

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.json_schema())

    def json_schema(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        # jsonb doesn't keep object key order; forms read the field order from this list.
        schema["x-order"] = list(schema.get("properties", {}))
        return schema

    def parse(self, raw: dict[str, Any]) -> BaseModel:
        return self.args.model_validate(raw)


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "search_documents",
            "Search the organisation's documents (Arabic and English). Returns numbered passages "
            "to cite as [n].",
            SearchDocumentsArgs,
            "auto",
            _search,
        ),
        Tool(
            "get_document",
            "Read passages of one document, optionally only some pages.",
            GetDocumentArgs,
            "auto",
            _get_document,
        ),
        Tool(
            "compare_clauses",
            "Find what two documents say about the same topic, to compare them.",
            CompareClausesArgs,
            "auto",
            _compare,
        ),
        Tool(
            "summarize_document",
            "Read a document in order so you can summarize it.",
            SummarizeDocumentArgs,
            "auto",
            _summarize,
        ),
        Tool(
            "create_ticket",
            "Open a ticket in the ticketing system. A person must approve it first.",
            CreateTicketArgs,
            "approve",
            _create_ticket,
            risk="medium",
        ),
        Tool(
            "send_email",
            "Send an email. A person must approve it first; they may edit it.",
            SendEmailArgs,
            "approve",
            _send_email,
            risk="high",
        ),
        Tool(
            "flag_clause",
            "Flag a passage of a document for review by its owners. A person must approve it.",
            FlagClauseArgs,
            "approve",
            _flag_clause,
            roles=EDITORS,
        ),
    ]
}


def tools_for(roles: frozenset[str]) -> list[Tool]:
    return [t for t in TOOLS.values() if t.roles & roles]


@dataclass
class Invocation:
    call_id: str
    tool: Tool | None
    raw_args: dict[str, Any]
    args: BaseModel | None = None
    error: str | None = None

    def ready(self) -> tuple[Tool, BaseModel]:
        """The validated tool and arguments; only for invocations without an error."""
        if self.tool is None or self.args is None:
            raise RuntimeError(f"tool call {self.call_id} was not validated: {self.error}")
        return self.tool, self.args


def prepare(call_id: str, name: str, raw_args: dict[str, Any], roles: frozenset[str]) -> Invocation:
    """Look up and validate a model's tool call. Problems become a message back to the model."""
    tool = TOOLS.get(name)
    if tool is None or not tool.roles & roles:
        return Invocation(call_id, None, raw_args, error=f"There is no tool called {name}.")
    try:
        return Invocation(call_id, tool, raw_args, args=tool.parse(raw_args))
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return Invocation(call_id, tool, raw_args, error=f"Invalid arguments: {problems}")


async def execute(tool: Tool, args: BaseModel, ctx: ToolContext) -> tuple[ToolOutcome, int]:
    """Runs a tool, turning expected failures into an outcome the model can read."""
    started = time.perf_counter()
    if not tool.roles & ctx.roles:
        outcome = ToolOutcome(
            content="You don't have permission for this.", summary="Not permitted", ok=False
        )
    else:
        try:
            outcome = await tool.run(ctx, args)
        except (ToolError, EffectError) as exc:
            outcome = ToolOutcome(content=str(exc), summary=str(exc), ok=False)
    return outcome, round((time.perf_counter() - started) * 1000)
