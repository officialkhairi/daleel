"""Admin console data: usage, users. Everything is scoped to the admin's tenant (RLS)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select, text

from app.api.health import HealthResponse
from app.auth.deps import require
from app.auth.principal import Principal
from app.db.models import Approval, Chat, Document, Message, User
from app.db.session import tenant_session

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require("admin"))])


@router.get("/ping")
async def ping() -> HealthResponse:
    """Smallest admin-only endpoint; exists to prove RBAC end to end."""
    return HealthResponse()


class UsageDay(BaseModel):
    day: date
    model: str
    runs: int
    failed: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    ttft_p50_ms: float | None
    ttft_p95_ms: float | None
    latency_p50_ms: float | None


class Totals(BaseModel):
    documents: int
    chats: int
    questions: int
    pending_approvals: int
    users: int


class Usage(BaseModel):
    days: list[UsageDay]
    totals: Totals


@router.get("/usage")
async def usage(
    request: Request,
    principal: Annotated[Principal, Depends(require("admin"))],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> Usage:
    """Per day and model: runs, failures, tokens, cost, time to first token (p50/p95)."""
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT day, model, runs, failed, tokens_in, tokens_out, cost_usd, ttft_p50_ms,"
                " ttft_p95_ms, latency_p50_ms FROM usage_daily"
                " WHERE day >= current_date - CAST(:days AS integer) ORDER BY day, model"
            ),
            {"days": days - 1},
        )
        series = [UsageDay.model_validate(dict(r._mapping)) for r in rows]

        async def count(stmt: Select[int]) -> int:
            return int(await session.scalar(stmt) or 0)

        totals = Totals(
            documents=await count(select(func.count()).select_from(Document)),
            chats=await count(select(func.count()).select_from(Chat)),
            questions=await count(
                select(func.count()).select_from(Message).where(Message.role == "user")
            ),
            pending_approvals=await count(
                select(func.count()).select_from(Approval).where(Approval.status == "pending")
            ),
            users=await count(select(func.count()).select_from(User)),
        )
    return Usage(days=series, totals=totals)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str | None
    email: str | None
    locale: str
    roles: list[str]
    created_at: datetime
    last_seen_at: datetime


@router.get("/users")
async def users(
    request: Request, principal: Annotated[Principal, Depends(require("admin"))]
) -> list[UserOut]:
    """People who have signed in, with the roles their last token carried (Keycloak decides)."""
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        found = await session.scalars(select(User).order_by(User.last_seen_at.desc()).limit(500))
        return [UserOut.model_validate(u) for u in found]
