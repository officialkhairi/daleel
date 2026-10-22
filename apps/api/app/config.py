from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment (and the repo-root .env in dev)."""

    model_config = SettingsConfigDict(env_file=("../../.env", ".env"), extra="ignore")

    database_url: str
    # Owner role used by Alembic. Falls back to database_url when unset.
    migrations_database_url: str | None = None
    # Role the API connects as; migrations grant it table privileges.
    app_db_user: str = "daleel_app"

    oidc_issuer: str
    oidc_jwks_url: str
    oidc_audience: str = "daleel-api"
    jwks_cache_ttl_seconds: int = 300
    # Minimum gap between JWKS refetches triggered by an unknown `kid`.
    jwks_min_refresh_seconds: int = 10

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
