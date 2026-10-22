"""Live ingestion progress. Browsers can't send an Authorization header on a WebSocket, so the
first message carries the access token: {"type": "auth", "token": "..."}. Tokens never go in
the URL (where they'd end up in access logs)."""

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.auth.principal import Principal
from app.documents.progress import ProgressEvent, channel
from app.errors import AppError

log = logging.getLogger(__name__)
router = APIRouter()

AUTH_TIMEOUT_SECONDS = 5
POLICY_VIOLATION = 1008


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


@router.websocket("/api/ws/documents")
async def document_progress(websocket: WebSocket) -> None:
    await websocket.accept()
    auth = await _authenticate(websocket)
    if auth is None:
        await websocket.close(code=POLICY_VIOLATION, reason="Authentication required")
        return
    principal, expires_at = auth
    roles = set(principal.roles)
    await websocket.send_json({"type": "ready"})

    pubsub = websocket.app.state.redis.pubsub()
    await pubsub.subscribe(channel(principal.tenant_id))

    async def forward() -> None:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = ProgressEvent.model_validate_json(message["data"])
            except ValidationError:
                log.warning("ignoring malformed progress event")
                continue
            if roles & set(event.acl_roles):
                await websocket.send_text(event.model_dump_json(exclude={"acl_roles"}))

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
