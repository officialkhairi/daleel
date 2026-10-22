"""Deterministic provider for tests, e2e and running the stack without a model."""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.llm.base import (
    ChatMessage,
    Finish,
    LLMError,
    LLMEvent,
    TextDelta,
    ToolCallDelta,
    ToolCallDone,
    ToolSpec,
    Usage,
)


class FakeError(BaseModel):
    """Scripted failure: raised as LLMError at this point in the turn."""

    type: Literal["fake_error"] = "fake_error"
    code: str = "llm_unavailable"
    message: str = "Scripted failure."
    retryable: bool = True


ScriptEvent = Annotated[
    TextDelta | ToolCallDelta | ToolCallDone | Usage | Finish | FakeError,
    Field(discriminator="type"),
]
_TURNS = TypeAdapter(list[list[ScriptEvent]])


def echo_turn(messages: Sequence[ChatMessage]) -> list[ScriptEvent]:
    """'You said: …' streamed word by word, with whitespace-count token usage."""
    last = next((m.content for m in reversed(messages) if m.role == "user"), "")
    words = f"You said: {last}".split(" ")
    events: list[ScriptEvent] = [
        TextDelta(text=w if i == len(words) - 1 else f"{w} ") for i, w in enumerate(words)
    ]
    tokens_in = sum(len(m.content.split()) for m in messages)
    return [*events, Usage(tokens_in=tokens_in, tokens_out=len(words)), Finish(reason="stop")]


class FakeProvider:
    """Each `stream()` call replays the next scripted turn; once the script runs out it echoes.
    `calls` records the messages of every call so tests can assert on the prompt."""

    def __init__(self, turns: list[list[ScriptEvent]] | None = None, *, delay: float = 0.0) -> None:
        self._turns = list(turns or [])
        self._delay = delay
        self.calls: list[list[ChatMessage]] = []

    @classmethod
    def from_file(cls, path: str | Path, *, delay: float = 0.0) -> "FakeProvider":
        data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(_TURNS.validate_python(data["turns"]), delay=delay)

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        **opts: Any,
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append(list(messages))
        turn = self._turns.pop(0) if self._turns else echo_turn(messages)
        for event in turn:
            if self._delay:
                await asyncio.sleep(self._delay)
            if isinstance(event, FakeError):
                raise LLMError(event.message, code=event.code, retryable=event.retryable)
            yield event
