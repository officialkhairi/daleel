# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY app ./app

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --no-create-home daleel
WORKDIR /app
COPY --from=build --chown=daleel:daleel /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --retries=20 \
  CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz').status != 200)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
