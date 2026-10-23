"""Arq worker entry point: `arq daleel_worker.main.WorkerSettings`."""

import uuid
from typing import Any, ClassVar

import httpx
from arq import cron, func
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.agent.expiry import expire_stale_approvals
from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.embeddings.base import EmbedKind
from app.jobs import EMBED_TEXTS, INGEST_DOCUMENT
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing, tracer
from app.storage import ObjectStore
from daleel_worker.embedders import build_embedder
from daleel_worker.ingest import IngestDeps
from daleel_worker.ingest import ingest_document as run_ingest

Ctx = dict[str, Any]


async def startup(ctx: Ctx) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.otel_exporter_otlp_endpoint, settings.otel_service_name)
    http = httpx.AsyncClient()
    engine = make_engine(settings.database_url)
    store = ObjectStore.from_settings(settings)
    await store.ensure_bucket()
    redis = Redis.from_url(settings.redis_url)
    ctx.update(
        http=http,
        engine=engine,
        redis_pub=redis,
        deps=IngestDeps(
            sessions=make_sessionmaker(engine),
            store=store,
            embedder=build_embedder(settings, http),
            redis=redis,
            batch_size=settings.embeddings_batch_size,
        ),
    )


async def shutdown(ctx: Ctx) -> None:
    await ctx["http"].aclose()
    await ctx["redis_pub"].aclose()
    await ctx["engine"].dispose()


async def ingest_document(ctx: Ctx, document_id: str, tenant_id: str) -> None:
    with tracer.start_as_current_span("ingest_document", attributes={"document.id": document_id}):
        await run_ingest(ctx["deps"], uuid.UUID(document_id), uuid.UUID(tenant_id))


async def expire_approvals(ctx: Ctx) -> int:
    deps: IngestDeps = ctx["deps"]
    return await expire_stale_approvals(deps.sessions, ctx["redis_pub"])


async def embed_texts(ctx: Ctx, texts: list[str], kind: EmbedKind) -> list[list[float]]:
    deps: IngestDeps = ctx["deps"]
    vectors: list[list[float]] = await deps.embedder.embed(texts, kind=kind)
    return vectors


class WorkerSettings:
    functions: ClassVar = [
        func(ingest_document, name=INGEST_DOCUMENT, max_tries=1, timeout=900),
        # Query embeddings are awaited by the API; keep results only briefly.
        func(embed_texts, name=EMBED_TEXTS, max_tries=1, timeout=60, keep_result=60),
    ]
    cron_jobs: ClassVar = [cron(expire_approvals, minute=set(range(0, 60, 5)), run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    # Lets `arq --check` (the container healthcheck) see a recent heartbeat.
    health_check_interval = 30
    # Short poll so query embeddings aren't held up behind the default 0.5 s.
    poll_delay = 0.05
