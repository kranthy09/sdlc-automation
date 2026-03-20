.PHONY: setup test test-unit test-integration test-module test-golden \
        lint validate-contracts dev dev-down seed-kb seed-corpus run ui ci

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup:
	uv sync --all-extras
	uv run pre-commit install
	uv run python -m spacy download en_core_web_lg

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	uv run pytest -x --cov=platform --cov=modules --cov=agents -v

test-unit:
	uv run pytest -m unit -v

test-integration:
	uv run pytest -m integration -v

test-module:
	uv run pytest modules/$(M)/tests/ -v

test-golden:
	uv run pytest -m golden -v

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy platform/ agents/ modules/ api/

format:
	uv run ruff check --fix .
	uv run ruff format .

validate-contracts:
	uv run python infra/scripts/validate_contracts.py

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
dev:
	docker compose -f infra/docker/docker-compose.yaml up -d
	@echo "Services starting: Qdrant :6333, Postgres :5432, Redis :6379, Prometheus :9090, Grafana :3001"

dev-down:
	docker compose -f infra/docker/docker-compose.yaml down

dev-logs:
	docker compose -f infra/docker/docker-compose.yaml logs -f

dev-ps:
	docker compose -f infra/docker/docker-compose.yaml ps

# ---------------------------------------------------------------------------
# Knowledge base seeding
# ---------------------------------------------------------------------------
seed-kb:
	uv run python -m infra.scripts.seed_knowledge_base --product $(PRODUCT)

seed-corpus:
	uv run python -m infra.scripts.seed_ms_learn_corpus --product $(PRODUCT)

# ---------------------------------------------------------------------------
# Running the platform
# ---------------------------------------------------------------------------
run:
	uv run uvicorn api.main:app --reload --port 8000

ui:
	cd ui && npm run dev

# ---------------------------------------------------------------------------
# CI gate (runs all quality checks)
# ---------------------------------------------------------------------------
ci: lint validate-contracts test
	@echo "CI passed — all gates green"
