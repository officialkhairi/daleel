import httpx
from arq import ArqRedis

from app.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.fake import FakeEmbedder
from app.embeddings.remote import OpenAICompatEmbedder, WorkerEmbedder


def build_query_embedder(settings: Settings, http: httpx.AsyncClient, arq: ArqRedis) -> Embedder:
    """The API's embedder, used for queries. It must match what the worker used for documents."""
    if settings.embeddings_provider == "sentence_transformers":
        return WorkerEmbedder(arq, timeout=settings.embeddings_query_timeout_seconds)
    if settings.embeddings_provider == "openai_compat":
        return OpenAICompatEmbedder(
            base_url=settings.embeddings_base_url,
            model=settings.embeddings_model,
            api_key=settings.embeddings_api_key.get_secret_value(),
            http=http,
            batch_size=settings.embeddings_batch_size,
        )
    return FakeEmbedder()
