"""Phase 5 gate: every route is authenticated, every role gets exactly what it should, and every
tenant table is protected by row-level security."""

import re
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TokenFactory
from tests.test_chat import new_chat, parse_sse
from tests.test_documents import unique_pdf, upload
from tests.test_rag import PROCUREMENT, add_document

PUBLIC = {"/healthz", "/readyz", "/metrics"}
ROLES = ["viewer", "editor", "approver", "admin"]


def fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


async def test_every_route_requires_a_token(app: FastAPI, client: httpx.AsyncClient) -> None:
    # Walk the OpenAPI schema: every documented operation except health checks.
    operations = [
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        if path not in PUBLIC
        for method in methods
    ]
    assert len(operations) >= 20
    for method, path in operations:
        response = await client.request(method, fill(path))
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.json()["code"] == "unauthorized"


# (method, path, roles allowed). "Allowed" means anything but 403: a random id then gives 404.
MATRIX: list[tuple[str, str, set[str]]] = [
    ("GET", "/api/me", set(ROLES)),
    ("GET", "/api/chats", set(ROLES)),
    ("POST", "/api/chats", set(ROLES)),
    ("GET", "/api/documents", set(ROLES)),
    ("GET", "/api/documents/{id}", set(ROLES)),
    ("GET", "/api/documents/{id}/file", set(ROLES)),
    ("PATCH", "/api/documents/{id}", {"editor", "admin"}),
    ("DELETE", "/api/documents/{id}", {"editor", "admin"}),
    ("GET", "/api/approvals", {"approver", "admin"}),
    ("GET", "/api/approvals/{id}", set(ROLES)),
    ("POST", "/api/approvals/{id}", {"approver", "admin"}),
    ("GET", "/api/admin/ping", {"admin"}),
    ("GET", "/api/admin/usage", {"admin"}),
    ("GET", "/api/admin/users", {"admin"}),
    ("GET", "/api/audit", {"admin"}),
]


@pytest.mark.parametrize(("method", "path", "allowed"), MATRIX)
@pytest.mark.parametrize("role", [*ROLES, "none"])
async def test_role_matrix(
    client: httpx.AsyncClient,
    make_token: TokenFactory,
    method: str,
    path: str,
    allowed: set[str],
    role: str,
) -> None:
    token = make_token(roles=[] if role == "none" else [role])
    body = {"decision": "reject"} if method == "POST" and "approvals" in path else {}
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.request(method, fill(path), json=body, headers=headers)
    if role in allowed or (path == "/api/me" and role == "none"):
        assert response.status_code != 403, f"{role} should reach {method} {path}"
    else:
        assert response.status_code == 403, f"{role} must not reach {method} {path}"
        assert response.json()["code"] == "forbidden"


async def test_uploads_need_an_editor(client: httpx.AsyncClient, make_token: TokenFactory) -> None:
    for role, status in (("viewer", 403), ("approver", 403), ("editor", 202), ("admin", 202)):
        headers = {"Authorization": f"Bearer {make_token(roles=[role])}"}
        assert (await upload(client, headers, unique_pdf())).status_code == status


async def test_every_tenant_table_has_forced_row_level_security(
    database_urls: tuple[str, str],
) -> None:
    engine = create_async_engine(database_urls[0])
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                           EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                      AND (c.relname = 'tenants' OR EXISTS (
                          SELECT 1 FROM information_schema.columns col
                          WHERE col.table_name = c.relname AND col.column_name = 'tenant_id'))
                    """
                )
            )
        ).all()
        view = await conn.scalar(
            text("SELECT reloptions FROM pg_class WHERE relname = 'usage_daily'")
        )
    await engine.dispose()
    tables = {r[0] for r in rows}
    assert {"documents", "chunks", "chats", "messages", "runs", "approvals", "audit_log"} <= tables
    unprotected = [r[0] for r in rows if not (r[1] and r[2] and r[3])]
    assert unprotected == []
    assert "security_invoker=true" in view  # the view applies the caller's RLS


async def test_access_changes_apply_at_once_and_are_audited(
    app: FastAPI, client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    editor = {"Authorization": f"Bearer {make_token(sub='ed', tenant=tenant, roles=['editor'])}"}
    viewer = {"Authorization": f"Bearer {make_token(sub='vi', tenant=tenant, roles=['viewer'])}"}
    admin = {"Authorization": f"Bearer {make_token(sub='ad', tenant=tenant, roles=['admin'])}"}
    doc = (await upload(client, editor, unique_pdf(), "memo.pdf")).json()
    assert (await client.get(f"/api/documents/{doc['id']}", headers=viewer)).status_code == 200

    response = await client.patch(
        f"/api/documents/{doc['id']}",
        json={"title": "Board memo", "acl_roles": ["editor"]},
        headers=editor,
    )
    assert response.status_code == 200
    assert response.json()["acl_roles"] == ["editor", "admin"]
    assert (await client.get(f"/api/documents/{doc['id']}", headers=viewer)).status_code == 404
    bad = await client.patch(
        f"/api/documents/{doc['id']}", json={"acl_roles": ["root"]}, headers=editor
    )
    assert bad.status_code == 422

    await client.delete(f"/api/documents/{doc['id']}", headers=editor)
    actions = [e["action"] for e in (await client.get("/api/audit", headers=admin)).json()]
    assert actions == ["document.deleted", "document.updated", "document.uploaded"]


async def test_usage_and_users_for_admins(
    app: FastAPI, client: httpx.AsyncClient, make_token: TokenFactory
) -> None:
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await add_document(app.state.sessions, tenant, "Policy", PROCUREMENT)
    officer_token = make_token(sub="o", tenant=tenant, roles=["editor", "approver"])
    officer = {"Authorization": f"Bearer {officer_token}"}
    admin = {"Authorization": f"Bearer {make_token(sub='a', tenant=tenant, roles=['admin'])}"}
    await client.get("/api/me", headers=officer)
    chat_id = await new_chat(client, officer)
    events = parse_sse(
        (
            await client.post(
                f"/api/chats/{chat_id}/messages",
                json={"content": "approval limits?"},
                headers=officer,
            )
        ).text
    )
    assert events[-1][2]["finish_reason"] == "stop"

    usage = (await client.get("/api/admin/usage?days=7", headers=admin)).json()
    [today] = usage["days"]
    assert (today["runs"], today["failed"]) == (1, 0)
    assert today["tokens_in"] > 0
    assert today["ttft_p50_ms"] is not None
    assert usage["totals"] == {
        "documents": 1,
        "chats": 1,
        "questions": 1,
        "pending_approvals": 0,
        "users": 1,
    }

    users = (await client.get("/api/admin/users", headers=admin)).json()
    assert [(u["username"], u["roles"]) for u in users] == [("officer", ["approver", "editor"])]


async def test_metrics_are_exported(client: httpx.AsyncClient, make_token: TokenFactory) -> None:
    headers = {"Authorization": f"Bearer {make_token()}"}
    chat_id = await new_chat(client, headers)
    await client.post(f"/api/chats/{chat_id}/messages", json={"content": "hi"}, headers=headers)
    body = (await client.get("/metrics")).text
    assert 'daleel_runs_total{status="completed"}' in body
    assert "daleel_run_ttft_seconds_bucket" in body
    assert (
        'daleel_http_requests_total{method="POST",route="/api/chats/{chat_id}/messages",status="200"}'
        in body
    )


def test_tracing_is_off_without_an_endpoint() -> None:
    from app.observability.tracing import configure_tracing, current_trace_id

    assert configure_tracing(None, "test") is False
    assert current_trace_id() is None
