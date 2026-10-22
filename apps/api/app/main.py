from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api import admin, health, me
from app.auth.jwks import JWKSCache, TokenVerifier
from app.config import Settings, get_settings
from app.db.session import make_engine, make_sessionmaker
from app.errors import ErrorEnvelope, install_error_handlers
from app.observability.logging import RequestIdMiddleware, configure_logging


def create_app(
    settings: Settings | None = None, *, http_client: httpx.AsyncClient | None = None
) -> FastAPI:
    """`http_client` lets tests serve JWKS from an in-process transport."""
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
        app.state.engine = engine
        app.state.sessions = make_sessionmaker(engine)
        app.state.verifier = TokenVerifier(
            jwks, issuer=settings.oidc_issuer, audience=settings.oidc_audience
        )
        try:
            yield
        finally:
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
    return app
