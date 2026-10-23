import json
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis

from app.config import Settings
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
from app.llm.factory import build_provider
from app.llm.fake import FakeProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.streaming.bus import RunBus
from app.streaming.events import Token

BASE = "http://llm.test/v1"
USER = [ChatMessage(role="user", content="hi")]


def sse(*chunks: dict[str, Any] | str) -> bytes:
    lines = [f"data: {c if isinstance(c, str) else json.dumps(c)}\n\n" for c in chunks]
    return "".join(lines).encode()


def delta(**fields: Any) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": None}]}


def finish(reason: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


Handler = Callable[[httpx.Request], httpx.Response]


async def collect(
    handler: Handler,
    *,
    tools: list[ToolSpec] | None = None,
    api_key: str = "sk-test",
    stream_usage: bool = True,
    **opts: Any,
) -> list[LLMEvent]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenAICompatProvider(
            base_url=BASE,
            model="falcon3:1b",
            api_key=api_key,
            http=http,
            timeout=5,
            stream_usage=stream_usage,
        )
        return [e async for e in provider.stream(USER, tools or [], **opts)]


async def test_streams_text_usage_and_finish() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = sse(
            delta(role="assistant", content=""),
            delta(content="مرحبا"),
            delta(content=" world"),
            finish("stop"),
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
            "[DONE]",
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    events = await collect(handler, temperature=0.2)

    assert events == [
        TextDelta(text="مرحبا"),
        TextDelta(text=" world"),
        Usage(tokens_in=7, tokens_out=2),
        Finish(reason="stop"),
    ]
    request = seen[0]
    assert str(request.url) == f"{BASE}/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    payload = json.loads(request.content)
    assert payload == {
        "model": "falcon3:1b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.2,
    }


async def test_options_off_and_no_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=sse(finish("length"), "[DONE]"))

    events = await collect(handler, api_key="", stream_usage=False, model="other")
    assert events == [Finish(reason="length")]
    assert "authorization" not in seen[0].headers
    payload = json.loads(seen[0].content)
    assert "stream_options" not in payload
    assert payload["model"] == "other"


async def test_reassembles_tool_calls() -> None:
    tool = ToolSpec(name="search_documents", description="Search", parameters={"type": "object"})
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        first = {
            "index": 0,
            "id": "call_1",
            "function": {"name": "search_documents", "arguments": ""},
        }
        body = sse(
            delta(tool_calls=[first]),
            delta(tool_calls=[{"index": 0, "function": {"arguments": '{"query": "thr'}}]),
            delta(tool_calls=[{"index": 0, "function": {"arguments": 'eshold"}'}}]),
            finish("tool_calls"),
            "[DONE]",
        )
        return httpx.Response(200, content=body)

    events = await collect(handler, tools=[tool])

    assert next(e for e in events if isinstance(e, ToolCallDelta)).name == "search_documents"
    assert events[-2:] == [
        ToolCallDone(call_id="call_1", name="search_documents", args={"query": "threshold"}),
        Finish(reason="tool_calls"),
    ]
    assert json.loads(seen[0].content)["tools"] == [
        {"type": "function", "function": tool.model_dump()}
    ]


async def test_sends_tool_history_in_wire_format() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=sse("[DONE]"))

    call = ToolCallDone(call_id="c1", name="search_documents", args={"query": "x"})
    messages = [
        ChatMessage(role="assistant", content="", tool_calls=[call]),
        ChatMessage(role="tool", content="result", tool_call_id="c1"),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenAICompatProvider(base_url=BASE, model="m", api_key="", http=http, timeout=5)
        assert [e async for e in provider.stream(messages, [])] == [Finish(reason="stop")]

    wire = json.loads(seen[0].content)["messages"]
    assert wire[0]["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "search_documents", "arguments": '{"query": "x"}'},
        }
    ]
    assert wire[1] == {"role": "tool", "content": "result", "tool_call_id": "c1"}


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (429, "llm_rate_limited", True),
        (503, "llm_unavailable", True),
        (400, "llm_unavailable", False),
        (401, "llm_unavailable", False),
    ],
)
async def test_http_errors_are_classified(status: int, code: str, retryable: bool) -> None:
    with pytest.raises(LLMError) as exc:
        await collect(lambda _: httpx.Response(status, json={"error": "nope"}))
    assert (exc.value.code, exc.value.retryable) == (code, retryable)


async def test_unreachable_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError) as exc:
        await collect(handler)
    assert exc.value.code == "llm_unavailable"
    assert exc.value.retryable


async def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError) as exc:
        await collect(handler)
    assert exc.value.code == "llm_timeout"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (sse({"error": {"message": "context too long"}}), "llm_error"),
        (b"data: {not json\n\n", "llm_bad_response"),
        (
            sse(delta(tool_calls=[{"index": 0, "function": {"name": "f", "arguments": "{"}}])),
            "llm_bad_tool_call",
        ),
    ],
)
async def test_bad_streams(body: bytes, code: str) -> None:
    with pytest.raises(LLMError) as exc:
        await collect(lambda _: httpx.Response(200, content=body))
    assert exc.value.code == code


async def test_missing_finish_reason_defaults_to_stop() -> None:
    events = await collect(lambda _: httpx.Response(200, content=sse(delta(content="x"))))
    assert events == [TextDelta(text="x"), Finish(reason="stop")]


def test_requires_base_url() -> None:
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        OpenAICompatProvider(
            base_url="", model="m", api_key="", http=httpx.AsyncClient(), timeout=1
        )


async def test_fake_provider_replays_script_then_echoes(tmp_path: Path) -> None:
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            {
                "turns": [
                    [
                        {"type": "text_delta", "text": "scripted"},
                        {"type": "finish", "reason": "stop"},
                    ],
                    [{"type": "fake_error", "code": "llm_timeout"}],
                ]
            }
        )
    )
    provider = FakeProvider.from_file(script)

    async def run() -> list[LLMEvent]:
        return [e async for e in provider.stream(USER, [])]

    assert await run() == [TextDelta(text="scripted"), Finish(reason="stop")]
    with pytest.raises(LLMError, match="Scripted failure"):
        await run()
    echoed = await run()
    assert "".join(e.text for e in echoed if isinstance(e, TextDelta)) == "You said: hi"


async def test_factory(settings: Settings) -> None:
    async with httpx.AsyncClient() as http:
        assert isinstance(build_provider(settings, http), FakeProvider)
        compat = settings.model_copy(update={"llm_provider": "openai_compat", "llm_base_url": BASE})
        assert isinstance(build_provider(compat, http), OpenAICompatProvider)


@pytest.fixture
async def bus(settings: Settings) -> AsyncIterator[RunBus]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    yield RunBus(redis, ttl_seconds=60)
    await redis.aclose()


async def test_bus_heartbeats_while_idle_and_stops_when_gone(bus: RunBus) -> None:
    run_id = uuid.uuid4()
    await bus.publish(run_id, Token(text="a"))
    reader = bus.read(run_id, block_ms=50)

    first = await anext(reader)
    assert first is not None
    assert first.name == "token"
    assert await anext(reader) is None  # idle: heartbeat

    await bus._redis.delete(f"run:{run_id}:events")
    with pytest.raises(StopAsyncIteration):
        await anext(reader)


async def json_mode(
    content: str, messages: list[ChatMessage] | None = None
) -> tuple[list[LLMEvent], dict[str, Any]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 9},
            },
        )

    tool = ToolSpec(name="send_email", description="Send", parameters={"type": "object"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenAICompatProvider(
            base_url=BASE, model="falcon3:1b", api_key="", http=http, timeout=5, tool_mode="json"
        )
        events = [
            e
            async for e in provider.stream(
                messages or [ChatMessage(role="system", content="Be brief."), *USER], [tool]
            )
        ]
    return events, json.loads(seen[0].content)


async def test_json_mode_turns_a_decision_into_a_tool_call() -> None:
    events, body = await json_mode('{"action": "send_email", "arguments": {"to": ["a@b.c"]}}')
    assert isinstance(events[1], ToolCallDone)
    assert (events[1].name, events[1].args) == ("send_email", {"to": ["a@b.c"]})
    assert events[0] == Usage(tokens_in=50, tokens_out=9)
    assert events[-1] == Finish(reason="tool_calls")
    assert body["stream"] is False
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["action"]["enum"] == ["answer", "send_email"]
    assert body["messages"][0]["content"].startswith("Be brief.\n\nReply with a JSON object only.")


async def test_json_mode_answers_word_by_word() -> None:
    events, _ = await json_mode('{"action": "answer", "answer": "Fifty thousand AED."}')
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Fifty", " thousand", " AED."]
    assert events[-1] == Finish(reason="stop")


async def test_json_mode_rejects_non_json() -> None:
    with pytest.raises(LLMError) as exc:
        await json_mode("I think you should email them")
    assert exc.value.code == "llm_bad_response"


async def test_json_mode_flattens_tool_turns() -> None:
    call = ToolCallDone(call_id="c1", name="send_email", args={"to": ["a@b.c"]})
    _, body = await json_mode(
        '{"action": "answer", "answer": "Done."}',
        [
            ChatMessage(role="user", content="email them"),
            ChatMessage(role="assistant", content="Drafted.", tool_calls=[call]),
            ChatMessage(role="tool", content="The email was sent.", tool_call_id="c1"),
        ],
    )
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert (
        body["messages"][2]["content"]
        == 'Drafted.\n[{"action": "send_email", "arguments": {"to": ["a@b.c"]}}]'
    )
    assert body["messages"][3]["content"] == "Tool result (c1):\nThe email was sent."


async def test_falls_back_to_json_mode_when_the_model_has_no_tools() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body["stream"]:
            return httpx.Response(
                400, json={"error": {"message": "falcon3:1b does not support tools"}}
            )
        content = '{"action": "answer", "answer": "Done."}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    tool = ToolSpec(name="send_email", description="Send", parameters={"type": "object"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenAICompatProvider(
            base_url=BASE, model="falcon3:1b", api_key="", http=http, timeout=5
        )
        first = [e async for e in provider.stream(USER, [tool])]
        second = [e async for e in provider.stream(USER, [tool])]

    assert [e for e in first if isinstance(e, TextDelta)] == [TextDelta(text="Done.")]
    assert second == first
    # One native attempt, then JSON mode for this turn and every later one.
    assert [b["stream"] for b in seen] == [True, False, False]
