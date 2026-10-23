"""Streaming client for any OpenAI-compatible /chat/completions endpoint (vLLM, Ollama, AI71,
OpenAI). The SSE stream is parsed by hand: `data: {chunk}` lines, terminated by `data: [DONE]`."""

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

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

_FINISH_REASONS: dict[str, Any] = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "length": "length",
}


def _to_wire(message: ChatMessage) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.args)},
            }
            for call in message.tool_calls
        ]
    return wire


@dataclass
class _PartialCall:
    call_id: str
    name: str = ""
    args: str = ""


async def parse_stream(lines: AsyncIterator[str]) -> AsyncIterator[LLMEvent]:
    """Turns the server's SSE lines into LLMEvents. Tool-call fragments are re-assembled by
    `index` and emitted as ToolCallDone once the stream ends."""
    calls: dict[int, _PartialCall] = {}
    finish: str | None = None

    async for line in lines:
        if not line.startswith("data:"):
            continue  # blank separators, comments, `event:` lines
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMError("Model server sent malformed data.", code="llm_bad_response") from exc

        if error := chunk.get("error"):
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise LLMError(f"Model error: {message}", code="llm_error")
        if usage := chunk.get("usage"):
            yield Usage(
                tokens_in=usage.get("prompt_tokens") or 0,
                tokens_out=usage.get("completion_tokens") or 0,
            )
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if text := delta.get("content"):
                yield TextDelta(text=text)
            for fragment in delta.get("tool_calls") or []:
                index = fragment.get("index", 0)
                part = calls.setdefault(index, _PartialCall(call_id=f"call_{index}"))
                function = fragment.get("function") or {}
                if fragment.get("id"):
                    part.call_id = fragment["id"]
                if function.get("name"):
                    part.name = function["name"]
                args = function.get("arguments") or ""
                part.args += args
                yield ToolCallDelta(
                    call_id=part.call_id, name=function.get("name"), args_delta=args
                )
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]

    for part in calls.values():
        try:
            args = json.loads(part.args or "{}")
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"Model produced invalid arguments for {part.name}.", code="llm_bad_tool_call"
            ) from exc
        yield ToolCallDone(call_id=part.call_id, name=part.name, args=args)
    yield Finish(reason=_FINISH_REASONS.get(finish or "stop", "stop"))


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        http: httpx.AsyncClient,
        timeout: float,
        stream_usage: bool = True,
        tool_mode: Literal["native", "json"] = "native",
    ) -> None:
        if not base_url:
            raise ValueError("LLM_BASE_URL is required for the openai_compat provider")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._api_key = api_key
        self._http = http
        self._timeout = httpx.Timeout(timeout, connect=10.0)
        self._stream_usage = stream_usage
        self._tool_mode = tool_mode

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        **opts: Any,
    ) -> AsyncIterator[LLMEvent]:
        if tools and self._tool_mode == "json":
            async for event in self._json_decision(messages, tools, **opts):
                yield event
            return
        body: dict[str, Any] = {
            "model": opts.get("model") or self._model,
            "messages": [_to_wire(m) for m in messages],
            "stream": True,
        }
        if self._stream_usage:
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = [{"type": "function", "function": t.model_dump()} for t in tools]
        for key in ("temperature", "max_tokens"):
            if key in opts:
                body[key] = opts[key]
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        try:
            async with self._http.stream(
                "POST", self._url, json=body, headers=headers, timeout=self._timeout
            ) as response:
                if response.status_code != httpx.codes.OK:
                    status = response.status_code
                    raise LLMError(
                        f"Model server returned HTTP {status}.",
                        code="llm_rate_limited" if status == 429 else "llm_unavailable",
                        retryable=status in (408, 409, 429) or status >= 500,
                    )
                async for event in parse_stream(response.aiter_lines()):
                    yield event
        except httpx.TimeoutException as exc:
            raise LLMError("Model server timed out.", code="llm_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                "Model server is unreachable.", code="llm_unavailable", retryable=True
            ) from exc

    # --- models without native tool calling ------------------------------------------------

    async def _json_decision(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec], **opts: Any
    ) -> AsyncIterator[LLMEvent]:
        """One non-streaming call whose output is constrained to a JSON decision (vLLM and
        Ollama honour `response_format` json_schema): answer, or call one tool."""
        names = [t.name for t in tools]
        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["answer", *names]},
                "arguments": {"type": "object"},
                "answer": {"type": "string"},
            },
            "required": ["action"],
        }
        catalog = "\n".join(
            f"- {t.name}: {t.description} Arguments (JSON Schema): {json.dumps(t.parameters)}"
            for t in tools
        )
        instructions = (
            "Reply with a JSON object only. To answer, use "
            '{"action": "answer", "answer": "<your answer>"}. To use a tool, use '
            '{"action": "<tool name>", "arguments": {...}}. Tools:\n' + catalog
        )
        wire = _flatten_tool_turns(messages)
        if wire and wire[0]["role"] == "system":
            wire[0] = {**wire[0], "content": f"{wire[0]['content']}\n\n{instructions}"}
        else:
            wire.insert(0, {"role": "system", "content": instructions})
        body: dict[str, Any] = {
            "model": opts.get("model") or self._model,
            "messages": wire,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "decision", "schema": schema},
            },
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = await self._http.post(
                self._url, json=body, headers=headers, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise LLMError("Model server timed out.", code="llm_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                "Model server is unreachable.", code="llm_unavailable", retryable=True
            ) from exc
        if response.status_code != httpx.codes.OK:
            status = response.status_code
            raise LLMError(
                f"Model server returned HTTP {status}.",
                code="llm_rate_limited" if status == 429 else "llm_unavailable",
                retryable=status in (408, 409, 429) or status >= 500,
            )
        payload = response.json()
        if usage := payload.get("usage"):
            yield Usage(
                tokens_in=usage.get("prompt_tokens") or 0,
                tokens_out=usage.get("completion_tokens") or 0,
            )
        content = (payload.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        try:
            decision = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(
                "Model did not return a JSON decision.", code="llm_bad_response"
            ) from exc
        action = decision.get("action")
        if action in names:
            arguments = decision.get("arguments")
            yield ToolCallDone(
                call_id=f"call_{uuid.uuid4().hex[:12]}",
                name=action,
                args=arguments if isinstance(arguments, dict) else {},
            )
            yield Finish(reason="tool_calls")
            return
        answer = str(decision.get("answer") or "")
        # No token stream in this mode; hand the answer over word by word.
        for i, word in enumerate(answer.split(" ")):
            yield TextDelta(text=word if i == 0 else f" {word}")
        yield Finish(reason="stop")


def _flatten_tool_turns(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Tool calls and results as plain turns, for servers that reject tool roles."""
    wire: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            wire.append(
                {"role": "user", "content": f"Tool result ({m.tool_call_id}):\n{m.content}"}
            )
        elif m.tool_calls:
            calls = [{"action": c.name, "arguments": c.args} for c in m.tool_calls]
            text = f"{m.content}\n" if m.content else ""
            wire.append({"role": "assistant", "content": text + json.dumps(calls)})
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire
