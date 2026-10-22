"""Chat queries. RLS already scopes every query to the tenant; ownership (user_id) is checked
here because chats are private to their author within a tenant."""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.db.models import Chat, Message, Run, User
from app.db.users import upsert_user

# A "running" run older than this is treated as abandoned (e.g. the API process died).
RUN_STALE_AFTER = timedelta(minutes=15)


async def ensure_user_id(session: AsyncSession, principal: Principal) -> uuid.UUID:
    user_id = await session.scalar(
        select(User.id).where(User.tenant_id == principal.tenant_id, User.oidc_sub == principal.sub)
    )
    return user_id if user_id is not None else await upsert_user(session, principal)


async def create_chat(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> Chat:
    chat = Chat(tenant_id=tenant_id, user_id=user_id, title=title)
    session.add(chat)
    await session.flush()
    await session.refresh(chat)
    return chat


async def list_chats(session: AsyncSession, user_id: uuid.UUID, limit: int = 50) -> Sequence[Chat]:
    result = await session.scalars(
        select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc()).limit(limit)
    )
    return result.all()


async def get_chat(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> Chat | None:
    stmt = select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def delete_chat(session: AsyncSession, chat: Chat) -> None:
    await session.delete(chat)


async def list_messages(
    session: AsyncSession, chat_id: uuid.UUID, *, limit: int | None = None
) -> Sequence[Message]:
    """Oldest first. With `limit`, the most recent `limit` messages."""
    stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.seq.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(reversed((await session.scalars(stmt)).all()))


async def last_user_message(session: AsyncSession, chat_id: uuid.UUID) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(Message.chat_id == chat_id, Message.role == "user")
        .order_by(Message.seq.desc())
        .limit(1)
    )


async def delete_messages_after(session: AsyncSession, message: Message) -> None:
    await session.execute(
        delete(Message).where(Message.chat_id == message.chat_id, Message.seq > message.seq)
    )


async def active_run(session: AsyncSession, chat_id: uuid.UUID) -> Run | None:
    """The chat's in-flight run, if any. Abandoned runs are marked failed on the way."""
    run = await session.scalar(
        select(Run).where(Run.chat_id == chat_id, Run.status == "running").limit(1)
    )
    if run is None:
        return None
    db_now = await session.scalar(select(func.now()))
    if db_now is not None and db_now - run.created_at > RUN_STALE_AFTER:
        await session.execute(
            update(Run)
            .where(Run.id == run.id)
            .values(status="failed", finished_at=func.now(), error={"code": "abandoned"})
        )
        return None
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID) -> Run | None:
    return await session.scalar(select(Run).where(Run.id == run_id, Run.user_id == user_id))
