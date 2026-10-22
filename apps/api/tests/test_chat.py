"""End-to-end chat behaviour over the SSE protocol, driven by FakeProvider scripts."""

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.llm.base import Finish, TextDelta, Usage
from app.llm.fake import FakeError, FakeProvider
from tests.conftest import TokenFactory

Event = tuple[str | None, str, dict[str, Any]]


def parse_sse(body: str) -> list[Event]:
    events: list[Event] = []
    for block in body.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if line.startswith(":") or not line:
                continue
            name, _, value = line.partition(": ")
            fields[name] = value
        if fields:
            events.append((fields.get("id"), fields["event"], json.loads(fields["data"])))
    return events


def names(events: list[Event]) -> list[str]:
    return [name for _, name, _ in events]


def text_of(events: list[Event]) -> str:
    return "".join(data["text"] for _, name, data in events if name == "token")


@pytest.fixture
def headers(make_token: TokenFactory) -> dict[str, str]:
    """One user for the whole test."""
    return {"Authorization": f"Bearer {make_token(sub=f'user-{uuid.uuid4()}')}"}


async def new_chat(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/api/chats", json={}, headers=headers)
    assert response.status_code == 201
    chat_id: str = response.json()["id"]
    return chat_id


async def send(
    client: httpx.AsyncClient, headers: dict[str, str], chat_id: str, content: str
) -> list[Event]:
    response = await client.post(
        f"/api/chats/{chat_id}/messages", json={"content": content}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def wait_for_active_run(
    client: httpx.AsyncClient, headers: dict[str, str], chat_id: str
) -> str:
    for _ in range(100):
        detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
        if detail["active_run_id"]:
            run_id: str = detail["active_run_id"]
            return run_id
        await asyncio.sleep(0.02)
    raise AssertionError("run never started")


def slow_turn(words: int) -> list[Any]:
    return [TextDelta(text=f"w{i} ") for i in range(words)] + [Finish(reason="stop")]


async def test_streams_answer_and_persists_it(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    chat_id = await new_chat(client, headers)
    events = await send(client, headers, chat_id, "Hello there")

    assert names(events)[0] == "run.started"
    assert names(events)[-2:] == ["usage", "run.completed"]
    assert set(names(events)[1:-2]) == {"token"}
    assert text_of(events) == "You said: Hello there"
    assert all(event_id for event_id, _, _ in events)
    completed = events[-1][2]
    assert completed["finish_reason"] == "stop"

    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert detail["chat"]["title"] == "Hello there"
    assert detail["active_run_id"] is None
    assert [(m["role"], m["content"], m["status"]) for m in detail["messages"]] == [
        ("user", "Hello there", "complete"),
        ("assistant", "You said: Hello there", "complete"),
    ]
    assert detail["messages"][1]["id"] == completed["message_id"]


async def test_usage_event_prices_tokens(
    app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider
) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"llm_price_in_per_mtok": 2.0, "llm_price_out_per_mtok": 6.0}
    )
    provider._turns = [
        [TextDelta(text="ok"), Usage(tokens_in=1000, tokens_out=500), Finish(reason="stop")]
    ]
    events = await send(client, headers, await new_chat(client, headers), "price?")
    usage = next(data for _, name, data in events if name == "usage")
    assert usage == {"tokens_in": 1000, "tokens_out": 500, "cost_usd": 0.005}


async def test_model_sees_system_prompt_and_history(
    client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider
) -> None:
    chat_id = await new_chat(client, headers)
    await send(client, headers, chat_id, "first")
    await send(client, headers, chat_id, "second")

    prompt = provider.calls[1]
    assert prompt[0].role == "system"
    assert [(m.role, m.content) for m in prompt[1:]] == [
        ("user", "first"),
        ("assistant", "You said: first"),
        ("user", "second\n\n(Reply in English.)"),
    ]


async def test_provider_error_before_any_text(
    client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider
) -> None:
    provider._turns = [[FakeError(code="llm_unavailable", message="down", retryable=True)]]
    chat_id = await new_chat(client, headers)
    events = await send(client, headers, chat_id, "hi")

    assert names(events) == ["run.started", "error", "run.completed"]
    assert events[1][2] == {"code": "llm_unavailable", "message": "down", "retryable": True}
    assert events[2][2] == {"message_id": None, "finish_reason": "error"}
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert [m["role"] for m in detail["messages"]] == ["user"]


async def test_error_mid_stream_keeps_partial_answer(
    client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider
) -> None:
    provider._turns = [[TextDelta(text="Partial "), FakeError()]]
    chat_id = await new_chat(client, headers)
    events = await send(client, headers, chat_id, "hi")

    assert names(events) == ["run.started", "token", "error", "run.completed"]
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert (detail["messages"][1]["content"], detail["messages"][1]["status"]) == (
        "Partial ",
        "error",
    )


async def test_retry_regenerates_last_answer(
    client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider
) -> None:
    provider._turns = [
        [TextDelta(text="first try"), Finish(reason="stop")],
        [TextDelta(text="second try"), Finish(reason="stop")],
    ]
    chat_id = await new_chat(client, headers)
    await send(client, headers, chat_id, "question")

    response = await client.post(f"/api/chats/{chat_id}/retry", headers=headers)
    assert text_of(parse_sse(response.text)) == "second try"
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "question"),
        ("assistant", "second try"),
    ]
    # The retry prompt ends at the question; the discarded answer is not in it.
    assert [m.content for m in provider.calls[1][1:]] == ["question\n\n(Reply in English.)"]


async def test_retry_without_question_is_409(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    chat_id = await new_chat(client, headers)
    response = await client.post(f"/api/chats/{chat_id}/retry", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "nothing_to_retry"


async def test_resume_from_last_event_id(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    chat_id = await new_chat(client, headers)
    events = await send(client, headers, chat_id, "one two three")
    run_id = events[0][2]["run_id"]
    seen_up_to = events[2][0]
    assert seen_up_to is not None

    response = await client.get(
        f"/api/runs/{run_id}/events", headers={**headers, "Last-Event-ID": seen_up_to}
    )
    assert parse_sse(response.text) == events[3:]

    replay = await client.get(f"/api/runs/{run_id}/events", headers=headers)
    assert parse_sse(replay.text) == events


async def test_cancel_stops_generation_and_keeps_partial(
    app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    app.state.provider = FakeProvider([slow_turn(200)], delay=0.01)
    chat_id = await new_chat(client, headers)
    stream = asyncio.create_task(send(client, headers, chat_id, "long please"))
    run_id = await wait_for_active_run(client, headers, chat_id)

    response = await client.post(f"/api/runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 202
    events = await stream

    assert events[-1][2]["finish_reason"] == "cancelled"
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    answer = detail["messages"][1]
    assert answer["status"] == "cancelled"
    assert 0 < len(answer["content"]) < len("w0 " * 200)
    assert answer["content"] == text_of(events)

    again = await client.post(f"/api/runs/{run_id}/cancel", headers=headers)
    assert again.json()["status"] == "cancelled"


async def test_one_run_per_chat(
    app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    app.state.provider = FakeProvider([slow_turn(200)], delay=0.01)
    chat_id = await new_chat(client, headers)
    stream = asyncio.create_task(send(client, headers, chat_id, "first"))
    run_id = await wait_for_active_run(client, headers, chat_id)

    second = await client.post(
        f"/api/chats/{chat_id}/messages", json={"content": "second"}, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["code"] == "run_in_progress"

    await client.post(f"/api/runs/{run_id}/cancel", headers=headers)
    await stream


async def test_chats_are_private_to_their_owner(
    client: httpx.AsyncClient, headers: dict[str, str], make_token: TokenFactory
) -> None:
    chat_id = await new_chat(client, headers)
    events = await send(client, headers, chat_id, "mine")
    run_id = events[0][2]["run_id"]
    other = {"Authorization": f"Bearer {make_token(sub='someone-else', roles=['admin'])}"}

    assert (await client.get(f"/api/chats/{chat_id}", headers=other)).status_code == 404
    send_other = await client.post(
        f"/api/chats/{chat_id}/messages", json={"content": "x"}, headers=other
    )
    assert send_other.status_code == 404
    assert (await client.get(f"/api/runs/{run_id}/events", headers=other)).status_code == 404
    assert (await client.post(f"/api/runs/{run_id}/cancel", headers=other)).status_code == 404
    assert (await client.delete(f"/api/chats/{chat_id}", headers=other)).status_code == 404
    assert chat_id not in [c["id"] for c in (await client.get("/api/chats", headers=other)).json()]


async def test_other_tenant_cannot_see_chat(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    sub = f"user-{uuid.uuid4()}"
    acme = {"Authorization": f"Bearer {make_token(sub=sub, tenant='acme')}"}
    globex = {"Authorization": f"Bearer {make_token(sub=sub, tenant='globex')}"}
    chat_id = await new_chat(client, acme)
    assert (await client.get(f"/api/chats/{chat_id}", headers=globex)).status_code == 404


async def test_list_and_delete(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    older = await new_chat(client, headers)
    newer = await new_chat(client, headers)
    await send(client, headers, older, "bump")  # answering moves a chat to the top

    listed = [c["id"] for c in (await client.get("/api/chats", headers=headers)).json()]
    assert listed == [older, newer]

    assert (await client.delete(f"/api/chats/{older}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/chats/{older}", headers=headers)).status_code == 404


async def test_viewer_can_chat(client: httpx.AsyncClient, make_token: TokenFactory) -> None:
    viewer = {"Authorization": f"Bearer {make_token(sub='a-viewer', roles=['viewer'])}"}
    events = await send(client, viewer, await new_chat(client, viewer), "hi")
    assert events[-1][2]["finish_reason"] == "stop"


async def test_no_role_cannot_chat(client: httpx.AsyncClient, make_token: TokenFactory) -> None:
    nobody = {"Authorization": f"Bearer {make_token(roles=[])}"}
    assert (await client.post("/api/chats", json={}, headers=nobody)).status_code == 403


@pytest.mark.parametrize("content", ["", "   ", "x" * 8001])
async def test_rejects_bad_content(
    client: httpx.AsyncClient, headers: dict[str, str], content: str
) -> None:
    chat_id = await new_chat(client, headers)
    response = await client.post(
        f"/api/chats/{chat_id}/messages", json={"content": content}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_unknown_chat_is_404(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await client.post(
        f"/api/chats/{uuid.uuid4()}/messages", json={"content": "hi"}, headers=headers
    )
    assert response.status_code == 404


async def test_bad_last_event_id_is_422(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    events = await send(client, headers, await new_chat(client, headers), "hi")
    run_id = events[0][2]["run_id"]
    response = await client.get(
        f"/api/runs/{run_id}/events", headers={**headers, "Last-Event-ID": "nonsense"}
    )
    assert response.status_code == 422


async def test_expired_events_are_410(
    app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    events = await send(client, headers, await new_chat(client, headers), "hi")
    run_id = events[0][2]["run_id"]
    await app.state.bus._redis.delete(f"run:{run_id}:events")
    response = await client.get(f"/api/runs/{run_id}/events", headers=headers)
    assert response.status_code == 410


async def test_shutdown_mid_answer_records_retryable_error(
    app: FastAPI, client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    app.state.provider = FakeProvider([slow_turn(200)], delay=0.01)
    chat_id = await new_chat(client, headers)
    stream = asyncio.create_task(send(client, headers, chat_id, "long"))
    await wait_for_active_run(client, headers, chat_id)
    await asyncio.sleep(0.2)  # let some text stream so there is a partial answer to keep

    await app.state.tasks.shutdown()
    events = await stream

    assert names(events)[-2:] == ["error", "run.completed"]
    assert events[-2][2]["code"] == "server_shutdown"
    assert events[-2][2]["retryable"] is True
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert detail["active_run_id"] is None
    assert detail["messages"][1]["status"] == "error"


@pytest.mark.parametrize(
    "turn", [[Finish(reason="stop")], [TextDelta(text=" \n "), Finish(reason="stop")]]
)
async def test_empty_answer_is_a_retryable_error(
    client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider, turn: list[Any]
) -> None:
    provider._turns = [turn]
    chat_id = await new_chat(client, headers)
    events = await send(client, headers, chat_id, "hi")

    error = next(data for _, name, data in events if name == "error")
    assert error == {
        "code": "empty_answer",
        "message": "The model returned an empty answer.",
        "retryable": True,
    }
    assert events[-1][2] == {"message_id": None, "finish_reason": "error"}
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert [m["role"] for m in detail["messages"]] == ["user"]


async def test_reply_language_follows_the_question_not_the_history(
    client: httpx.AsyncClient, headers: dict[str, str], provider: FakeProvider
) -> None:
    chat_id = await new_chat(client, headers)
    await send(client, headers, chat_id, "مرحبا")
    await send(client, headers, chat_id, "hello")

    assert "أجب باللغة العربية" in provider.calls[0][0].content
    assert "Reply in English." in provider.calls[1][0].content
    # The latest question carries the note in the prompt; earlier turns and the stored text don't.
    assert provider.calls[1][-1].content == "hello\n\n(Reply in English.)"
    assert provider.calls[1][1].content == "مرحبا"
    detail = (await client.get(f"/api/chats/{chat_id}", headers=headers)).json()
    assert [m["content"] for m in detail["messages"] if m["role"] == "user"] == ["مرحبا", "hello"]


async def test_reply_language_falls_back_to_user_locale(
    client: httpx.AsyncClient, make_token: TokenFactory, provider: FakeProvider
) -> None:
    arabic_user = {"Authorization": f"Bearer {make_token(sub=f'ar-{uuid.uuid4()}', locale='ar')}"}
    await send(client, arabic_user, await new_chat(client, arabic_user), "?")
    assert "أجب باللغة العربية" in provider.calls[0][0].content
