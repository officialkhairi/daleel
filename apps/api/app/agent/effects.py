"""Clients for the outside world. Only approved tool calls reach these."""

from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx


class EffectError(Exception):
    """The side effect could not be carried out; the message goes back to the model and user."""


class Mailer:
    def __init__(self, *, host: str, port: int, sender: str) -> None:
        self._host = host
        self._port = port
        self._sender = sender

    async def send(self, *, to: list[str], subject: str, body: str, headers: dict[str, str]) -> str:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        for name, value in headers.items():
            message[name] = value
        message.set_content(body)
        try:
            await aiosmtplib.send(message, hostname=self._host, port=self._port, timeout=15)
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise EffectError(f"The mail server refused the message: {exc}") from exc
        return str(message["Message-ID"] or "")


class Ticketing:
    def __init__(self, *, base_url: str, token: str, http: httpx.AsyncClient) -> None:
        self._url = f"{base_url.rstrip('/')}/api/tickets"
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = http

    async def create(
        self, *, title: str, body: str, priority: str, requester: str
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(
                self._url,
                json={"title": title, "body": body, "priority": priority, "requester": requester},
                headers=self._headers,
                timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EffectError(f"The ticketing system failed: {exc}") from exc
        ticket: dict[str, Any] = response.json()
        return ticket
