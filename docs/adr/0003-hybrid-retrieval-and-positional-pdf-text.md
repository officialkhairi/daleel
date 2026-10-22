# ADR 0003: Hybrid retrieval, and reading Arabic PDFs by position

- Status: accepted
- Date: 2026-10-23

## Context

Users ask in English or Arabic about documents in either language, and every claim must point at the exact
passage. Arabic text in PDFs is unreliable: generators often write glyphs in visual order and map ligatures back
to their letters in the wrong order, so naive extraction yields reversed words and misspellings, which break
keyword search and the snippets users see.

## Decision

- **Hybrid retrieval with reciprocal rank fusion.** Vector search (bge-m3, multilingual) finds paraphrases and
  crosses languages; keyword search (Postgres `tsvector` with the Arabic and English Snowball stemmers) finds
  exact terms, numbers and names that embeddings blur. RRF merges the two rankings without tuning score scales.
- **Everything in Postgres.** pgvector (HNSW) and full-text indexes sit next to the documents table, so tenant
  RLS and the role filter apply to both searches in the same SQL. No separate vector database to secure.
- **Positions are first-class.** Parsing keeps a page and a box for every block; chunks keep the boxes of their
  blocks. Citations carry them to the browser, which highlights them on the rendered page.
- **Arabic lines are rebuilt from character positions** rather than trusting the file's text order: sort by x
  (right to left), keep ligature parts together, restore left-to-right runs (numbers, Latin), and infer spaces
  from gaps.

## Alternatives considered

- **Vector-only retrieval.** Weak on exact figures ("500,000") and policy codes, which is most of what
  compliance questions hinge on.
- **A dedicated vector store (Qdrant, Weaviate).** Better at scale, but tenant and role filtering would be
  duplicated outside the database that owns them.
- **OCR every PDF.** Most reliable for Arabic, but slow and heavy; kept as a future fallback for scanned files.

## Consequences

- Retrieval quality depends on the embedding model; the default `fake` embedder behaves like keyword search.
- Positional reconstruction fixes the common cases but cannot restore letters a generator never recorded.
- Changing the embedding model means re-ingesting documents.
