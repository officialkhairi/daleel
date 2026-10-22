"""Ingestion: object store → parse → chunk → embed → Postgres, publishing progress as it goes.
Re-running it for a document replaces that document's chunks."""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.language import detect_language
from app.db.models import Chunk, Document
from app.db.session import tenant_session
from app.documents.progress import DocumentStatus, ProgressEvent, Stage, publish
from app.embeddings.base import Embedder
from app.storage import ObjectStore
from daleel_worker.chunking import ChunkDraft, chunk_blocks
from daleel_worker.parsing import UnsupportedDocumentError, parse

log = logging.getLogger(__name__)


class IngestError(Exception):
    """A failure the uploader can act on; its message is shown in the UI."""


@dataclass(frozen=True)
class IngestDeps:
    sessions: async_sessionmaker[AsyncSession]
    store: ObjectStore
    embedder: Embedder
    redis: Redis
    batch_size: int = 16


class _Reporter:
    def __init__(self, deps: IngestDeps, document: Document) -> None:
        self._deps = deps
        self._document_id = document.id
        self._tenant_id = document.tenant_id
        self._acl = list(document.acl_roles)

    async def __call__(
        self,
        status: DocumentStatus,
        stage: Stage,
        progress: int,
        *,
        error: str | None = None,
        chunk_count: int | None = None,
        page_count: int | None = None,
    ) -> None:
        async with tenant_session(self._deps.sessions, self._tenant_id) as session:
            await session.execute(
                update(Document)
                .where(Document.id == self._document_id)
                .values(status=status, progress=progress, error=error, updated_at=func.now())
            )
        await publish(
            self._deps.redis,
            self._tenant_id,
            ProgressEvent(
                document_id=self._document_id,
                status=status,
                stage=stage,
                progress=progress,
                acl_roles=self._acl,
                error=error,
                chunk_count=chunk_count,
                page_count=page_count,
            ),
        )


async def ingest_document(deps: IngestDeps, document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    async with tenant_session(deps.sessions, tenant_id) as session:
        document = await session.scalar(select(Document).where(Document.id == document_id))
    if document is None:
        log.warning("document %s vanished before ingestion", document_id)
        return

    report = _Reporter(deps, document)
    try:
        await report("processing", "parsing", 5)
        data = await deps.store.get(document.s3_key)
        try:
            parsed = await asyncio.to_thread(parse, data, document.content_type)
        except UnsupportedDocumentError as exc:
            raise IngestError(str(exc)) from exc
        except Exception as exc:
            raise IngestError("The file could not be read. It may be damaged.") from exc

        await report("processing", "chunking", 15)
        drafts = chunk_blocks(parsed.blocks)
        if not drafts:
            raise IngestError(
                "No text found. Scanned documents need OCR, which isn't supported yet."
            )

        vectors: list[list[float]] = []
        for start in range(0, len(drafts), deps.batch_size):
            batch = drafts[start : start + deps.batch_size]
            vectors += await deps.embedder.embed([d.embedding_text for d in batch], kind="document")
            done = min(start + deps.batch_size, len(drafts))
            await report("processing", "embedding", 15 + int(75 * done / len(drafts)))

        await report("processing", "indexing", 92)
        language = detect_language(" ".join(d.text for d in drafts[:20]), fallback="en")
        await _store_chunks(deps, document, drafts, vectors, language, parsed.page_count)
        await report("ready", "done", 100, chunk_count=len(drafts), page_count=parsed.page_count)
        log.info("ingested %s: %d chunks", document_id, len(drafts))
    except IngestError as exc:
        await report("failed", "failed", 100, error=str(exc))
    except Exception:
        log.exception("ingestion of %s failed", document_id)
        await report("failed", "failed", 100, error="Processing failed. Try uploading it again.")


async def _store_chunks(
    deps: IngestDeps,
    document: Document,
    drafts: list[ChunkDraft],
    vectors: list[list[float]],
    language: str,
    page_count: int | None,
) -> None:
    async with tenant_session(deps.sessions, document.tenant_id) as session:
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        session.add_all(
            Chunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                ord=index,
                text=draft.text,
                heading=draft.heading,
                page=draft.page,
                bboxes=[box.as_dict() for box in draft.boxes],
                lang=detect_language(draft.text, fallback="ar" if language == "ar" else "en"),
                token_count=draft.token_count,
                embedding=vector,
            )
            for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True))
        )
        await session.execute(
            update(Document)
            .where(Document.id == document.id)
            .values(lang=language, page_count=page_count, chunk_count=len(drafts))
        )
