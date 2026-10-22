# syntax=docker/dockerfile:1.7
# Build context: repo root (the worker depends on the API package for models and config).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# bge-m3 in-process (sentence-transformers + CPU PyTorch). Set false for a slim image that uses
# EMBEDDINGS_PROVIDER=openai_compat or fake.
ARG LOCAL_EMBEDDINGS=true
WORKDIR /src
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/
COPY apps/api/app apps/api/app
COPY apps/api/alembic.ini apps/api/
COPY apps/worker/pyproject.toml apps/worker/uv.lock apps/worker/
COPY apps/worker/daleel_worker apps/worker/daleel_worker
WORKDIR /src/apps/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable $([ "$LOCAL_EMBEDDINGS" = "true" ] && echo "--extra local-embeddings")

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --create-home --home-dir /home/daleel daleel
# Same path as in the build stage: the venv's scripts have it baked into their shebangs.
COPY --from=build --chown=daleel:daleel /src/apps/worker/.venv /src/apps/worker/.venv
ENV PATH="/src/apps/worker/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HF_HOME=/models
RUN mkdir -p /models && chown daleel:daleel /models
USER 10001
WORKDIR /app
CMD ["arq", "daleel_worker.main.WorkerSettings"]
