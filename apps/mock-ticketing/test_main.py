from fastapi.testclient import TestClient

import main


def test_create_and_list(monkeypatch: object) -> None:
    main.TOKEN = "t0ken"
    client = TestClient(main.app)
    assert client.post("/api/tickets", json={"title": "x", "body": "y"}).status_code == 401
    headers = {"Authorization": "Bearer t0ken"}
    created = client.post(
        "/api/tickets", json={"title": "Renew contract", "body": "<b>soon</b>"}, headers=headers
    ).json()
    assert created["key"].startswith("OPS-")
    assert client.get("/api/tickets", headers=headers).json()[0]["key"] == created["key"]
    page = client.get("/").text
    assert "Renew contract" in page
    assert "&lt;b&gt;soon&lt;/b&gt;" in page
