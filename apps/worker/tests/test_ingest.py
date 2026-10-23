import asyncio
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ALL_ROLES, Chunk, Document, Tenant
from app.db.session import tenant_session
from app.documents.progress import channel
from daleel_worker.ingest import IngestDeps, ingest_document
from daleel_worker.main import embed_texts
from tests.conftest import DEMO_DIR


async def make_document(
    deps: IngestDeps, tenant_id: uuid.UUID, data: bytes, content_type: str = "application/pdf"
) -> uuid.UUID:
    document_id = uuid.uuid4()
    key = f"{tenant_id}/{document_id}/file"
    await deps.store.put(key, data, content_type)
    async with tenant_session(deps.sessions, tenant_id) as session:
        await session.merge(Tenant(id=tenant_id, slug=str(tenant_id), name="t"))
        await session.flush()
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                title="Procurement Policy",
                filename="file.pdf",
                content_type=content_type,
                size_bytes=len(data),
                sha256=uuid.uuid4().hex * 2,
                s3_key=key,
                acl_roles=list(ALL_ROLES),
            )
        )
    return document_id


async def load(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[Document, list[Chunk]]:
    async with tenant_session(sessions, tenant_id) as session:
        document = await session.scalar(select(Document).where(Document.id == document_id))
        chunks = (
            await session.scalars(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ord)
            )
        ).all()
    assert document is not None
    return document, list(chunks)


async def test_ingests_arabic_pdf_with_progress(deps: IngestDeps, tenant_id: uuid.UUID) -> None:
    data = (DEMO_DIR / "procurement-policy-ar.pdf").read_bytes()
    document_id = await make_document(deps, tenant_id, data)
    pubsub = deps.redis.pubsub()
    await pubsub.subscribe(channel(tenant_id))
    await pubsub.get_message(timeout=1)

    await ingest_document(deps, document_id, tenant_id)

    document, chunks = await load(deps.sessions, tenant_id, document_id)
    assert (document.status, document.progress, document.error) == ("ready", 100, None)
    assert (document.lang, document.page_count, document.chunk_count) == ("ar", 2, len(chunks))
    assert len(chunks) >= 6
    threshold = next(c for c in chunks if c.heading == "2. حدود صلاحيات الاعتماد")
    assert "500,000 درهم" in threshold.text
    assert threshold.page == 1
    assert threshold.bboxes
    assert threshold.bboxes[0]["page"] == 1
    assert threshold.lang == "ar"
    assert threshold.embedding is not None
    assert len(threshold.embedding) == 1024

    events = []
    while (message := await pubsub.get_message(timeout=1)) is not None:
        if message["type"] == "message":
            events.append(json.loads(message["data"]))
    stages = [e["stage"] for e in events]
    assert stages[0] == "parsing"
    assert stages[-1] == "done"
    assert "embedding" in stages
    progress = [e["progress"] for e in events]
    assert progress == sorted(progress)
    assert events[-1]["chunk_count"] == len(chunks)
    await pubsub.aclose()


async def test_reingesting_replaces_chunks(deps: IngestDeps, tenant_id: uuid.UUID) -> None:
    data = (DEMO_DIR / "information-security-policy-en.pdf").read_bytes()
    document_id = await make_document(deps, tenant_id, data)
    await ingest_document(deps, document_id, tenant_id)
    _, first = await load(deps.sessions, tenant_id, document_id)
    await ingest_document(deps, document_id, tenant_id)
    document, second = await load(deps.sessions, tenant_id, document_id)
    assert len(second) == len(first) == document.chunk_count
    assert document.lang == "en"


async def test_document_without_text_fails_with_a_reason(
    deps: IngestDeps, tenant_id: uuid.UUID
) -> None:
    import pymupdf

    blank = pymupdf.open()
    blank.new_page()
    document_id = await make_document(deps, tenant_id, blank.tobytes())
    await ingest_document(deps, document_id, tenant_id)
    document, chunks = await load(deps.sessions, tenant_id, document_id)
    assert document.status == "failed"
    assert document.error is not None
    assert "No text found" in document.error
    assert chunks == []


async def test_damaged_file_fails_with_a_reason(deps: IngestDeps, tenant_id: uuid.UUID) -> None:
    document_id = await make_document(deps, tenant_id, b"%PDF-1.7 garbage")
    await ingest_document(deps, document_id, tenant_id)
    document, _ = await load(deps.sessions, tenant_id, document_id)
    assert (document.status, document.error) == (
        "failed",
        "The file could not be read. It may be damaged.",
    )


async def test_missing_document_is_ignored(deps: IngestDeps, tenant_id: uuid.UUID) -> None:
    await ingest_document(deps, uuid.uuid4(), tenant_id)  # no exception


async def test_embed_texts_job(deps: IngestDeps) -> None:
    vectors = await embed_texts({"deps": deps}, ["a", "b"], "query")
    assert len(vectors) == 2
    assert all(len(v) == 1024 for v in vectors)


async def test_store_round_trip(deps: IngestDeps) -> None:
    await deps.store.put("x/y.txt", b"hello", "text/plain")
    assert await deps.store.get("x/y.txt") == b"hello"
    await deps.store.delete("x/y.txt")
    await deps.store.delete("x/y.txt")  # deleting twice is fine
    await asyncio.sleep(0)
