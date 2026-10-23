"""Tenant notifications: ingestion progress (from the worker) and approval updates (from the API)
go out on one Redis channel per tenant; the API relays them to browsers over WebSocket, filtered
by what each viewer may see."""

import uuid
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis

DocumentStatus = Literal["uploaded", "processing", "ready", "failed"]
Stage = Literal["queued", "parsing", "chunking", "embedding", "indexing", "done", "failed"]


class ProgressEvent(BaseModel):
    type: Literal["document.progress"] = "document.progress"
    document_id: uuid.UUID
    status: DocumentStatus
    stage: Stage
    progress: int  # 0-100
    acl_roles: list[str]
    error: str | None = None
    chunk_count: int | None = None
    page_count: int | None = None


class ApprovalNotice(BaseModel):
    """Sent to approvers (and the requester) when an approval is created or decided."""

    type: Literal["approval.created", "approval.decided"]
    approval_id: uuid.UUID
    run_id: uuid.UUID
    chat_id: uuid.UUID
    tool: str
    status: Literal["pending", "approved", "rejected", "expired"]
    requested_by: uuid.UUID | None


def channel(tenant_id: uuid.UUID) -> str:
    return f"tenant:{tenant_id}:events"


async def publish(redis: Redis, tenant_id: uuid.UUID, event: BaseModel) -> None:
    await redis.publish(channel(tenant_id), event.model_dump_json())
