import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.auth.deps import require
from app.auth.principal import Principal
from app.chat import repo
from app.chat.runner import Pricing, execute_run
from app.chat.service import start_run
from app.db.session import tenant_session
from app.errors import NotFound
from app.streaming.events import RunStarted
from app.streaming.sse import sse_response

router = APIRouter(prefix="/api/chats", tags=["chats"])

# Every role may chat; what a chat can reach (documents, tools) is restricted in later phases.
any_role = require("viewer", "editor", "approver", "admin")

Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class CreateChat(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class SendMessage(BaseModel):
    content: Content


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str = Field(description="Empty until the first message names the chat.")
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant", "tool"]
    content: str
    status: Literal["complete", "cancelled", "error"]
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    created_at: datetime


class ChatDetail(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]
    active_run_id: uuid.UUID | None = Field(
        description="Set while an answer is generating; resume it via /api/runs/{id}/events."
    )


@router.post("", status_code=201)
async def create(
    body: CreateChat, request: Request, principal: Principal = Depends(any_role)
) -> ChatOut:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        chat = await repo.create_chat(
            session, tenant_id=principal.tenant_id, user_id=user_id, title=body.title
        )
        return ChatOut.model_validate(chat)


@router.get("")
async def list_(request: Request, principal: Principal = Depends(any_role)) -> list[ChatOut]:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        return [ChatOut.model_validate(c) for c in await repo.list_chats(session, user_id)]


@router.get("/{chat_id}")
async def get(
    chat_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> ChatDetail:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        chat = await repo.get_chat(session, chat_id, user_id)
        if chat is None:
            raise NotFound("Chat not found.")
        messages = await repo.list_messages(session, chat.id)
        run = await repo.active_run(session, chat.id)
        return ChatDetail(
            chat=ChatOut.model_validate(chat),
            messages=[MessageOut.model_validate(m) for m in messages],
            active_run_id=run.id if run else None,
        )


@router.delete("/{chat_id}", status_code=204)
async def delete(
    chat_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> Response:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        chat = await repo.get_chat(session, chat_id, user_id)
        if chat is None:
            raise NotFound("Chat not found.")
        await repo.delete_chat(session, chat)
    return Response(status_code=204)


async def _run_and_stream(
    request: Request, principal: Principal, chat_id: uuid.UUID, content: str | None
) -> StreamingResponse:
    state = request.app.state
    started = await start_run(
        state.sessions,
        principal,
        chat_id,
        content=content,
        model=state.settings.llm_model,
        history_limit=state.settings.chat_history_limit,
    )
    spec = started.spec
    # Published before the task starts, so a reader never waits on an empty stream.
    await state.bus.publish(spec.run_id, RunStarted(run_id=spec.run_id, model=spec.model))
    state.tasks.spawn(
        execute_run(
            spec,
            provider=state.provider,
            bus=state.bus,
            sessions=state.sessions,
            pricing=Pricing(
                state.settings.llm_price_in_per_mtok, state.settings.llm_price_out_per_mtok
            ),
        ),
        name=f"run-{spec.run_id}",
    )
    return sse_response(state.bus, spec.run_id)


@router.post(
    "/{chat_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def send_message(
    chat_id: uuid.UUID,
    body: SendMessage,
    request: Request,
    principal: Principal = Depends(any_role),
) -> StreamingResponse:
    """Stores the message and streams the answer as server-sent events (see docs/PLAN.md)."""
    return await _run_and_stream(request, principal, chat_id, body.content)


@router.post(
    "/{chat_id}/retry",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def retry(
    chat_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> StreamingResponse:
    """Regenerates the answer to the chat's last question."""
    return await _run_and_stream(request, principal, chat_id, None)
