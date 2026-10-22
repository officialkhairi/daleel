"""Shared fixtures. No test talks to a real Keycloak: tokens are signed with a throwaway RSA key
and the JWKS endpoint is served by an in-process httpx transport."""

import json
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app
from app.storage import ObjectStore

ISSUER = "http://keycloak.test/realms/daleel"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
AUDIENCE = "daleel-api"
KID = "test-key"
APP_ROLE = "daleel_app"
APP_PASSWORD = "app-test-password"

TokenFactory = Callable[..., str]


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks_body(rsa_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key()))
    return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}


@pytest.fixture(scope="session")
def make_token(rsa_key: rsa.RSAPrivateKey) -> TokenFactory:
    def factory(
        *,
        roles: list[str] | None = None,
        sub: str | None = None,
        tenant: str | None = "acme",
        kid: str = KID,
        key: rsa.RSAPrivateKey | None = None,
        **overrides: Any,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": sub or str(uuid.uuid4()),
            "iat": now,
            "exp": now + 300,
            "preferred_username": "officer",
            "name": "Compliance Officer",
            "email": "officer@daleel.local",
            "locale": "en",
            "realm_access": {"roles": roles if roles is not None else ["editor", "approver"]},
        }
        if tenant is not None:
            claims["tenant"] = tenant
        claims.update(overrides)
        return jwt.encode(claims, key or rsa_key, algorithm="RS256", headers={"kid": kid})

    return factory


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def database_urls(postgres: PostgresContainer) -> tuple[str, str]:
    """(owner_url, app_url). Migrates once per session, then opens the app role for login."""
    owner_url = postgres.get_connection_url()
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = owner_url
    cfg.attributes["app_db_user"] = APP_ROLE
    command.upgrade(cfg, "head")

    sql = f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"
    result = postgres.exec(["psql", "-U", postgres.username, "-d", postgres.dbname, "-c", sql])
    assert result.exit_code == 0, result.output

    app_url = owner_url.replace(
        f"{postgres.username}:{postgres.password}@", f"{APP_ROLE}:{APP_PASSWORD}@"
    )
    return owner_url, app_url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    redis = (
        DockerContainer("redis:7.4-alpine")
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with redis as container:
        host = container.get_container_host_ip()
        yield f"redis://{host}:{container.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def settings(database_urls: tuple[str, str], redis_url: str) -> Settings:
    return Settings(
        database_url=database_urls[1],
        redis_url=redis_url,
        oidc_issuer=ISSUER,
        oidc_jwks_url=JWKS_URL,
        oidc_audience=AUDIENCE,
        _env_file=None,
    )


@pytest.fixture
def jwks_requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def jwks_transport(
    jwks_body: dict[str, Any], jwks_requests: list[httpx.Request]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        jwks_requests.append(request)
        if str(request.url) == JWKS_URL:
            return httpx.Response(200, json=jwks_body)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def provider() -> FakeProvider:
    """Echoes by default. Tests script turns with `provider._turns` or swap app.state.provider."""
    return FakeProvider()


class MemoryStore(ObjectStore):
    """In-memory stand-in for MinIO (the worker's tests use a real one)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def ensure_bucket(self) -> None:
        return None

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
async def app(
    settings: Settings,
    jwks_transport: httpx.MockTransport,
    provider: FakeProvider,
    store: MemoryStore,
) -> AsyncIterator[FastAPI]:
    async with httpx.AsyncClient(transport=jwks_transport) as http:
        application = create_app(settings, http_client=http, provider=provider, store=store)
        async with application.router.lifespan_context(application):
            yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
        yield c
