import json
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.auth.principal import tenant_id_for
from app.db.models import Document
from app.db.session import tenant_session
from tests.conftest import MemoryStore, TokenFactory

PDF_BYTES = b"%PDF-1.7\n% test document\n"
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 64


def auth(make_token: TokenFactory, roles: list[str], tenant: str = "acme") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {make_token(sub=f'u-{uuid.uuid4()}', roles=roles, tenant=tenant)}"
    }


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    data: bytes = PDF_BYTES,
    name: str = "policy.pdf",
    **form: Any,
) -> httpx.Response:
    return await client.post(
        "/api/documents",
        headers=headers,
        files={"file": (name, data, "application/pdf")},
        data=form,
    )


def unique_pdf() -> bytes:
    return PDF_BYTES + uuid.uuid4().hex.encode()


async def test_upload_stores_queues_and_announces(
    app: FastAPI, client: httpx.AsyncClient, make_token: TokenFactory, store: MemoryStore
) -> None:
    editor = auth(make_token, ["editor"])
    pubsub = app.state.redis.pubsub()
    await pubsub.subscribe(f"tenant:{tenant_id_for('acme')}:events")
    await pubsub.get_message(timeout=1)  # subscribe confirmation

    data = unique_pdf()
    response = await upload(client, editor, data, "../../Procurement Policy (v2).pdf")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["title"] == "Procurement Policy (v2)"
    assert body["filename"] == "Procurement_Policy_v2.pdf"  # no path parts, no odd characters
    assert body["acl_roles"] == ["viewer", "editor", "approver", "admin"]

    key = f"{tenant_id_for('acme')}/{body['id']}/Procurement_Policy_v2.pdf"
    assert store.objects[key] == (data, "application/pdf")

    queued = await app.state.arq.queued_jobs()
    assert any(job.function == "ingest_document" and job.args[0] == body["id"] for job in queued)

    message = await pubsub.get_message(timeout=2)
    assert message is not None
    event = json.loads(message["data"])
    assert (event["document_id"], event["stage"]) == (body["id"], "queued")
    await pubsub.aclose()


async def test_type_is_decided_by_content(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    editor = auth(make_token, ["editor"])
    response = await upload(client, editor, b"MZ\x90\x00 not a pdf", "evil.pdf")
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_file"

    docx = await upload(client, editor, DOCX_BYTES + uuid.uuid4().bytes, "memo.bin")
    assert docx.status_code == 202
    assert docx.json()["filename"] == "memo.docx"


async def test_size_limit(
    app: FastAPI, client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"upload_max_bytes": 64})
    response = await upload(client, auth(make_token, ["editor"]), PDF_BYTES + b"x" * 100)
    assert response.status_code == 413


async def test_duplicates_are_rejected(
    client: httpx.AsyncClient, make_token: TokenFactory, store: MemoryStore
) -> None:
    editor = auth(make_token, ["editor"])
    data = unique_pdf()
    assert (await upload(client, editor, data)).status_code == 202
    second = await upload(client, editor, data, "copy.pdf")
    assert second.status_code == 409
    assert second.json()["code"] == "duplicate_document"
    assert sum(1 for d, _ in store.objects.values() if d == data) == 1  # orphan cleaned up


async def test_viewers_cannot_upload_or_delete(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    viewer = auth(make_token, ["viewer"])
    assert (await upload(client, viewer, unique_pdf())).status_code == 403
    doc = (await upload(client, auth(make_token, ["editor"]), unique_pdf())).json()
    assert (await client.delete(f"/api/documents/{doc['id']}", headers=viewer)).status_code == 403


async def test_acl_roles_control_visibility(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    editor = auth(make_token, ["editor"])
    restricted = (
        await upload(client, editor, unique_pdf(), "board.pdf", acl_roles=["approver"])
    ).json()
    assert restricted["acl_roles"] == ["approver", "admin"]  # admin is always added

    viewer = auth(make_token, ["viewer"])
    approver = auth(make_token, ["approver"])
    admin = auth(make_token, ["admin"])
    for headers, visible in ((viewer, False), (approver, True), (admin, True), (editor, False)):
        listed = [d["id"] for d in (await client.get("/api/documents", headers=headers)).json()]
        assert (restricted["id"] in listed) is visible
        detail = await client.get(f"/api/documents/{restricted['id']}", headers=headers)
        assert detail.status_code == (200 if visible else 404)
        file = await client.get(f"/api/documents/{restricted['id']}/file", headers=headers)
        assert file.status_code == (200 if visible else 404)


async def test_unknown_role_is_rejected(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    response = await upload(client, auth(make_token, ["editor"]), unique_pdf(), acl_roles=["root"])
    assert response.status_code == 422


async def test_download_serves_the_original(
    client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    editor = auth(make_token, ["editor"])
    data = unique_pdf()
    doc = (await upload(client, editor, data, "سياسة.pdf")).json()
    response = await client.get(f"/api/documents/{doc['id']}/file", headers=editor)
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline; filename*=UTF-8''")
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_delete_removes_row_and_file(
    client: httpx.AsyncClient, make_token: TokenFactory, store: MemoryStore
) -> None:
    editor = auth(make_token, ["editor"])
    doc = (await upload(client, editor, unique_pdf())).json()
    assert (await client.delete(f"/api/documents/{doc['id']}", headers=editor)).status_code == 204
    assert (await client.get(f"/api/documents/{doc['id']}", headers=editor)).status_code == 404
    assert not any(doc["id"] in key for key in store.objects)


async def test_other_tenants_documents_are_invisible(
    app: FastAPI, client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    doc = (await upload(client, auth(make_token, ["editor"], "acme"), unique_pdf())).json()
    globex = auth(make_token, ["admin"], "globex")
    assert (await client.get(f"/api/documents/{doc['id']}", headers=globex)).status_code == 404
    async with tenant_session(app.state.sessions, tenant_id_for("globex")) as session:
        assert (
            await session.scalar(select(Document).where(Document.id == uuid.UUID(doc["id"])))
            is None
        )


def test_websocket_requires_auth_then_relays_visible_progress(
    settings: Any, jwks_transport: httpx.MockTransport, make_token: TokenFactory
) -> None:
    from fastapi.testclient import TestClient
    from redis import Redis as SyncRedis
    from starlette.websockets import WebSocketDisconnect

    from app.main import create_app

    app = create_app(settings, http_client=httpx.AsyncClient(transport=jwks_transport))
    redis = SyncRedis.from_url(settings.redis_url)
    channel = f"tenant:{tenant_id_for('acme')}:events"

    def event(acl: list[str]) -> str:
        return json.dumps(
            {
                "type": "document.progress",
                "document_id": str(uuid.uuid4()),
                "status": "processing",
                "stage": "embedding",
                "progress": 40,
                "acl_roles": acl,
            }
        )

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws/documents") as ws:
            ws.send_json({"type": "auth", "token": "garbage"})
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1008

        with client.websocket_connect("/api/ws") as ws:
            ws.send_json({"type": "auth", "token": make_token(roles=["viewer"])})
            assert ws.receive_json() == {"type": "ready"}
            redis.publish(channel, event(["approver", "admin"]))  # not for viewers
            redis.publish(channel, event(["viewer", "admin"]))
            received = ws.receive_json()
            assert received["progress"] == 40
            assert "acl_roles" not in received
    redis.close()
