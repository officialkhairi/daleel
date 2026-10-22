import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings
from app.embeddings.base import Embedder, EmbedKind
from app.embeddings.fake import FakeEmbedder
from app.embeddings.remote import OpenAICompatEmbedder

log = logging.getLogger(__name__)


class SentenceTransformerEmbedder:
    """BAAI/bge-m3 in this process. Loading takes a while (and downloads ~2.3 GB the first time),
    so it happens once at worker startup."""

    def __init__(self, model_name: str, *, batch_size: int) -> None:
        from sentence_transformers import SentenceTransformer  # optional dependency

        log.info("loading embedding model %s", model_name)
        self._model: Any = SentenceTransformer(model_name, device="cpu")
        self._batch = batch_size

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        def encode() -> list[list[float]]:
            vectors = self._model.encode(
                list(texts), batch_size=self._batch, normalize_embeddings=True
            )
            return [list(map(float, v)) for v in vectors]

        return await asyncio.to_thread(encode)


def build_embedder(settings: Settings, http: httpx.AsyncClient) -> Embedder:
    if settings.embeddings_provider == "sentence_transformers":
        return SentenceTransformerEmbedder(
            settings.embeddings_model, batch_size=settings.embeddings_batch_size
        )
    if settings.embeddings_provider == "openai_compat":
        return OpenAICompatEmbedder(
            base_url=settings.embeddings_base_url,
            model=settings.embeddings_model,
            api_key=settings.embeddings_api_key.get_secret_value(),
            http=http,
            batch_size=settings.embeddings_batch_size,
        )
    return FakeEmbedder()
