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

    # Object storage (MinIO or any S3-compatible store).
    s3_endpoint: str = "localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "daleel"
    s3_secure: bool = False
    upload_max_bytes: int = 25 * 1024 * 1024

    # "sentence_transformers" runs BAAI/bge-m3 in the worker (the API asks the worker to embed
    # queries); "openai_compat" calls any /v1/embeddings endpoint (Ollama, TEI, vLLM, OpenAI);
    # "fake" hashes words into vectors (tests, first run).
    embeddings_provider: Literal["fake", "sentence_transformers", "openai_compat"] = "fake"
    embeddings_model: str = "BAAI/bge-m3"
    embeddings_base_url: str = ""
    embeddings_api_key: SecretStr = SecretStr("")
    embeddings_batch_size: int = 16
    # How long the API waits for the worker to embed a query.
    embeddings_query_timeout_seconds: float = 15.0

    # Retrieval: candidates per method before fusion, results kept after it.
    retrieval_candidates: int = 20
    retrieval_top_k: int = 6
    retrieval_rrf_k: int = 60

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
