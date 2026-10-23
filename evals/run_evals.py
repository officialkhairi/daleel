"""Golden-set evals for retrieval and grounded answers.

Ingests the demo policies (docs/demo) with the worker's real parser, chunker and embedder into a
throwaway Postgres, then for every question in golden.jsonl runs the API's hybrid retrieval and
asks the configured model, with the same system prompt, sources block and citation filter as the
chat agent. It reports:

- recall@k: answerable questions where a retrieved passage contains the expected evidence;
- citation precision: citations that point at a passage containing that evidence;
- faithfulness: cited sentences whose words are mostly found in the passages they cite;
- answer correctness: answers containing the expected key terms (reported, not gated);
- abstention: unanswerable questions answered without any citation (reported, not gated).

Fails (exit 1) when recall, citation precision or faithfulness is below its threshold.

    make evals                       # FakeProvider + fake embeddings, as in CI
    make evals EVALS_ENV="LLM_PROVIDER=openai_compat LLM_BASE_URL=http://localhost:11434/v1 \\
        LLM_MODEL=qwen2.5:3b EMBEDDINGS_PROVIDER=fake"

With fake (bag-of-words) embeddings retrieval is lexical only, so cross-lingual questions (an
English question about the Arabic policy) are skipped; a real embedder (bge-m3) runs them.
Set EVALS_DATABASE_URL to use an existing, migrated database instead of a Testcontainers one.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.language import Language, reply_note, system_prompt
from app.config import Settings
from app.db.models import ALL_ROLES, Document, Tenant
from app.db.session import make_engine, make_sessionmaker, tenant_session
from app.embeddings.base import Embedder
from app.embeddings.fake import normalize
from app.llm.base import ChatMessage, LLMProvider, TextDelta
from app.llm.factory import build_provider
from app.rag.citations import CitationFilter
from app.rag.prompt import sources_prompt
from app.rag.retrieve import RetrievedChunk, retrieve
from app.storage import ObjectStore
from daleel_worker.embedders import build_embedder
from daleel_worker.ingest import IngestDeps, ingest_document

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
DEMO_DIR = ROOT / "docs" / "demo"
DOCUMENTS = {
    "information-security-policy-en": "Information Security Policy",
    "procurement-policy-ar": "سياسة المشتريات والتعاقد مع الموردين",
}
APP_ROLE, APP_PASSWORD = "daleel_app", "evals-app-password"


# --- data -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    id: str
    lang: Language
    question: str
    evidence: list[str]
    answer: list[str]
    doc: str | None = None
    crosslingual: bool = False

    @property
    def answerable(self) -> bool:
        return bool(self.evidence)


@dataclass
class Result:
    item: Item
    skipped: str | None = None
    retrieved_hit: bool = False
    hit_rank: int | None = None
    citations: list[int] = field(default_factory=list)
    correct_citations: int = 0
    cited_sentences: int = 0
    supported_sentences: int = 0
    answer_ok: bool | None = None
    answer: str = ""
    error: str | None = None


def load_items(path: Path) -> list[Item]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(Item(**json.loads(line)))
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise SystemExit("golden.jsonl has duplicate ids")
    return items


# --- matching -------------------------------------------------------------------------------

_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"\w+")
_MARKERS = re.compile(r"\[\d+\]")
_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+(?!\[)|\n+")
# Arabic clitics that glue onto the next word (و, ال, ب, ل, ف and combinations).
_ARABIC_PREFIX = re.compile(r"^(?:و|ف)?(?:ب|ل|ك)?(?:ال)?(?=\w{3})")
_STOPWORDS = {
    "the", "and", "for", "are", "with", "that", "this", "must", "from", "what", "which", "who",
    "any", "all", "you", "your", "can", "has", "have", "into", "not", "only", "its", "their",
    "التي", "الذي", "على", "من", "في", "إلى", "الى", "عن", "او", "أو", "ان", "أن", "هذه", "ذلك",
}  # fmt: skip


def norm(text: str) -> str:
    return _SPACES.sub(" ", normalize(text)).strip()


def passage(chunk: RetrievedChunk) -> str:
    return norm(f"{chunk.heading or ''} {chunk.text}")


def supports(chunk: RetrievedChunk, item: Item) -> bool:
    text = passage(chunk)
    return all(norm(e) in text for e in item.evidence)


def content_words(text: str) -> set[str]:
    words = set()
    for word in _WORD.findall(norm(_MARKERS.sub(" ", text))):
        word = _ARABIC_PREFIX.sub("", word)
        if len(word) >= 3 and word not in _STOPWORDS:
            words.add(word)
    return words


def cited_sentences(answer: str) -> Iterator[tuple[str, list[int]]]:
    for sentence in _SENTENCE_END.split(answer):
        numbers = [int(n) for n in re.findall(r"\[(\d+)\]", sentence)]
        if numbers:
            yield sentence, numbers


# --- environment ----------------------------------------------------------------------------


@contextmanager
def database() -> Iterator[str]:
    if url := os.environ.get("EVALS_DATABASE_URL"):
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        owner_url = pg.get_connection_url()
        cfg = Config(str(API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_DIR / "app" / "db" / "migrations"))
        cfg.attributes["url"] = owner_url
        cfg.attributes["app_db_user"] = APP_ROLE
        command.upgrade(cfg, "head")
        sql = f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"
        result = pg.exec(["psql", "-U", pg.username, "-d", pg.dbname, "-c", sql])
        if result.exit_code != 0:
            raise RuntimeError(result.output)
        yield owner_url.replace(f"{pg.username}:{pg.password}@", f"{APP_ROLE}:{APP_PASSWORD}@")


class _Files:
    """The object store, for ingestion only: the demo files, read from disk."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes:
        return self.files[key]


class _NoProgress:
    """Ingestion publishes progress for the UI; nobody listens here."""

    async def publish(self, channel: str, message: str) -> int:
        return 0


async def ingest_demo(
    sessions: async_sessionmaker[AsyncSession], embedder: Embedder, tenant_id: uuid.UUID
) -> None:
    files = _Files()
    deps = IngestDeps(
        sessions=sessions,
        store=cast(ObjectStore, files),
        embedder=embedder,
        redis=cast(Redis, _NoProgress()),
    )
    async with tenant_session(sessions, tenant_id) as session:
        session.add(Tenant(id=tenant_id, slug=f"evals-{tenant_id}", name="Evals"))
    for name, title in DOCUMENTS.items():
        data = (DEMO_DIR / f"{name}.pdf").read_bytes()
        document_id = uuid.uuid4()
        files.files[str(document_id)] = data
        async with tenant_session(sessions, tenant_id) as session:
            session.add(
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    title=title,
                    filename=f"{name}.pdf",
                    content_type="application/pdf",
                    size_bytes=len(data),
                    sha256=uuid.uuid4().hex * 2,
                    s3_key=str(document_id),
                    acl_roles=list(ALL_ROLES),
                )
            )
        await ingest_document(deps, document_id, tenant_id)
        async with tenant_session(sessions, tenant_id) as session:
            document = await session.get(Document, document_id)
            if document is None or document.status != "ready":
                raise RuntimeError(f"ingesting {name} failed: {document and document.error}")
            print(f"ingested {name}: {document.chunk_count} chunks", file=sys.stderr)


# --- one question ---------------------------------------------------------------------------


async def answer(provider: LLMProvider, item: Item, chunks: list[RetrievedChunk]) -> str:
    """The model's answer as the user would see it: unretrieved citations removed."""
    system = f"{system_prompt(item.lang)}\n\n{sources_prompt(chunks, item.lang)}"
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=f"{item.question}\n\n{reply_note(item.lang)}"),
    ]
    citations = CitationFilter(valid=set(range(1, len(chunks) + 1)))
    parts: list[str] = []
    async for event in provider.stream(messages, ()):
        if isinstance(event, TextDelta):
            parts.append(citations.feed(event.text)[0])
    parts.append(citations.flush()[0])
    return "".join(parts)


async def evaluate(
    item: Item,
    *,
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    embedder: Embedder,
    provider: LLMProvider,
    tenant_id: uuid.UUID,
) -> Result:
    result = Result(item)
    if item.crosslingual and settings.embeddings_provider == "fake":
        result.skipped = "cross-lingual needs a real embedder"
        return result
    chunks = await retrieve(
        sessions,
        tenant_id=tenant_id,
        roles=ALL_ROLES,
        query=item.question,
        embedder=embedder,
        candidates=settings.retrieval_candidates,
        top_k=settings.retrieval_top_k,
        rrf_k=settings.retrieval_rrf_k,
    )
    if item.answerable:
        ranks = [n for n, chunk in enumerate(chunks, start=1) if supports(chunk, item)]
        result.retrieved_hit = bool(ranks)
        result.hit_rank = ranks[0] if ranks else None
    try:
        text = await answer(provider, item, chunks)
    except Exception as exc:  # a model error counts against the item, not the whole run
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    result.answer = text
    numbers = [int(n) for n in re.findall(r"\[(\d+)\]", text)]
    result.citations = numbers
    if not item.answerable:
        return result

    result.correct_citations = sum(1 for n in numbers if supports(chunks[n - 1], item))
    for sentence, cited in cited_sentences(text):
        words = content_words(sentence)
        source_words = set().union(*(content_words(passage(chunks[n - 1])) for n in cited))
        result.cited_sentences += 1
        if not words or len(words & source_words) / len(words) >= 0.5:
            result.supported_sentences += 1
    if item.answer:
        result.answer_ok = all(norm(term) in norm(text) for term in item.answer)
    return result


# --- report ---------------------------------------------------------------------------------


def ratio(num: float, den: int) -> float | None:
    return num / den if den else None


def summarize(results: list[Result], k: int) -> dict[str, Any]:
    run = [r for r in results if r.skipped is None]
    answerable = [r for r in run if r.item.answerable]
    unanswerable = [r for r in run if not r.item.answerable and r.error is None]
    cited = sum(len(r.citations) for r in answerable)
    with_terms = [r for r in answerable if r.answer_ok is not None]
    return {
        f"recall@{k}": ratio(sum(r.retrieved_hit for r in answerable), len(answerable)),
        "mrr": ratio(sum(1 / r.hit_rank for r in answerable if r.hit_rank), len(answerable)) or 0,
        "citation_precision": ratio(sum(r.correct_citations for r in answerable), cited) or 0.0,
        "answers_with_citations": ratio(
            sum(bool(r.citations) for r in answerable), len(answerable)
        ),
        "faithfulness": ratio(
            sum(r.supported_sentences for r in answerable),
            sum(r.cited_sentences for r in answerable),
        )
        or 0.0,
        "answer_correctness": ratio(sum(bool(r.answer_ok) for r in with_terms), len(with_terms)),
        "abstention": ratio(sum(not r.citations for r in unanswerable), len(unanswerable)),
        "evaluated": len(run),
        "skipped": len(results) - len(run),
        "errors": sum(r.error is not None for r in results),
    }


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def markdown(
    summary: dict[str, Any], results: list[Result], gates: dict[str, float], model: str
) -> str:
    lines = [f"### Evals: `{model}`", "", "| Metric | Value | Gate |", "| --- | --- | --- |"]
    for key, value in summary.items():
        gate = gates.get(key)
        if isinstance(value, float) or value is None:
            mark = "" if gate is None else (" ✅" if (value or 0) >= gate else " ❌")
            lines.append(f"| {key} | {fmt(value)}{mark} | {'' if gate is None else f'≥ {gate}'} |")
        else:
            lines.append(f"| {key} | {value} | |")
    misses = [r for r in results if r.skipped is None and r.item.answerable and not r.retrieved_hit]
    wrong = [r for r in results if r.skipped is None and len(r.citations) > r.correct_citations]
    if misses or wrong or any(r.error for r in results):
        lines += ["", "| Item | Problem |", "| --- | --- |"]
        lines += [f"| {r.item.id} | evidence not retrieved |" for r in misses]
        lines += [
            f"| {r.item.id} | {len(r.citations) - r.correct_citations} of {len(r.citations)} "
            "citations miss the evidence |"
            for r in wrong
            if r.item.answerable
        ]
        lines += [f"| {r.item.id} | {r.error} |" for r in results if r.error]
    return "\n".join(lines)


async def run_all(items: list[Item], settings: Settings) -> list[Result]:
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    results = []
    async with httpx.AsyncClient() as http:
        embedder = build_embedder(settings, http)
        provider = build_provider(settings, http)
        tenant_id = uuid.uuid4()
        await ingest_demo(sessions, embedder, tenant_id)
        for item in items:
            result = await evaluate(
                item,
                sessions=sessions,
                settings=settings,
                embedder=embedder,
                provider=provider,
                tenant_id=tenant_id,
            )
            hit = "hit" if result.retrieved_hit else "miss"
            status = result.skipped or (hit if item.answerable else "unanswerable")
            print(f"{item.id:24} {status}  cites={result.citations}", file=sys.stderr)
            results.append(result)
    await engine.dispose()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--golden", type=Path, default=ROOT / "evals" / "golden.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "results" / "latest.json")
    parser.add_argument("--min-recall", type=float, default=0.85)
    parser.add_argument(
        "--min-citation-precision",
        type=float,
        help="Default 0.85; 0.80 with the fake model, which always cites source 1, so there the "
        "metric is the precision@1 of retrieval rather than the model's choice of sources.",
    )
    parser.add_argument("--min-faithfulness", type=float, default=0.8)
    parser.add_argument("--only", help="Run only items whose id contains this text.")
    args = parser.parse_args()

    items = [i for i in load_items(args.golden) if not args.only or args.only in i.id]
    # Outside the event loop: the migrations run their own.
    with database() as url:
        settings = Settings(database_url=url, oidc_issuer="unused", oidc_jwks_url="unused")
        results = asyncio.run(run_all(items, settings))

    k = settings.retrieval_top_k
    summary = summarize(results, k)
    gates = {
        f"recall@{k}": args.min_recall,
        "citation_precision": args.min_citation_precision
        or (0.80 if settings.llm_provider == "fake" else 0.85),
        "faithfulness": args.min_faithfulness,
    }
    model = f"{settings.llm_model} / embeddings {settings.embeddings_provider}"
    report = markdown(summary, results, gates, model)
    if settings.llm_provider == "fake":
        report += (
            "\n\nThe fake model always cites source 1, so citation precision here is the "
            "precision@1 of retrieval; run with a real model to measure its citations."
        )
    print(report)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "model": model,
                "summary": summary,
                "items": [
                    {
                        "id": r.item.id,
                        "skipped": r.skipped,
                        "retrieved": r.retrieved_hit,
                        "rank": r.hit_rank,
                        "citations": r.citations,
                        "correct_citations": r.correct_citations,
                        "answer_ok": r.answer_ok,
                        "error": r.error,
                        "answer": r.answer,
                    }
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    failed = [key for key, gate in gates.items() if (summary[key] or 0) < gate]
    if failed:
        print(f"FAILED: {', '.join(failed)} below the gate", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
