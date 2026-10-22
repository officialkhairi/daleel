"""Starting runs. Everything that must be true before a run begins (ownership, one run per chat,
the user message stored) happens in one committed transaction; generation then runs in the
background."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.principal import Principal
from app.chat import repo
from app.chat.runner import SYSTEM_PROMPT, RunSpec
from app.db.models import Chat, Message, Run
from app.db.session import tenant_session
from app.errors import AppError, NotFound
from app.llm.base import ChatMessage

TITLE_LENGTH = 60


class RunInProgress(AppError):
    status_code = 409
    code = "run_in_progress"


class NothingToRetry(AppError):
    status_code = 409
    code = "nothing_to_retry"


@dataclass(frozen=True)
class StartedRun:
    spec: RunSpec
    user_message_id: uuid.UUID


def _history(messages: list[Message]) -> list[ChatMessage]:
    turns = [
        ChatMessage(role="user" if m.role == "user" else "assistant", content=m.content)
        for m in messages
        if m.role in ("user", "assistant") and m.content
    ]
    return [ChatMessage(role="system", content=SYSTEM_PROMPT), *turns]


async def _locked_chat(session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID) -> Chat:
    chat = await repo.get_chat(session, chat_id, user_id, lock=True)
    if chat is None:
        raise NotFound("Chat not found.")
    if await repo.active_run(session, chat.id) is not None:
        raise RunInProgress("This chat is already answering. Wait for it or stop it first.")
    return chat


async def start_run(
    sessions: async_sessionmaker[AsyncSession],
    principal: Principal,
    chat_id: uuid.UUID,
    *,
    content: str | None,
    model: str,
    history_limit: int,
) -> StartedRun:
    """`content` sends a new user message; None retries the last one (dropping the answers
    after it)."""
    async with tenant_session(sessions, principal.tenant_id) as session:
        user_id = await repo.ensure_user_id(session, principal)
        chat = await _locked_chat(session, chat_id, user_id)

        if content is not None:
            user_message = Message(
                tenant_id=principal.tenant_id, chat_id=chat.id, role="user", content=content
            )
            session.add(user_message)
            if not chat.title:
                chat.title = content[:TITLE_LENGTH].strip()
            await session.flush()
        else:
            last = await repo.last_user_message(session, chat.id)
            if last is None:
                raise NothingToRetry("There is no question to retry.")
            await repo.delete_messages_after(session, last)
            user_message = last

        run = Run(
            tenant_id=principal.tenant_id,
            chat_id=chat.id,
            user_id=user_id,
            user_message_id=user_message.id,
            model=model,
        )
        session.add(run)
        await session.flush()
        history = await repo.list_messages(session, chat.id, limit=history_limit)

    spec = RunSpec(
        run_id=run.id,
        chat_id=chat.id,
        tenant_id=principal.tenant_id,
        model=model,
        history=_history(list(history)),
    )
    return StartedRun(spec=spec, user_message_id=user_message.id)
