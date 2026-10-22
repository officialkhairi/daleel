import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import TokenFactory


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


async def test_readyz_checks_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200


async def test_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


async def test_me_returns_roles_and_records_user(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    token = make_token(sub="officer-sub", roles=["editor", "approver", "offline_access"])
    first = await client.get("/api/me", headers=auth(token))
    assert first.status_code == 200
    body = first.json()
    assert body["roles"] == ["approver", "editor"]  # unknown realm roles dropped, sorted
    assert body["tenant"] == "acme"
    assert body["username"] == "officer"
    assert body["locale"] == "en"

    second = await client.get("/api/me", headers=auth(token))
    assert second.json()["id"] == body["id"]  # upsert, not a second row


async def test_me_without_token_is_401_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "code": "unauthorized",
        "message": "Missing bearer token.",
        "retryable": False,
    }


async def test_me_with_bad_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me", headers=auth("garbage"))
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


async def test_token_without_tenant_is_rejected(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    response = await client.get("/api/me", headers=auth(make_token(tenant=None)))
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


@pytest.mark.parametrize(
    ("roles", "status"),
    [(["viewer"], 403), (["editor", "approver"], 403), (["admin"], 200), ([], 403)],
)
async def test_admin_ping_rbac(
    client: httpx.AsyncClient, make_token: TokenFactory, roles: list[str], status: int
) -> None:
    response = await client.get("/api/admin/ping", headers=auth(make_token(roles=roles)))
    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "forbidden"


async def test_unknown_route_is_enveloped(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_unhandled_error_hides_details(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    response = await client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Something went wrong.",
        "retryable": True,
    }
    assert "secret" not in response.text
    assert "Traceback" not in response.text
