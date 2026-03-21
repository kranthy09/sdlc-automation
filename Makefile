.PHONY: setup test test-unit test-integration test-module test-golden \
        lint validate-contracts \
        services services-down services-logs services-ps \
        dev dev-down dev-logs dev-ps \
        seed-kb seed-corpus run \
        ui ui-install test-ui test-ui-coverage type-check-ui ci

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup:
	uv sync --extra dev --extra ml
	uv run pre-commit install
	uv run python -m spacy download en_core_web_lg

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	uv run python -m pytest -x --cov=platform --cov=modules --cov=agents -v

test-unit:
	uv run python -m pytest -m unit -v

test-integration:
	uv run python -m pytest -m integration -v

test-module:
	uv run python -m pytest modules/$(M)/tests/ -v

test-golden:
	uv run python -m pytest -m golden -v

test-phase3:
	uv run python -m pytest tests/integration/test_phase3.py -v

test-phase4:
	uv run python -m pytest tests/unit/test_phase4_prompts.py tests/integration/test_phase4.py -v

test-api:
	uv run python -m pytest tests/unit/test_api_dynafit.py tests/unit/test_api_workers.py -v

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
services:
	docker compose -f infra/docker/docker-compose.services.yaml up -d
	@echo "Services ready: Postgres :5432  Redis :6379  Qdrant :6333"

services-down:
	docker compose -f infra/docker/docker-compose.services.yaml down

services-logs:
	docker compose -f infra/docker/docker-compose.services.yaml logs -f

services-ps:
	docker compose -f infra/docker/docker-compose.services.yaml ps

# Full stack (services + observability)
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

ui-install:
	cd ui && npm install

ui:
	cd ui && npm run dev

test-ui:
	cd ui && npm test

test-ui-coverage:
	cd ui && npm run test:coverage

type-check-ui:
	cd ui && npm run type-check

# ---------------------------------------------------------------------------
# CI gate (runs all quality checks)
# ---------------------------------------------------------------------------
ci: lint validate-contracts test
	@echo "CI passed — all gates green"
