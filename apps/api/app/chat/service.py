"""Starting runs. Everything that must be true before a run begins (ownership, one run per chat,
the user message stored) happens in one committed transaction; generation then runs in the
background."""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import audit
from app.agent.loop import RunSpec
from app.auth.principal import Principal
from app.chat import repo
from app.chat.language import Language, detect_language, reply_note, system_prompt
from app.db.models import Approval, Chat, Message, Run
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


_CITATION_MARKS = re.compile(r"\s?\[\d{1,2}\]")


def _history(messages: list[Message], language: Language) -> list[ChatMessage]:
    # Earlier answers' [n] markers point at sources this turn's prompt doesn't have.
    turns = [
        ChatMessage(role="user", content=m.content)
        if m.role == "user"
        else ChatMessage(role="assistant", content=_CITATION_MARKS.sub("", m.content))
        for m in messages
        if m.role in ("user", "assistant") and m.content
    ]
    if turns and turns[-1].role == "user":
        question = turns[-1]
        turns[-1] = question.model_copy(
            update={"content": f"{question.content}\n\n{reply_note(language)}"}
        )
    return [ChatMessage(role="system", content=system_prompt(language)), *turns]


def _reply_language(question: str, principal: Principal) -> Language:
    """The language of the question being answered, not of the UI or earlier turns."""
    return detect_language(question, fallback="ar" if principal.locale == "ar" else "en")


async def _supersede_pending_approvals(
    session: AsyncSession, chat: Chat, principal: Principal, user_id: uuid.UUID
) -> None:
    """A new question moves the conversation on: actions still waiting for approval from an
    earlier answer won't be carried out."""
    paused = (
        await session.scalars(
            select(Run).where(Run.chat_id == chat.id, Run.status == "awaiting_approval")
        )
    ).all()
    for run in paused:
        approvals = (
            await session.scalars(
                select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")
            )
        ).all()
        for approval in approvals:
            approval.status = "expired"
            approval.reason = "Superseded by a newer question."
            approval.decided_at = func.now()
            await audit.record(
                session,
                tenant_id=principal.tenant_id,
                actor_id=user_id,
                actor=principal.username,
                action="approval.superseded",
                target_type="approval",
                target_id=approval.id,
                details={"tool": approval.tool},
            )
        run.status = "cancelled"
        run.finished_at = func.now()


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
        await _supersede_pending_approvals(session, chat, principal, user_id)

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

    language = _reply_language(user_message.content, principal)
    spec = RunSpec(
        run_id=run.id,
        chat_id=chat.id,
        tenant_id=principal.tenant_id,
        user_id=user_id,
        username=principal.username,
        roles=frozenset(principal.roles),
        model=model,
        history=_history(list(history), language),
        question=user_message.content,
        language=language,
    )
    return StartedRun(spec=spec, user_message_id=user_message.id)
