import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt

from app.errors import ServiceUnavailable, Unauthorized

log = logging.getLogger(__name__)

ALGORITHMS = ["RS256"]


class JWKSCache:
    """Signing keys from the issuer, cached for `ttl` seconds.

    An unknown `kid` (key rotation) triggers one refetch, rate-limited by `min_refresh` so a
    flood of forged tokens cannot turn into a flood of requests to Keycloak.
    """

    def __init__(
        self,
        url: str,
        http: httpx.AsyncClient,
        *,
        ttl: float,
        min_refresh: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._http = http
        self._ttl = ttl
        self._min_refresh = min_refresh
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    def _age(self) -> float:
        return float("inf") if self._fetched_at is None else self._clock() - self._fetched_at

    async def _refresh(self) -> None:
        try:
            response = await self._http.get(self._url, timeout=5.0)
            response.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, jwt.PyJWKSetError, ValueError) as exc:
            log.warning("JWKS fetch from %s failed: %s", self._url, exc)
            raise ServiceUnavailable(
                "Identity provider is unavailable.", code="auth_unavailable"
            ) from exc
        self._keys = {k.key_id: k for k in jwk_set.keys if k.key_id}
        self._fetched_at = self._clock()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        async with self._lock:
            stale = self._age() >= self._ttl
            unknown = kid not in self._keys and self._age() >= self._min_refresh
            if stale or unknown:
                await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise Unauthorized("Token signed with an unknown key.", code="invalid_token")
        return key


class TokenVerifier:
    def __init__(self, jwks: JWKSCache, *, issuer: str, audience: str) -> None:
        self._jwks = jwks
        self._issuer = issuer
        self._audience = audience

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise Unauthorized("Malformed token.", code="invalid_token") from exc
        kid = header.get("kid")
        if header.get("alg") not in ALGORITHMS or not isinstance(kid, str):
            raise Unauthorized("Unsupported token.", code="invalid_token")

        key = await self._jwks.get_key(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthorized("Token expired.", code="token_expired") from exc
        except jwt.InvalidTokenError as exc:
            raise Unauthorized("Invalid token.", code="invalid_token") from exc
        return claims
