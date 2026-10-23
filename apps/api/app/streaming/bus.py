"""Run events live in one Redis Stream per run. The generating task appends; any number of SSE
readers (on any API replica) replay from the start or from a Last-Event-ID. Stream entry ids
double as SSE event ids."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.streaming.events import TERMINAL_EVENT, StreamEvent


@dataclass(frozen=True)
class StoredEvent:
    id: str
    name: str
    data: str


class RunBus:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _events_key(run_id: uuid.UUID) -> str:
        return f"run:{run_id}:events"

    @staticmethod
    def _cancel_key(run_id: uuid.UUID) -> str:
        return f"run:{run_id}:cancel"

    async def publish(self, run_id: uuid.UUID, event: StreamEvent) -> str:
        key = self._events_key(run_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(key, {"event": event.name, "data": event.model_dump_json()})
            # Refreshed on every write, so an abandoned run's events still expire.
            pipe.expire(key, self._ttl)
            event_id, _ = await pipe.execute()
        return str(event_id)

    async def read(
        self, run_id: uuid.UUID, *, after: str = "0", block_ms: int = 15_000
    ) -> AsyncIterator[StoredEvent | None]:
        """Yields events after `after` until the terminal event. Yields None after `block_ms`
        of silence (callers send a heartbeat). Stops if the run's stream no longer exists."""
        key = self._events_key(run_id)
        cursor = after
        while True:
            response = await self._redis.xread({key: cursor}, count=100, block=block_ms)
            entries = _entries(response, key)
            if not entries:
                if not await self._redis.exists(key):
                    return
                yield None
                continue
            for entry_id, fields in entries:
                cursor = entry_id
                yield StoredEvent(id=entry_id, name=fields["event"], data=fields["data"])
                if fields["event"] == TERMINAL_EVENT:
                    return

    async def last_event_id(self, run_id: uuid.UUID) -> str | None:
        entries = await self._redis.xrevrange(self._events_key(run_id), count=1)
        return str(entries[0][0]) if entries else None

    async def has_events(self, run_id: uuid.UUID) -> bool:
        return bool(await self._redis.exists(self._events_key(run_id)))

    async def request_cancel(self, run_id: uuid.UUID) -> None:
        await self._redis.set(self._cancel_key(run_id), "1", ex=self._ttl)

    async def cancel_requested(self, run_id: uuid.UUID) -> bool:
        return bool(await self._redis.exists(self._cancel_key(run_id)))


def _entries(response: Any, key: str) -> list[tuple[str, dict[str, str]]]:
    """XREAD replies as {key: [entries]} under RESP3 and [[key, entries]] under RESP2."""
    if not response:
        return []
    raw = response.get(key, []) if isinstance(response, dict) else response[0][1]
    return [(str(entry_id), dict(fields)) for entry_id, fields in raw]
