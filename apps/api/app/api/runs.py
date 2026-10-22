import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.chats import any_role
from app.auth.principal import Principal
from app.chat import repo
from app.db.session import tenant_session
from app.errors import AppError, Gone, NotFound
from app.streaming.sse import sse_response

router = APIRouter(prefix="/api/runs", tags=["runs"])

EVENT_ID = re.compile(r"^\d+-\d+$")


class BadEventId(AppError):
    status_code = 422
    code = "validation_error"


class RunOut(BaseModel):
    id: uuid.UUID
    status: Literal["running", "completed", "cancelled", "failed", "awaiting_approval"]


@router.get(
    "/{run_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def events(
    run_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_role),
    last_event_id: Annotated[str | None, Header()] = None,
    after: Annotated[str | None, Query(description="Same as the Last-Event-ID header.")] = None,
) -> StreamingResponse:
    """Replays a run's events after `Last-Event-ID` (or from the start), then follows live."""
    cursor = last_event_id or after or "0"
    if cursor != "0" and not EVENT_ID.match(cursor):
        raise BadEventId("Last-Event-ID is not an event id from this stream.")

    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        run = await repo.get_run(session, run_id, user_id)
    if run is None:
        raise NotFound("Run not found.")
    if not await request.app.state.bus.has_events(run_id):
        raise Gone("This answer's live events have expired. Reload the chat.")
    return sse_response(request.app.state.bus, run_id, after=cursor)


@router.post("/{run_id}/cancel", status_code=202)
async def cancel(
    run_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> RunOut:
    """Asks a running answer to stop. Idempotent; the stream ends with finish_reason=cancelled."""
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        run = await repo.get_run(session, run_id, user_id)
    if run is None:
        raise NotFound("Run not found.")
    if run.status == "running":
        await request.app.state.bus.request_cancel(run_id)
    return RunOut.model_validate({"id": run.id, "status": run.status})
