FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace root files for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy all libs (needed for workspace resolution)
COPY libs/ libs/

# Copy OMS app
COPY apps/oms/ apps/oms/

# Install dependencies
RUN uv sync --frozen --package astraeus-oms --no-dev

# --- Runtime stage ---
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r astraeus && useradd -r -g astraeus astraeus

WORKDIR /app

# Copy installed packages and app from build stage
COPY --from=base /app /app
COPY --from=base /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=base /usr/local/bin /usr/local/bin

USER astraeus

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uv", "run", "uvicorn", "astraeus_oms.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
