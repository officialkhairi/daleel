"""Approvals left undecided past their expiry (24 h by default). Run periodically by the worker."""

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.documents.progress import ApprovalNotice, publish


async def expire_stale_approvals(sessions: async_sessionmaker[AsyncSession], redis: Redis) -> int:
    """Expires overdue approvals in every tenant, closes their runs and notifies the inboxes."""
    async with sessions() as session, session.begin():
        rows = (await session.execute(text("SELECT * FROM expire_stale_approvals()"))).all()
    for row in rows:
        await publish(
            redis,
            row.tenant_id,
            ApprovalNotice(
                type="approval.decided",
                approval_id=row.approval_id,
                run_id=row.run_id,
                chat_id=row.chat_id,
                tool=row.tool,
                status="expired",
                requested_by=row.requested_by,
            ),
        )
    return len(rows)
