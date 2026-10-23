import pytest

from app.rag.citations import CitationFilter


def run(chunks: list[str], valid: set[int]) -> tuple[str, list[int], int]:
    f = CitationFilter(valid=valid)
    out, cited = [], []
    for chunk in chunks:
        text, new = f.feed(chunk)
        out.append(text)
        cited += new
    text, new = f.flush()
    return "".join(out) + text, cited + new, f.dropped


def test_passes_valid_markers_and_reports_first_use() -> None:
    assert run(["The limit is 50,000 AED [1]. Above it [2][1]."], {1, 2}) == (
        "The limit is 50,000 AED [1]. Above it [2][1].",
        [1, 2],
        0,
    )


@pytest.mark.parametrize("split", range(1, 12))
def test_markers_split_across_tokens(split: int) -> None:
    text = "Approved [12] ok"
    assert run([text[:split], text[split:]], {12}) == (text, [12], 0)


def test_drops_unretrieved_sources() -> None:
    assert run(["Yes [1][7]. No [9]."], {1, 2}) == ("Yes [1]. No .", [1], 2)


def test_normalizes_lists_including_arabic_comma() -> None:
    assert run(["a [1, 2] b [2،3]"], {1, 2, 3}) == ("a [1][2] b [2][3]", [1, 2, 3], 0)


@pytest.mark.parametrize("text", ["see [note]", "array[0]x", "[", "a [ b", "x [123] y", "[1"])
def test_other_brackets_are_text(text: str) -> None:
    assert run([text], {1, 123})[0] == text


def test_holds_partial_marker_until_closed() -> None:
    f = CitationFilter(valid={3})
    assert f.feed("cost [") == ("cost ", [])
    assert f.feed("3") == ("", [])
    assert f.feed("] done") == ("[3] done", [3])


@pytest.mark.parametrize(
    ("marker", "plain"),
    [
        ('[source n="1"]', "[1]"),
        ("[Source 1]", "[1]"),
        ("[source n=1]", "[1]"),
        ("[source 1, 2]", "[1][2]"),
    ],
)
def test_rewrites_echoed_source_tags(marker: str, plain: str) -> None:
    assert run([f"Board approval {marker}."], {1, 2})[0] == f"Board approval {plain}."


@pytest.mark.parametrize("split", range(1, 16))
def test_echoed_source_tag_split_across_tokens(split: int) -> None:
    text = 'Yes [source n="2"] ok'
    assert run([text[:split], text[split:]], {2}) == ("Yes [2] ok", [2], 0)


def test_source_word_without_number_is_text() -> None:
    text = "the [source code] and [sour cream]"
    assert run([text], {1})[0] == text
