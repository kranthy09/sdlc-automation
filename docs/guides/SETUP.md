# Setup — Get Running in 5 Minutes

## Prerequisites

- Python 3.12+
- Docker + Docker Compose
- `.env` file (ask lead for template)

## Backend

```bash
# Clone and enter
cd /home/kranthi/Projects/enterprise_ai

# Create venv
python3.12 -m venv .venv
source .venv/bin/activate

# Install deps
pip install -e .

# Validate
make validate-contracts
```

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
