# =============================================================================
# NEXA – Multi-stage Dockerfile
# =============================================================================

FROM python:3.12-slim AS base
LABEL maintainer="NEXA Engineering"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
FROM base AS builder
COPY pyproject.toml .
RUN pip install --upgrade pip && pip install ".[dev]" --prefix=/install

# ---------------------------------------------------------------------------
FROM base AS production

# Non-root user
RUN groupadd -r nexa && useradd -r -g nexa -d /app -s /sbin/nologin nexa

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=nexa:nexa app/ ./app/
COPY --chown=nexa:nexa alembic/ ./alembic/
COPY --chown=nexa:nexa alembic.ini .

USER nexa

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
