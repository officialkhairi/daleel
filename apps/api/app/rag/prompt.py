"""How retrieved passages are shown to the model. Sources are numbered from 1 in rank order and
the model cites them as [n]."""

from html import escape

from app.chat.language import Language
from app.rag.retrieve import RetrievedChunk

_INSTRUCTIONS: dict[Language, str] = {
    "en": (
        "Answer using only the numbered sources below. After every sentence that uses a source, "
        "cite it with its number in square brackets, like [1] or [2][3]. If the sources do not "
        "contain the answer, say that you could not find it in the documents. The sources may be "
        "in Arabic or English; answer in English either way."
    ),
    "ar": (
        "أجب اعتمادًا على المصادر المرقمة أدناه فقط. بعد كل جملة تستند إلى مصدر، اذكر رقمه بين "
        "قوسين معقوفين مثل [1] أو [2][3]. إذا لم تتضمن المصادر الإجابة فقل إنك لم تجدها في "
        "المستندات. قد تكون المصادر بالعربية أو الإنجليزية؛ أجب بالعربية في الحالتين."
    ),
}


def sources_prompt(chunks: list[RetrievedChunk], language: Language) -> str:
    """Appended to the system prompt. Text inside <source> is escaped, so a document cannot
    close the tag and pose as instructions."""
    parts = [_INSTRUCTIONS[language], "", "<sources>"]
    for n, chunk in enumerate(chunks, start=1):
        attrs = f'n="{n}" title="{escape(chunk.title)}"'
        if chunk.page is not None:
            attrs += f' page="{chunk.page}"'
        body = f"{chunk.heading}\n{chunk.text}" if chunk.heading else chunk.text
        parts.append(f"<source {attrs}>\n{escape(body, quote=False)}\n</source>")
    parts.append("</sources>")
    return "\n".join(parts)
