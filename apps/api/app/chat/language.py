"""Which language an answer should be in. Decided here rather than left to the model: small models
can't reliably infer it, and naming both languages in the prompt pulls them toward the wrong one."""

from typing import Literal

Language = Literal["ar", "en"]

# Arabic, Arabic Supplement, Arabic Extended-A, Presentation Forms A and B.
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _is_arabic(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _ARABIC_RANGES)


def detect_language(text: str, *, fallback: Language) -> Language:
    """Arabic if the text has at least as many Arabic letters as Latin ones; `fallback` (the user's
    locale) when it has no letters at all, e.g. "?" or "123"."""
    arabic = latin = 0
    for ch in text:
        if not ch.isalpha():
            continue
        if _is_arabic(ch):
            arabic += 1
        elif ch.isascii():
            latin += 1
    if arabic == 0 and latin == 0:
        return fallback
    return "ar" if arabic >= latin else "en"


_PROMPTS: dict[Language, str] = {
    "en": (
        "You are Daleel, an assistant for enterprise documents. "
        "Reply in English. Use Markdown for lists, tables and emphasis. "
        "If you are not sure, say so plainly."
    ),
    "ar": (
        "أنت دليل، مساعد للمستندات المؤسسية. "
        "أجب باللغة العربية الفصحى. استخدم Markdown للقوائم والجداول والتأكيد. "
        "إذا لم تكن متأكدًا فقل ذلك بوضوح."
    ),
}


def system_prompt(language: Language) -> str:
    return _PROMPTS[language]


_REPLY_NOTES: dict[Language, str] = {"en": "(Reply in English.)", "ar": "(أجب باللغة العربية.)"}


def strip_reply_note(content: str) -> str:
    for note in _REPLY_NOTES.values():
        content = content.removesuffix(f"\n\n{note}")
    return content


def reply_note(language: Language) -> str:
    """Appended to the question in the prompt only (never stored). Small models follow the
    system prompt's language less once the history is in the other language; a note on the
    latest turn fixes that, and unlike a mid-conversation system message every chat template
    accepts it."""
    return _REPLY_NOTES[language]
