"""Deterministic embeddings for tests and the default stack: a hashed bag of words. Texts that share
words get similar vectors, which is enough to exercise retrieval without a model."""

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence

from app.db.models import EMBEDDING_DIM
from app.embeddings.base import EmbedKind

_WORD = re.compile(r"\w+", re.UNICODE)
# Arabic diacritics (tashkeel) and tatweel.
_ARABIC_MARKS = re.compile(r"[ً-ْـ]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _ARABIC_MARKS.sub("", text)
    return text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")


def _bucket(word: str) -> int:
    return (
        int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "big")
        % EMBEDDING_DIM
    )


class FakeEmbedder:
    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIM
            for word in _WORD.findall(normalize(text)):
                vector[_bucket(word)] += 1.0
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors
