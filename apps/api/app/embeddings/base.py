from collections.abc import Sequence
from typing import Literal, Protocol

# bge-m3 needs no query/document prefixes, but some embedding models do; providers get the hint.
EmbedKind = Literal["query", "document"]


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        """One unit-length vector per text, in order."""
        ...


class EmbeddingError(Exception):
    pass
