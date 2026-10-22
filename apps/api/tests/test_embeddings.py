import json
import math
from typing import Any

import httpx
import pytest

from app.embeddings.base import EmbeddingError
from app.embeddings.fake import FakeEmbedder, normalize
from app.embeddings.remote import OpenAICompatEmbedder, WorkerEmbedder


async def test_fake_vectors_are_unit_length_and_lexical() -> None:
    a, b, c = await FakeEmbedder().embed(
        ["approval threshold", "Approval THRESHOLD!", "vendor registration"], kind="document"
    )
    assert math.isclose(sum(v * v for v in a), 1.0)
    assert a == b
    assert sum(x * y for x, y in zip(a, c, strict=True)) == 0


def test_normalize_folds_arabic_variants() -> None:
    assert normalize("إِدارةُ") == normalize("ادارة") == "اداره"


async def test_openai_compat_batches_and_orders_by_index() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        data = [{"index": i, "embedding": [3.0, 4.0]} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": list(reversed(data))})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        embedder = OpenAICompatEmbedder(
            base_url="http://emb.test/v1", model="bge-m3", api_key="k", http=http, batch_size=2
        )
        vectors = await embedder.embed(["a", "b", "c"], kind="query")

    assert [r["input"] for r in requests] == [["a", "b"], ["c"]]
    assert requests[0]["model"] == "bge-m3"
    assert vectors == [[0.6, 0.8]] * 3  # normalised


async def test_openai_compat_errors() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as http:
        embedder = OpenAICompatEmbedder(
            base_url="http://emb.test/v1", model="m", api_key="", http=http, batch_size=8
        )
        with pytest.raises(EmbeddingError):
            await embedder.embed(["a"], kind="query")
    with pytest.raises(ValueError, match="EMBEDDINGS_BASE_URL"):
        OpenAICompatEmbedder(base_url="", model="m", api_key="", http=http, batch_size=1)


class FakeJob:
    def __init__(self, result: Any) -> None:
        self._result = result

    async def result(self, **_: float) -> Any:  # mirrors arq.jobs.Job.result
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeArq:
    def __init__(self, result: Any) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._result = result

    async def enqueue_job(self, *args: Any) -> FakeJob:
        self.calls.append(args)
        return FakeJob(self._result)


async def test_worker_embedder_round_trip_and_timeout() -> None:
    arq = FakeArq([[1.0, 0.0]])
    assert await WorkerEmbedder(arq, timeout=1).embed(["q"], kind="query") == [[1.0, 0.0]]  # type: ignore[arg-type]
    assert arq.calls == [("embed_texts", ["q"], "query")]

    slow = WorkerEmbedder(FakeArq(TimeoutError()), timeout=1)  # type: ignore[arg-type]
    with pytest.raises(EmbeddingError, match="in time"):
        await slow.embed(["q"], kind="query")
