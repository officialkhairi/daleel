from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.errors import ServiceUnavailable

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness: the process is serving requests."""
    return HealthResponse()


@router.get("/readyz")
async def readyz(request: Request) -> HealthResponse:
    """Readiness: the database answers."""
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise ServiceUnavailable("Database is unavailable.", code="db_unavailable") from exc
    return HealthResponse()
