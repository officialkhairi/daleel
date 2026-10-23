"""The real side-effect clients: SMTP into a Mailpit container, and the ticketing HTTP API."""

import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.agent.effects import EffectError, Mailer, Ticketing


@pytest.fixture(scope="module")
def mailpit() -> Iterator[tuple[str, int, int]]:
    container = (
        DockerContainer("axllent/mailpit:v1.27.0")
        .with_exposed_ports(1025, 8025)
        .waiting_for(LogMessageWaitStrategy("accessible via"))
    )
    with container:
        host = container.get_container_host_ip()
        yield host, int(container.get_exposed_port(1025)), int(container.get_exposed_port(8025))


async def test_mailer_delivers_to_mailpit(mailpit: tuple[str, int, int]) -> None:
    host, smtp, web = mailpit
    mailer = Mailer(host=host, port=smtp, sender="Daleel <daleel@acme.example>")
    await mailer.send(
        to=["procurement@acme.example"],
        subject="تذكير: حدود الاعتماد",
        body="Contracts above 500,000 AED go to the committee.",
        headers={"X-Daleel-Approval": "a1"},
    )
    async with httpx.AsyncClient(base_url=f"http://{host}:{web}") as http:
        messages = (await http.get("/api/v1/messages")).json()["messages"]
        assert messages[0]["Subject"] == "تذكير: حدود الاعتماد"
        assert messages[0]["To"][0]["Address"] == "procurement@acme.example"
        headers = (await http.get(f"/api/v1/message/{messages[0]['ID']}/headers")).json()
        assert headers["X-Daleel-Approval"] == ["a1"]


async def test_mailer_reports_an_unreachable_server() -> None:
    mailer = Mailer(host="127.0.0.1", port=1, sender="d@acme.example")
    with pytest.raises(EffectError):
        await mailer.send(to=["a@b.c"], subject="s", body="b", headers={})


@pytest.fixture
def ticketing_app() -> object:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mock-ticketing"))
    import main  # type: ignore[import-not-found]  # the mock service, imported by path

    main.TOKEN = "t"
    return main.app


async def test_ticketing_client_against_the_mock_service(ticketing_app: object) -> None:
    transport = httpx.ASGITransport(app=ticketing_app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport) as http:
        ticketing = Ticketing(base_url="http://ticketing.test", token="t", http=http)
        ticket = await ticketing.create(
            title="Renew", body="soon", priority="high", requester="officer"
        )
        assert ticket["key"].startswith("OPS-")
        wrong = Ticketing(base_url="http://ticketing.test", token="nope", http=http)
        with pytest.raises(EffectError):
            await wrong.create(title="x", body="y", priority="low", requester="z")
