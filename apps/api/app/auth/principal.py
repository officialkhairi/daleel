import uuid
from typing import Any, Literal, get_args

from pydantic import BaseModel

from app.errors import Unauthorized

Role = Literal["viewer", "editor", "approver", "admin"]
KNOWN_ROLES: frozenset[str] = frozenset(get_args(Role))

# Fixed namespace so a tenant slug always maps to the same id.
TENANT_NAMESPACE = uuid.UUID("6f2b8f3e-6a43-4c8e-9d0a-1f3c5d7e9b21")


def tenant_id_for(slug: str) -> uuid.UUID:
    return uuid.uuid5(TENANT_NAMESPACE, slug)


class Principal(BaseModel, frozen=True):
    """The authenticated caller, built only from a verified access token."""

    sub: str
    tenant: str
    tenant_id: uuid.UUID
    username: str
    name: str | None = None
    email: str | None = None
    locale: str = "en"
    roles: frozenset[Role]

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "Principal":
        tenant = claims.get("tenant")
        if not isinstance(tenant, str) or not tenant:
            raise Unauthorized("Token has no tenant.", code="invalid_token")
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        return cls(
            sub=claims["sub"],
            tenant=tenant,
            tenant_id=tenant_id_for(tenant),
            username=claims.get("preferred_username") or claims["sub"],
            name=claims.get("name"),
            email=claims.get("email"),
            locale=claims.get("locale") or "en",
            roles=frozenset(r for r in realm_roles if r in KNOWN_ROLES),
        )
