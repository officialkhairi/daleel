from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwks import TokenVerifier
from app.auth.principal import Principal, Role
from app.db.session import tenant_session
from app.errors import Forbidden, Unauthorized

_bearer = HTTPBearer(auto_error=False)


async def current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None:
        raise Unauthorized("Missing bearer token.")
    verifier: TokenVerifier = request.app.state.verifier
    claims = await verifier.verify(credentials.credentials)
    return Principal.from_claims(claims)


def require(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    """Dependency that admits callers holding at least one of `roles`."""
    allowed = frozenset(roles)

    async def check(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.roles & allowed:
            raise Forbidden(f"Requires one of: {', '.join(sorted(allowed))}.")
        return principal

    return check


async def tenant_db(
    request: Request, principal: Principal = Depends(current_principal)
) -> AsyncIterator[AsyncSession]:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        yield session
