"""Ingestion progress: the worker publishes on a per-tenant Redis channel, the API relays it to
browsers over WebSocket (filtered by each viewer's roles)."""

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


def channel(tenant_id: uuid.UUID) -> str:
    return f"tenant:{tenant_id}:documents"


async def publish(redis: Redis, tenant_id: uuid.UUID, event: ProgressEvent) -> None:
    await redis.publish(channel(tenant_id), event.model_dump_json())
