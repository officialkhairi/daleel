from fastapi import APIRouter, Depends

from app.api.health import HealthResponse
from app.auth.deps import require

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require("admin"))])


@router.get("/ping")
async def ping() -> HealthResponse:
    """Smallest admin-only endpoint; exists to prove RBAC end to end."""
    return HealthResponse()
