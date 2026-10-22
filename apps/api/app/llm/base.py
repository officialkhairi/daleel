"""The single seam for every LLM call. Implementations arrive in Phase 2 (OpenAI-compatible,
Anthropic, and a FakeProvider for tests); this module fixes the contract they share."""

from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field


class TextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallDelta(BaseModel):
    type: Literal["tool_call_delta"] = "tool_call_delta"
    call_id: str
    name: str | None = None
    args_delta: str = ""


class ToolCallDone(BaseModel):
    type: Literal["tool_call_done"] = "tool_call_done"
    call_id: str
    name: str
    args: dict[str, Any]


class Usage(BaseModel):
    type: Literal["usage"] = "usage"
    tokens_in: int
    tokens_out: int


class Finish(BaseModel):
    type: Literal["finish"] = "finish"
    reason: Literal["stop", "tool_calls", "length", "error"]


LLMEvent = Annotated[
    TextDelta | ToolCallDelta | ToolCallDone | Usage | Finish,
    Field(discriminator="type"),
]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCallDone] | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema generated from the tool's Pydantic arg model


class LLMProvider(Protocol):
    # Declared without `async` so that async-generator implementations satisfy it.
    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        **opts: Any,
    ) -> AsyncIterator[LLMEvent]: ...
