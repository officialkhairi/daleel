import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.db.models import Tenant, User


async def upsert_user(session: AsyncSession, principal: Principal) -> uuid.UUID:
    """Records the caller's tenant and profile from their token; returns the users.id."""
    await session.execute(
        insert(Tenant)
        .values(id=principal.tenant_id, slug=principal.tenant, name=principal.tenant)
        .on_conflict_do_nothing(index_elements=[Tenant.id])
    )
    profile = {
        "username": principal.username,
        "email": principal.email,
        "display_name": principal.name,
        "locale": principal.locale,
    }
    stmt = (
        insert(User)
        .values(tenant_id=principal.tenant_id, oidc_sub=principal.sub, **profile)
        .on_conflict_do_update(
            index_elements=[User.tenant_id, User.oidc_sub],
            set_={**profile, "last_seen_at": func.now()},
        )
        .returning(User.id)
    )
    return (await session.execute(stmt)).scalar_one()
