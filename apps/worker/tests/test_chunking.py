import itertools

from daleel_worker.chunking import chunk_blocks, estimate_tokens
from daleel_worker.parsing import Block, Box


def body(text: str, page: int = 1, y: float = 0) -> Block:
    return Block(text=text, kind="body", page=page, boxes=[Box(page, 10, y, 100, y + 10)])


def words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def test_chunks_never_cross_headings() -> None:
    blocks = [
        Block("Scope", "heading"),
        body("Applies to everyone."),
        Block("Thresholds", "heading"),
        body("Above 500,000 needs the committee.", page=2),
    ]
    chunks = chunk_blocks(blocks)
    assert [(c.heading, c.text, c.page) for c in chunks] == [
        ("Scope", "Applies to everyone.", 1),
        ("Thresholds", "Above 500,000 needs the committee.", 2),
    ]
    assert chunks[1].embedding_text == "Thresholds\nAbove 500,000 needs the committee."


def test_long_sections_split_near_target_with_overlap() -> None:
    blocks = [Block("Long", "heading")] + [body(words(60, f"w{i}"), y=i * 20) for i in range(20)]
    chunks = chunk_blocks(blocks, target=200, overlap=0.5)

    assert len(chunks) > 1
    assert all(c.token_count <= 200 for c in chunks)
    # The last block of one chunk opens the next (overlap) ...
    for first, second in itertools.pairwise(chunks):
        assert first.text.split("\n")[-1] == second.text.split("\n")[0]
    # ... and every block appears somewhere.
    joined = "\n".join(c.text for c in chunks)
    assert all(f"w{i}" in joined for i in range(20))


def test_overlap_does_not_leak_into_the_next_section() -> None:
    blocks = [Block("A", "heading"), body(words(10, "alpha")), Block("B", "heading"), body("beta")]
    chunks = chunk_blocks(blocks, target=50, overlap=0.9)
    assert "alpha" not in chunks[1].text


def test_oversized_block_is_split_at_sentences_and_keeps_its_box() -> None:
    text = " ".join(f"Sentence {i} {words(20)}." for i in range(10))
    chunks = chunk_blocks([body(text, page=3)], target=60, overlap=0)
    assert len(chunks) >= 3
    assert all(c.page == 3 and c.boxes == [Box(3, 10, 0, 100, 10)] for c in chunks)
    assert chunks[0].text.startswith("Sentence 0")


def test_boxes_are_merged_without_duplicates() -> None:
    blocks = [body("one", y=0), body("two", y=20), body("three", page=2, y=0)]
    [chunk] = chunk_blocks(blocks)
    assert [(b.page, b.y0) for b in chunk.boxes] == [(1, 0), (1, 20), (2, 0)]
    assert chunk.page == 1


def test_token_estimate() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens(words(10)) == 13
    assert estimate_tokens("العقود التي تتجاوز") == 4
