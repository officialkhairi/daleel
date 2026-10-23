import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Approval, Chat, User


class ApprovalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    chat_id: uuid.UUID
    chat_title: str
    call_id: str
    tool: str
    args: dict[str, Any]
    edited_args: dict[str, Any] | None
    json_schema: dict[str, Any]
    risk: Literal["low", "medium", "high"]
    status: Literal["pending", "approved", "rejected", "expired"]
    requested_by: uuid.UUID | None
    requested_by_name: str | None
    decided_by_name: str | None
    decided_at: datetime | None
    reason: str | None
    expires_at: datetime
    created_at: datetime


async def load_approvals(session: AsyncSession, *where: Any) -> list[ApprovalOut]:
    requester, decider = aliased(User), aliased(User)
    stmt = (
        select(Approval, Chat.title, requester, decider)
        .join(Chat, Chat.id == Approval.chat_id)
        .outerjoin(requester, requester.id == Approval.requested_by)
        .outerjoin(decider, decider.id == Approval.decided_by)
        .where(*where)
        .order_by(Approval.created_at.desc())
        .limit(200)
    )

    def name(user: User | None) -> str | None:
        return (user.display_name or user.username) if user else None

    return [
        ApprovalOut(
            id=a.id,
            run_id=a.run_id,
            chat_id=a.chat_id,
            chat_title=title,
            call_id=a.call_id,
            tool=a.tool,
            args=a.args,
            edited_args=a.edited_args,
            json_schema=a.json_schema,
            risk=a.risk,
            status=a.status,
            requested_by=a.requested_by,
            requested_by_name=name(req),
            decided_by_name=name(dec),
            decided_at=a.decided_at,
            reason=a.reason,
            expires_at=a.expires_at,
            created_at=a.created_at,
        )
        for a, title, req, dec in (await session.execute(stmt)).all()
    ]
