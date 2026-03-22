# Enterprise AI Platform — FastAPI backend
# Build: docker build -t enterprise-ai-api .
# Run:   docker compose -f infra/docker/docker-compose.dev.yaml up api

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# System deps needed by ml extras (python-magic, spacy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (layer-cached)
# --mount=type=cache persists uv's package download cache across builds on the
# same machine — avoids re-downloading docling/spacy and other heavy ml deps
# every time pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml

# Copy application source
COPY . .

# Pre-download fastembed models (reads model names from product configs).
RUN uv run python -m infra.scripts.download_models

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uv", "run", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
