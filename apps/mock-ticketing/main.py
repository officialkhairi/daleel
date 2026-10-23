"""Mock ticketing system (stand-in for Jira/ServiceNow). Tickets live in memory.

POST /api/tickets   create (bearer token)       GET /api/tickets   list (bearer token)
GET  /               an HTML list, so a demo can show the ticket arriving"""

import os
import secrets
from datetime import UTC, datetime
from html import escape
from itertools import count
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Mock ticketing")
TOKEN = os.environ.get("TICKETING_TOKEN", "")
_numbers = count(101)
_tickets: list["Ticket"] = []


class NewTicket(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(max_length=5000)]
    priority: Literal["low", "medium", "high"] = "medium"
    requester: Annotated[str, Field(max_length=255)] = ""


class Ticket(NewTicket):
    key: str
    status: Literal["open"] = "open"
    created_at: datetime


def authorized(authorization: Annotated[str | None, Header()] = None) -> None:
    if TOKEN and not secrets.compare_digest(authorization or "", f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/api/tickets", status_code=201, dependencies=[Depends(authorized)])
def create(ticket: NewTicket) -> Ticket:
    created = Ticket(
        **ticket.model_dump(), key=f"OPS-{next(_numbers)}", created_at=datetime.now(UTC)
    )
    _tickets.append(created)
    return created


@app.get("/api/tickets", dependencies=[Depends(authorized)])
def list_tickets() -> list[Ticket]:
    return list(reversed(_tickets))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    rows = (
        "".join(
            f"<tr><td>{t.key}</td><td>{escape(t.priority)}</td><td dir='auto'>{escape(t.title)}</td>"
            f"<td dir='auto'>{escape(t.body)}</td><td>{escape(t.requester)}</td>"
            f"<td>{t.created_at:%Y-%m-%d %H:%M}</td></tr>"
            for t in reversed(_tickets)
        )
        or "<tr><td colspan='6'>No tickets yet.</td></tr>"
    )
    return (
        "<!doctype html><meta charset='utf-8'><title>Mock ticketing</title>"
        "<style>body{font-family:system-ui;margin:2rem}td,th{border-bottom:1px solid #ddd;"
        "padding:.4rem .6rem;text-align:start;vertical-align:top}</style>"
        "<h1>Tickets</h1><table><tr><th>Key</th><th>Priority</th><th>Title</th><th>Body</th>"
        f"<th>Requester</th><th>Created</th></tr>{rows}</table>"
    )
