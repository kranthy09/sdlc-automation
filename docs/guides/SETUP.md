# Setup — Get Running in 5 Minutes

## Prerequisites

- Python 3.12+
- Docker + Docker Compose
- `.env` file (ask lead for template)

## Backend

```bash
# Clone and enter
cd /home/kranthi/Projects/enterprise_ai

# Install uv (if not already)
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.bashrc

# Create venv and install all extras (ml = pdfplumber/spaCy/qdrant; ocr = pdf2image/tesseract; dev = pytest/ruff/mypy)
uv sync --extra ml --extra ocr --extra dev

# Activate
source .venv/bin/activate

# Validate
make validate-contracts
```

> **OCR system packages** (required by the `ocr` extra):
> ```bash
> sudo apt-get install -y poppler-utils tesseract-ocr   # Debian/Ubuntu
> brew install poppler tesseract                         # macOS
> ```
> OCR is only used as a fallback for scanned/image-only PDF pages. The parser works without it — scanned pages are skipped with a DEBUG log.

## Frontend

```bash
cd ui
npm install
npm run dev
```

## Services (Docker)

```bash
docker-compose up -d
# Starts: PostgreSQL, Redis, Qdrant, Minio
```

## Verify

```bash
# Run tests
make test

# Run linter + type checker
make lint

# Run all CI gates
make validate-contracts && make lint && make test
```

## Where to Find What

| Need | Location |
|------|----------|
| Import rules, coding standards | [docs/specs/rules.md](../specs/rules.md) |
| REQFIT phases, prompts | [docs/specs/dynafit.md](../specs/dynafit.md) |
| API, DB schema, UI | [docs/specs/api.md](../specs/api.md) |
| Guardrails design | [docs/specs/guardrails.md](../specs/guardrails.md) |
| Component details | [docs/INDEX.md](../INDEX.md) → Components |

## Troubleshooting

**Import errors?** Run `make validate-contracts` — check output for boundary violations.

**Type errors?** Run `make lint` — mypy will show exact line.

**Tests fail?** Check `.env` is correct and services are running.
