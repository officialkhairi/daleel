"""Row-level security is the last line of tenant isolation: these tests use the app role
directly, bypassing every API check."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.principal import Principal, tenant_id_for
from app.config import Settings
from app.db.models import User
from app.db.session import make_engine, make_sessionmaker, tenant_session
from app.db.users import upsert_user


def principal(tenant: str, sub: str) -> Principal:
    return Principal(
        sub=sub, tenant=tenant, tenant_id=tenant_id_for(tenant), username=sub, roles=frozenset()
    )


@pytest.fixture
async def sessions(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(settings.database_url)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def test_tenant_cannot_read_another_tenants_users(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    alice = principal("tenant-a", "alice")
    bob = principal("tenant-b", "bob")
    async with tenant_session(sessions, alice.tenant_id) as s:
        await upsert_user(s, alice)
    async with tenant_session(sessions, bob.tenant_id) as s:
        await upsert_user(s, bob)

    async with tenant_session(sessions, alice.tenant_id) as s:
        subs = (await s.execute(select(User.oidc_sub))).scalars().all()
    assert "alice" in subs
    assert "bob" not in subs


async def test_no_tenant_set_sees_nothing(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:
        count = (await s.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert count == 0


async def test_cannot_write_into_another_tenant(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    mallory = principal("tenant-m", "mallory")
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(sessions, tenant_id_for("tenant-other")) as s:
            await upsert_user(s, mallory)
