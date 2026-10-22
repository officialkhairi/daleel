"""Heading-aware chunking: a chunk never spans two sections, aims for ~500 tokens, and repeats the
tail of the previous chunk (~15%) so a sentence cut at a boundary is still found whole."""

import re
from dataclasses import dataclass, field

from daleel_worker.parsing import Block, Box

_WORD = re.compile(r"\w+", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?؟。])\s+")


def estimate_tokens(text: str) -> int:
    """~1.3 subword tokens per word for bge-m3's tokenizer on English and Arabic prose."""
    return max(1, round(len(_WORD.findall(text)) * 1.3))


@dataclass
class ChunkDraft:
    text: str
    heading: str | None
    page: int | None
    boxes: list[Box] = field(default_factory=list)
    token_count: int = 0

    @property
    def embedding_text(self) -> str:
        return f"{self.heading}\n{self.text}" if self.heading else self.text


@dataclass
class _Piece:
    text: str
    page: int | None
    boxes: list[Box]
    tokens: int


def _pieces(block: Block, target: int) -> list[_Piece]:
    """A block bigger than a whole chunk is split at sentence ends (all pieces keep its box)."""
    tokens = estimate_tokens(block.text)
    if tokens <= target:
        return [_Piece(block.text, block.page, block.boxes, tokens)]
    pieces: list[_Piece] = []
    current: list[str] = []
    for sentence in _SENTENCE_END.split(block.text):
        if current and estimate_tokens(" ".join([*current, sentence])) > target:
            text = " ".join(current)
            pieces.append(_Piece(text, block.page, block.boxes, estimate_tokens(text)))
            current = []
        current.append(sentence)
    if current:
        text = " ".join(current)
        pieces.append(_Piece(text, block.page, block.boxes, estimate_tokens(text)))
    return pieces


def _draft(pieces: list[_Piece], heading: str | None) -> ChunkDraft:
    boxes: list[Box] = []
    for piece in pieces:
        for box in piece.boxes:
            if box not in boxes:
                boxes.append(box)
    text = "\n".join(p.text for p in pieces)
    return ChunkDraft(
        text=text,
        heading=heading,
        page=next((p.page for p in pieces if p.page is not None), None),
        boxes=boxes,
        token_count=sum(p.tokens for p in pieces),
    )


def chunk_blocks(
    blocks: list[Block], *, target: int = 500, overlap: float = 0.15
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    heading: str | None = None
    current: list[_Piece] = []
    fresh = 0  # tokens added since the last flush (excludes carried-over overlap)
    budget = int(target * overlap)

    def flush() -> None:
        nonlocal current, fresh
        if fresh:
            chunks.append(_draft(current, heading))
        # Carry the tail into the next chunk, up to the overlap budget.
        carried: list[_Piece] = []
        total = 0
        for piece in reversed(current):
            if total + piece.tokens > budget:
                break
            carried.insert(0, piece)
            total += piece.tokens
        current, fresh = carried, 0

    for block in blocks:
        if block.kind == "heading":
            flush()
            current = []  # overlap never crosses into a new section
            heading = block.text
            continue
        for piece in _pieces(block, target):
            if fresh and sum(p.tokens for p in current) + piece.tokens > target:
                flush()
            current.append(piece)
            fresh += piece.tokens
    flush()
    return chunks
