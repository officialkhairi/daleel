from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from app.agent.effects import Mailer, Ticketing
from app.api import admin, approvals, audit, chats, documents, health, me, runs, ws
from app.auth.jwks import JWKSCache, TokenVerifier
from app.chat.tasks import TaskRegistry
from app.config import Settings, get_settings
from app.db.session import make_engine, make_sessionmaker
from app.embeddings.factory import build_query_embedder
from app.errors import ErrorEnvelope, install_error_handlers
from app.llm.base import LLMProvider
from app.llm.factory import build_provider
from app.observability.logging import RequestIdMiddleware, configure_logging
from app.storage import ObjectStore
from app.streaming.bus import RunBus


def create_app(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
    provider: LLMProvider | None = None,
    store: ObjectStore | None = None,
) -> FastAPI:
    """Tests inject `http_client` (JWKS from an in-process transport), `provider` and `store`."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http = http_client or httpx.AsyncClient()
        engine = make_engine(settings.database_url)
        jwks = JWKSCache(
            settings.oidc_jwks_url,
            http,
            ttl=settings.jwks_cache_ttl_seconds,
            min_refresh=settings.jwks_min_refresh_seconds,
        )
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        tasks = TaskRegistry()
        app.state.settings = settings
        app.state.redis = redis
        app.state.arq = arq
        app.state.store = store or ObjectStore.from_settings(settings)
        app.state.embedder = build_query_embedder(settings, http, arq)
        app.state.mailer = Mailer(
            host=settings.smtp_host, port=settings.smtp_port, sender=settings.smtp_from
        )
        app.state.ticketing = Ticketing(
            base_url=settings.ticketing_url,
            token=settings.ticketing_token.get_secret_value(),
            http=http,
        )
        app.state.engine = engine
        app.state.bus = RunBus(redis, ttl_seconds=settings.run_events_ttl_seconds)
        app.state.provider = provider or build_provider(settings, http)
        app.state.tasks = tasks
        app.state.sessions = make_sessionmaker(engine)
        app.state.verifier = TokenVerifier(
            jwks, issuer=settings.oidc_issuer, audience=settings.oidc_audience
        )
        try:
            yield
        finally:
            await tasks.shutdown()
            await arq.aclose()
            await redis.aclose()
            await engine.dispose()
            if http_client is None:
                await http.aclose()

    app = FastAPI(
        title="Daleel API",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            401: {"model": ErrorEnvelope},
            403: {"model": ErrorEnvelope},
            500: {"model": ErrorEnvelope},
        },
    )
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(chats.router)
    app.include_router(runs.router)
    app.include_router(documents.router)
    app.include_router(ws.router)
    app.include_router(approvals.router)
    app.include_router(audit.router)
    return app
