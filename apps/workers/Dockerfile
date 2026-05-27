# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.0 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/workers/pyproject.toml apps/workers/pyproject.toml
COPY libs/ libs/
COPY apps/workers/ apps/workers/

RUN uv sync --frozen --no-dev --package astraeus-workers

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system astraeus \
    && useradd --system --gid astraeus --create-home --home-dir /home/astraeus astraeus

WORKDIR /app
COPY --from=builder --chown=astraeus:astraeus /app /app

USER astraeus
CMD ["python", "-m", "astraeus_workers.main"]
