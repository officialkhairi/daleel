from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.jwks import JWKSCache, TokenVerifier
from app.errors import ServiceUnavailable, Unauthorized
from tests.conftest import AUDIENCE, ISSUER, JWKS_URL, KID, TokenFactory


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _cache(transport: httpx.MockTransport, clock: Clock) -> tuple[JWKSCache, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=transport)
    return JWKSCache(JWKS_URL, http, ttl=300, min_refresh=10, clock=clock), http


async def test_keys_are_cached_until_ttl(
    jwks_transport: httpx.MockTransport, jwks_requests: list[httpx.Request]
) -> None:
    clock = Clock()
    cache, http = _cache(jwks_transport, clock)
    async with http:
        await cache.get_key(KID)
        await cache.get_key(KID)
        assert len(jwks_requests) == 1

        clock.now += 301
        await cache.get_key(KID)
        assert len(jwks_requests) == 2


async def test_unknown_kid_refetches_at_most_once_per_interval(
    jwks_transport: httpx.MockTransport, jwks_requests: list[httpx.Request]
) -> None:
    clock = Clock()
    cache, http = _cache(jwks_transport, clock)
    async with http:
        await cache.get_key(KID)
        clock.now += 11
        with pytest.raises(Unauthorized):
            await cache.get_key("rotated")
        with pytest.raises(Unauthorized):
            await cache.get_key("rotated-again")
        assert len(jwks_requests) == 2


async def test_idp_outage_is_retryable_503() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(502))
    cache, http = _cache(transport, Clock())
    async with http:
        with pytest.raises(ServiceUnavailable) as exc:
            await cache.get_key(KID)
    assert exc.value.retryable
    assert exc.value.code == "auth_unavailable"


@pytest.fixture
async def verifier(jwks_transport: httpx.MockTransport) -> Any:
    cache, http = _cache(jwks_transport, Clock())
    async with http:
        yield TokenVerifier(cache, issuer=ISSUER, audience=AUDIENCE)


async def test_valid_token_returns_claims(
    verifier: TokenVerifier, make_token: TokenFactory
) -> None:
    claims = await verifier.verify(make_token(sub="abc"))
    assert claims["sub"] == "abc"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"exp": 1}, "token_expired"),
        ({"aud": "someone-else"}, "invalid_token"),
        ({"iss": "http://evil.test/realms/daleel"}, "invalid_token"),
    ],
)
async def test_rejects_bad_claims(
    verifier: TokenVerifier, make_token: TokenFactory, overrides: dict[str, Any], code: str
) -> None:
    with pytest.raises(Unauthorized) as exc:
        await verifier.verify(make_token(**overrides))
    assert exc.value.code == code


async def test_rejects_token_signed_by_another_key(
    verifier: TokenVerifier, make_token: TokenFactory
) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(Unauthorized):
        await verifier.verify(make_token(key=other))


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c"])
async def test_rejects_garbage(verifier: TokenVerifier, token: str) -> None:
    with pytest.raises(Unauthorized):
        await verifier.verify(token)


async def test_rejects_hs256_token(verifier: TokenVerifier) -> None:
    import jwt

    forged = jwt.encode(
        {"sub": "x"}, "secret-at-least-32-bytes-long-key!", algorithm="HS256", headers={"kid": KID}
    )
    with pytest.raises(Unauthorized):
        await verifier.verify(forged)
