"""Hybrid retrieval: vector (bge-m3, HNSW) and keyword (tsvector, Arabic + English stemming) run in
parallel and are merged with reciprocal rank fusion. Tenant isolation comes from RLS; role-based
document access (acl_roles) is enforced in the same SQL, so nothing a user may not read is ever
returned, ranked or shown to the model."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chunk, Document
from app.db.session import tenant_session
from app.embeddings.base import Embedder, EmbeddingError

log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    text: str
    heading: str | None
    page: int | None
    bboxes: list[dict[str, Any]]
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)


def _base(roles: Sequence[str], document_ids: Sequence[uuid.UUID] | None = None) -> Select[Any]:
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.title,
            Chunk.text,
            Chunk.heading,
            Chunk.page,
            Chunk.bboxes,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.status == "ready", Document.acl_roles.overlap(list(roles)))
    )
    if document_ids:
        stmt = stmt.where(Document.id.in_(list(document_ids)))
    return stmt


def _row(row: Any) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.id,
        document_id=row.document_id,
        title=row.title,
        text=row.text,
        heading=row.heading,
        page=row.page,
        bboxes=row.bboxes,
    )


async def vector_search(
    session: AsyncSession,
    vector: list[float],
    roles: Sequence[str],
    limit: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    # With a WHERE clause, HNSW may stop before finding `limit` matches; iterative scans keep
    # going (pgvector >= 0.8).
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = Chunk.embedding.cosine_distance(vector)
    stmt = (
        _base(roles, document_ids)
        .where(Chunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    return [_row(r) for r in (await session.execute(stmt)).all()]


async def keyword_search(
    session: AsyncSession,
    query: str,
    roles: Sequence[str],
    limit: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    # plainto_tsquery ANDs every word, which rarely matches a whole question; OR them instead and
    # let ts_rank_cd reward chunks that match more of them. Both stemmers run on the query because
    # it may be in either language.
    tsquery = text(
        "(replace(plainto_tsquery('english', :q)::text, '&', '|')::tsquery"
        " || replace(plainto_tsquery('arabic', :q)::text, '&', '|')::tsquery)"
    )
    rank = func.ts_rank_cd(Chunk.tsv, tsquery)
    stmt = (
        _base(roles, document_ids)
        .where(Chunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt, {"q": query})).all()
    return [_row(r) for r in rows]


def fuse(
    result_lists: dict[str, list[RetrievedChunk]], *, k: int, top_k: int
) -> list[RetrievedChunk]:
    """Reciprocal rank fusion: score = sum over methods of 1 / (k + rank)."""
    merged: dict[uuid.UUID, RetrievedChunk] = {}
    for method, results in result_lists.items():
        for rank, chunk in enumerate(results, start=1):
            entry = merged.setdefault(chunk.chunk_id, chunk)
            entry.ranks[method] = rank
            entry.score += 1.0 / (k + rank)
    return sorted(merged.values(), key=lambda c: c.score, reverse=True)[:top_k]


async def retrieve(
    sessions: async_sessionmaker[AsyncSession],
    *,
    tenant_id: uuid.UUID,
    roles: Sequence[str],
    query: str,
    embedder: Embedder,
    candidates: int,
    top_k: int,
    rrf_k: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[RetrievedChunk]:
    async def by_vector() -> list[RetrievedChunk]:
        try:
            vector = (await embedder.embed([query], kind="query"))[0]
        except EmbeddingError as exc:
            # Keyword search still works without the embedding model.
            log.warning("vector search skipped: %s", exc)
            return []
        async with tenant_session(sessions, tenant_id) as session:
            return await vector_search(session, vector, roles, candidates, document_ids)

    async def by_keyword() -> list[RetrievedChunk]:
        async with tenant_session(sessions, tenant_id) as session:
            return await keyword_search(session, query, roles, candidates, document_ids)

    vector_results, keyword_results = await asyncio.gather(by_vector(), by_keyword())
    return fuse({"vector": vector_results, "keyword": keyword_results}, k=rrf_k, top_k=top_k)
