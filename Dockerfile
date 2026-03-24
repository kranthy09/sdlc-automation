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

# Bake in the spaCy NER model required by presidio PII redactor (G2).
# uv pip install works without pip being installed as a Python module.
# en_core_web_sm must match the installed spaCy major.minor (3.8.x here).
RUN uv pip install \
    "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

# Pre-download fastembed models BEFORE copying all source so this layer is
# cached unless product_config.py or ProductConfig schema changes.
# Only the minimal files needed for model discovery are copied here.
COPY modules/__init__.py modules/__init__.py
COPY modules/dynafit/__init__.py modules/dynafit/__init__.py
COPY modules/dynafit/product_config.py modules/dynafit/product_config.py
COPY platform/__init__.py platform/__init__.py
COPY platform/schemas/__init__.py platform/schemas/__init__.py
COPY platform/schemas/product.py platform/schemas/product.py
COPY infra/__init__.py infra/__init__.py
COPY infra/scripts/__init__.py infra/scripts/__init__.py
COPY infra/scripts/download_models.py infra/scripts/download_models.py
RUN uv run python -m infra.scripts.download_models

# Copy application source (code changes only invalidate from here down)
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uv", "run", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
