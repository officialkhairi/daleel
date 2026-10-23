"""Live notifications: ingestion progress and approval updates for the caller's tenant.

Browsers can't send an Authorization header on a WebSocket, so the first message carries the
access token: {"type": "auth", "token": "..."}. Tokens never go in the URL (where they'd end up
in access logs). Each event is forwarded only to viewers allowed to see it."""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.principal import Principal
from app.chat import repo
from app.db.session import tenant_session
from app.documents.progress import channel
from app.errors import AppError

log = logging.getLogger(__name__)
router = APIRouter()

AUTH_TIMEOUT_SECONDS = 5
POLICY_VIOLATION = 1008
APPROVERS = {"approver", "admin"}


async def _authenticate(websocket: WebSocket) -> tuple[Principal, float] | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS)
        message = json.loads(raw)
        token = message["token"] if message.get("type") == "auth" else None
        if not isinstance(token, str):
            return None
        claims = await websocket.app.state.verifier.verify(token)
        return Principal.from_claims(claims), float(claims["exp"])
    except (TimeoutError, ValueError, KeyError, AppError, WebSocketDisconnect):
        return None


def visible(event: dict[str, Any], roles: set[str], user_id: uuid.UUID) -> bool:
    kind = event.get("type")
    if kind == "document.progress":
        return bool(roles & set(event.get("acl_roles", [])))
    if kind in ("approval.created", "approval.decided"):
        return bool(roles & APPROVERS) or event.get("requested_by") == str(user_id)
    return False


@router.websocket("/api/ws")
@router.websocket("/api/ws/documents")  # Phase 3 path, kept for old clients
async def notifications(websocket: WebSocket) -> None:
    await websocket.accept()
    auth = await _authenticate(websocket)
    if auth is None:
        await websocket.close(code=POLICY_VIOLATION, reason="Authentication required")
        return
    principal, expires_at = auth
    roles: set[str] = set(principal.roles)
    async with tenant_session(websocket.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)

    pubsub = websocket.app.state.redis.pubsub()
    # Subscribe before announcing readiness, so nothing published after "ready" is missed.
    await pubsub.subscribe(channel(principal.tenant_id))
    await websocket.send_json({"type": "ready"})

    async def forward() -> None:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = json.loads(message["data"])
            except ValueError:
                log.warning("ignoring malformed notification")
                continue
            if isinstance(event, dict) and visible(event, roles, user_id):
                event.pop("acl_roles", None)
                await websocket.send_json(event)

    async def until_closed() -> None:
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await websocket.receive_text()

    tasks = [asyncio.create_task(forward()), asyncio.create_task(until_closed())]
    try:
        # The connection lives no longer than the token that opened it; the client reconnects
        # with a fresh one.
        await asyncio.wait(
            tasks, timeout=max(0.0, expires_at - time.time()), return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in tasks:
            task.cancel()
        await pubsub.unsubscribe()
        await pubsub.aclose()
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=POLICY_VIOLATION, reason="Token expired")
