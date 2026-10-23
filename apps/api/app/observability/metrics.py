"""Prometheus metrics, scraped from GET /metrics (served on the API port only; nginx doesn't
expose it to browsers)."""

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "daleel_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "daleel_http_request_duration_seconds", "HTTP request duration", ["method", "route"]
)
RUNS = Counter("daleel_runs_total", "Finished run segments by outcome", ["status"])
RUN_TTFT = Histogram(
    "daleel_run_ttft_seconds",
    "Time from question to first answer token (includes retrieval)",
    ["model"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64),
)
LLM_TOKENS = Counter("daleel_llm_tokens_total", "Model tokens", ["model", "direction"])
LLM_COST = Counter("daleel_llm_cost_usd_total", "Estimated model cost (USD)", ["model"])
TOOL_CALLS = Counter("daleel_tool_calls_total", "Tool calls by outcome", ["tool", "outcome"])
APPROVAL_DECISIONS = Counter(
    "daleel_approval_decisions_total", "Approval decisions", ["tool", "decision"]
)
CITATIONS_DROPPED = Counter(
    "daleel_citations_dropped_total", "Citation markers removed for unretrieved sources"
)
RETRIEVAL_SECONDS = Histogram("daleel_retrieval_seconds", "Hybrid retrieval duration")
