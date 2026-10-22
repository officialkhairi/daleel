"""Real Postgres (migrated with the API's Alembic), Redis and MinIO; fake embeddings."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.db.session import make_engine, make_sessionmaker
from app.embeddings.fake import FakeEmbedder
from app.storage import ObjectStore
from daleel_worker.ingest import IngestDeps

API_DIR = Path(__file__).resolve().parents[2] / "api"
DEMO_DIR = Path(__file__).resolve().parents[3] / "docs" / "demo"
# Same image (pinned by digest) as deploy/compose.
MINIO_IMAGE = (
    "cgr.dev/chainguard/minio"
    "@sha256:d88920d6a50bd0b088223b688be3b76c63e6205dbe494437f67ba1240ea12880"
)
APP_ROLE, APP_PASSWORD = "daleel_app", "app-test-password"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        owner_url = pg.get_connection_url()
        cfg = Config(str(API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_DIR / "app" / "db" / "migrations"))
        cfg.attributes["url"] = owner_url
        cfg.attributes["app_db_user"] = APP_ROLE
        command.upgrade(cfg, "head")
        sql = f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"
        result = pg.exec(["psql", "-U", pg.username, "-d", pg.dbname, "-c", sql])
        assert result.exit_code == 0, result.output
        yield owner_url.replace(f"{pg.username}:{pg.password}@", f"{APP_ROLE}:{APP_PASSWORD}@")


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    container = (
        DockerContainer("redis:7.4-alpine")
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def minio_endpoint() -> Iterator[str]:
    container = (
        DockerContainer(MINIO_IMAGE)
        .with_command("server /data")
        .with_env("MINIO_ROOT_USER", "test")
        .with_env("MINIO_ROOT_PASSWORD", "test-secret")
        .with_exposed_ports(9000)
        .waiting_for(LogMessageWaitStrategy("API:"))
    )
    with container:
        yield f"{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"


@pytest.fixture(scope="session")
async def store(minio_endpoint: str) -> ObjectStore:
    client = Minio(minio_endpoint, access_key="test", secret_key="test-secret", secure=False)
    object_store = ObjectStore(client, "daleel-test")
    await object_store.ensure_bucket()
    return object_store


@pytest.fixture
async def deps(database_url: str, redis_url: str, store: ObjectStore) -> AsyncIterator[IngestDeps]:
    engine = make_engine(database_url)
    redis = Redis.from_url(redis_url)
    yield IngestDeps(
        sessions=make_sessionmaker(engine),
        store=store,
        embedder=FakeEmbedder(),
        redis=redis,
        batch_size=4,
    )
    await redis.aclose()
    await engine.dispose()


@pytest.fixture
def sessions(deps: IngestDeps) -> async_sessionmaker[AsyncSession]:
    return deps.sessions


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()
