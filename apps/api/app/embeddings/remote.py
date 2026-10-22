"""Embedders that run elsewhere: an OpenAI-compatible /embeddings endpoint, or the worker."""

import math
from collections.abc import Sequence
from typing import Any

import httpx
from arq import ArqRedis

from app.embeddings.base import EmbeddingError, EmbedKind
from app.jobs import EMBED_TEXTS


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class OpenAICompatEmbedder:
    def __init__(
        self, *, base_url: str, model: str, api_key: str, http: httpx.AsyncClient, batch_size: int
    ) -> None:
        if not base_url:
            raise ValueError("EMBEDDINGS_BASE_URL is required for openai_compat embeddings")
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http
        self._batch = batch_size

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            batch = list(texts[start : start + self._batch])
            try:
                response = await self._http.post(
                    self._url,
                    json={"model": self._model, "input": batch},
                    headers=self._headers,
                    timeout=120.0,
                )
                response.raise_for_status()
                data: list[dict[str, Any]] = response.json()["data"]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise EmbeddingError(f"Embedding server failed: {exc}") from exc
            vectors.extend(
                _unit(item["embedding"]) for item in sorted(data, key=lambda d: d["index"])
            )
        return vectors


class WorkerEmbedder:
    """Asks the worker (which holds the model) to embed. Used by the API for queries, so the API
    image never needs PyTorch."""

    def __init__(self, arq: ArqRedis, *, timeout: float) -> None:
        self._arq = arq
        self._timeout = timeout

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        job = await self._arq.enqueue_job(EMBED_TEXTS, list(texts), kind)
        if job is None:  # pragma: no cover - only when a job id is reused
            raise EmbeddingError("Could not queue the embedding job.")
        try:
            vectors: list[list[float]] = await job.result(timeout=self._timeout, poll_delay=0.02)
        except TimeoutError as exc:
            raise EmbeddingError("The worker did not embed the query in time.") from exc
        return vectors
