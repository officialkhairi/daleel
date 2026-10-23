"""Deterministic provider for tests, e2e and running the stack without a model."""

import asyncio
import html
import json
import re
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.chat.language import strip_reply_note
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


_FIRST_SOURCE = re.compile(r'<source n="1"[^>]*>\n(.*?)\n</source>', re.DOTALL)
_EMAIL_INTENT = re.compile(r"\b(e-?mail|remind(er)?|notify)\b|بريد|ذك[ّ]?ر|تذكير", re.IGNORECASE)
_TICKET_INTENT = re.compile(r"\bticket\b|تذكرة", re.IGNORECASE)


def _words(text: str) -> list[ScriptEvent]:
    words = text.split(" ")
    return [TextDelta(text=w if i == len(words) - 1 else f"{w} ") for i, w in enumerate(words)]


def echo_turn(messages: Sequence[ChatMessage], tools: Sequence[ToolSpec] = ()) -> list[ScriptEvent]:
    """A tiny deterministic "agent" for demos and e2e tests, no model needed:

    - after a tool result, it reports it;
    - asked to email or remind someone, it proposes send_email (needs approval);
    - asked for a ticket, it proposes create_ticket (needs approval);
    - with sources in the prompt, it quotes source 1 and cites it;
    - otherwise it echoes: "You said: …".
    """
    last = messages[-1] if messages else ChatMessage(role="user", content="")
    question = strip_reply_note(
        next((m.content for m in reversed(messages) if m.role == "user"), "")
    )
    source = _FIRST_SOURCE.search(messages[0].content) if messages else None
    excerpt = " ".join(html.unescape(source.group(1)).split()[:24]) if source else ""
    available = {t.name for t in tools}
    tokens_in = sum(len(m.content.split()) for m in messages)
    events: list[ScriptEvent]

    if last.role == "tool":
        events = _words(f"Update: {last.content}")
    elif "send_email" in available and _EMAIL_INTENT.search(question):
        body = (
            f"Hello,\n\nA reminder from the procurement policy: {excerpt or question}\n\nThank you."
        )
        events = [
            *_words("I've drafted the email below; it will be sent once it is approved."),
            ToolCallDone(
                call_id="call_send_email",
                name="send_email",
                args={
                    "to": ["procurement@acme.example"],
                    "subject": "Reminder: contract approval thresholds",
                    "body": body,
                },
            ),
        ]
    elif "create_ticket" in available and _TICKET_INTENT.search(question):
        events = [
            *_words("I've prepared a ticket; it will be opened once it is approved."),
            ToolCallDone(
                call_id="call_create_ticket",
                name="create_ticket",
                args={"title": question[:80], "body": excerpt or question, "priority": "medium"},
            ),
        ]
    elif excerpt:
        events = _words(f"From the documents: {excerpt} [1]")
    else:
        events = _words(f"You said: {question}")
    finish = "tool_calls" if any(isinstance(e, ToolCallDone) for e in events) else "stop"
    return [*events, Usage(tokens_in=tokens_in, tokens_out=len(events)), Finish(reason=finish)]


class FakeProvider:
    """Each `stream()` call replays the next scripted turn; once the script runs out it echoes.
    `calls` records the messages of every call so tests can assert on the prompt."""

    def __init__(self, turns: list[list[ScriptEvent]] | None = None, *, delay: float = 0.0) -> None:
        self._turns = list(turns or [])
        self._delay = delay
        self.calls: list[list[ChatMessage]] = []
        self.tools_seen: list[list[str]] = []

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
        self.tools_seen.append([t.name for t in tools])
        turn = self._turns.pop(0) if self._turns else echo_turn(messages, tools)
        for event in turn:
            if self._delay:
                await asyncio.sleep(self._delay)
            if isinstance(event, FakeError):
                raise LLMError(event.message, code=event.code, retryable=event.retryable)
            yield event
