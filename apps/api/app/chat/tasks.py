import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)


class TaskRegistry:
    """Keeps background runs referenced (asyncio only holds weak refs) and cancels them on
    shutdown so each can record a `server_shutdown` error."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coro: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def shutdown(self, grace_seconds: float = 10.0) -> None:
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        _, pending = await asyncio.wait(self._tasks, timeout=grace_seconds)
        if pending:
            log.warning("%d runs did not stop within %.0fs", len(pending), grace_seconds)

    async def drain(self, limit_seconds: float = 30.0) -> None:
        """Waits for every running task (tests). A task still running after `limit_seconds` is a
        bug; its stack is printed and the wait fails instead of hanging."""
        while self._tasks:
            _, pending = await asyncio.wait(set(self._tasks), timeout=limit_seconds)
            if pending:
                for task in pending:
                    task.print_stack()
                raise TimeoutError(f"{len(pending)} background runs did not finish")
