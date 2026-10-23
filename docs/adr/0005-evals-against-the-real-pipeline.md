# ADR 0005: Evals run the real pipeline, deterministically in CI

- Status: accepted
- Date: 2026-10-23

## Context

Retrieval and citations are the product: an answer that cites the wrong passage is worse than no answer. Changes
to parsing, chunking, ranking or prompts can quietly make that worse, and unit tests check mechanisms, not
quality. CI must never call a real model (it would be slow, flaky and costly), but a quality check that skips the
real code paths would prove little.

## Decision

- **A golden set** (`evals/golden.jsonl`): 42 questions over the demo policies, in English and Arabic, including
  cross-lingual questions (English about the Arabic policy and the reverse) and questions the documents cannot
  answer. Each answerable item names *evidence*: a short phrase the right passage contains.
- **Evidence phrases, not chunk ids.** Chunk ids are random per ingestion and change whenever chunking does, so
  an item matches any retrieved passage that contains its evidence (after the same Arabic normalization search
  uses). The set survives chunking changes and stays readable.
- **The harness runs production code:** the worker's parser, chunker and embedder ingest the PDFs into a real
  Postgres; the API's hybrid `retrieve()` searches; the answer comes from the configured `LLMProvider` with the
  chat agent's system prompt, sources block and streaming `CitationFilter`.
- **Metrics:** recall@6 (the evidence was retrieved), citation precision (cited passages contain the evidence),
  faithfulness (cited sentences' content words mostly appear in what they cite), plus answer correctness and
  abstention on unanswerable questions, which are reported but not gated.
- **CI runs it deterministically** with `FakeProvider` and fake embeddings and fails below 0.85 recall, 0.80
  faithfulness and the citation-precision gate. The fake model always cites source 1, so in CI citation
  precision is the precision@1 of retrieval and its gate is 0.80; with a real model the gate is 0.85.
  Cross-lingual items need a multilingual embedder and are skipped with the fake one.
- **Real models are evaluated on demand** with the same command (`make evals EVALS_ENV=...`).

## Consequences

- A regression in Arabic text extraction, chunking or ranking fails CI before it reaches users. The first run
  found one: Chromium-generated PDFs drop an alef before a lam-alef ligature, which broke keyword search on
  words like الاعتماد.
- Faithfulness is lexical. It is cheap and deterministic but underrates good paraphrases, especially in Arabic;
  an LLM judge would measure it better at the cost of a model in the loop, so it is left for on-demand runs.
- The demo corpus is small (14 passages). The set is a regression guard, not a benchmark; it grows with the
  corpus.
