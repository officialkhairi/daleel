import pytest

from app.chat.language import detect_language, system_prompt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hello", "en"),
        ("What is the approval threshold for vendor contracts?", "en"),
        ("ما هي عتبة الموافقة على عقود الموردين؟", "ar"),
        ("مرحبا", "ar"),
        ("ما معنى KPI في العقود؟", "ar"),  # mostly Arabic with a Latin acronym
        ("Explain the term عقد in one line", "en"),  # mostly English with an Arabic word
        ("ﻣﺮﺣﺒﺎ", "ar"),  # presentation forms
    ],
)
def test_detects_by_script(text: str, expected: str) -> None:
    assert detect_language(text, fallback="en") == expected


@pytest.mark.parametrize("text", ["?", "123", "   ", "🙂"])
def test_no_letters_uses_fallback(text: str) -> None:
    assert detect_language(text, fallback="ar") == "ar"
    assert detect_language(text, fallback="en") == "en"


def test_prompts_name_only_one_language() -> None:
    assert "English" in system_prompt("en")
    assert "Arabic" not in system_prompt("en")
    assert "العربية" in system_prompt("ar")
