import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_principal, tenant_db
from app.auth.principal import Principal, Role
from app.db.users import upsert_user

router = APIRouter(prefix="/api", tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    sub: str
    username: str
    name: str | None
    email: str | None
    locale: str
    tenant: str
    roles: list[Role]


@router.get("/me")
async def me(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(tenant_db),
) -> MeResponse:
    user_id = await upsert_user(db, principal)
    return MeResponse(
        id=user_id,
        sub=principal.sub,
        username=principal.username,
        name=principal.name,
        email=principal.email,
        locale=principal.locale,
        tenant=principal.tenant,
        roles=sorted(principal.roles),
    )
