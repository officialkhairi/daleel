import uuid
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from app.streaming.bus import RunBus
from app.streaming.events import HEARTBEAT, encode_sse


def sse_response(bus: RunBus, run_id: uuid.UUID, *, after: str = "0") -> StreamingResponse:
    """Streams a run's events from `after` to `run.completed`. Disconnecting stops only this
    reader; the run keeps going and can be resumed."""

    async def body() -> AsyncIterator[bytes]:
        async for event in bus.read(run_id, after=after):
            yield HEARTBEAT if event is None else encode_sse(event.id, event.name, event.data)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
