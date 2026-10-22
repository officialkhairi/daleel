from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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

    redis_url: str = "redis://localhost:6379/0"
    # How long a finished run's events stay replayable for Last-Event-ID resume.
    run_events_ttl_seconds: int = 3600

    # "fake" streams a canned answer (no model needed); "openai_compat" talks to any
    # OpenAI-compatible /chat/completions endpoint (vLLM, Ollama, AI71, OpenAI).
    llm_provider: Literal["fake", "openai_compat"] = "fake"
    llm_base_url: str = ""
    llm_model: str = "fake-echo"
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = 60.0
    # Some servers reject `stream_options`; turn off to skip the usage chunk.
    llm_stream_usage: bool = True
    # USD per million tokens, for the `usage` event's cost estimate.
    llm_price_in_per_mtok: float = 0.0
    llm_price_out_per_mtok: float = 0.0
    # FakeProvider: path to a JSON script of turns to replay instead of echoing.
    llm_fake_script: str | None = None
    llm_fake_delay_ms: int = 30
    # Chat history sent to the model (most recent messages).
    chat_history_limit: int = 20

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
