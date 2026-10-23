from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.auth.deps import require
from app.auth.principal import Principal
from app.db.models import AuditEntry
from app.db.session import tenant_session

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any]
    created_at: datetime


@router.get("")
async def list_(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: Annotated[int | None, Query(description="Entries older than this id.")] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    principal: Principal = Depends(require("admin")),
) -> list[AuditEntryOut]:
    """Newest first. The log is append-only: the database refuses updates and deletes."""
    stmt = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    if before is not None:
        stmt = stmt.where(AuditEntry.id < before)
    if action:
        stmt = stmt.where(AuditEntry.action == action)
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        return [AuditEntryOut.model_validate(e) for e in await session.scalars(stmt)]
