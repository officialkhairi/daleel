"""Append-only audit trail (the table refuses UPDATE and DELETE)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEntry


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    actor: str,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEntry(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            details=details or {},
        )
    )
