.PHONY: setup lock test test-unit test-integration test-module test-golden \
        lint format validate-contracts \
        dev dev-down dev-logs dev-ps db-migrate \
        seed-kb seed-kb-lite smoke-test run \
        ui ui-install test-ui test-ui-docker test-ui-coverage type-check-ui ci

# Single compose file for dev/MVP
COMPOSE := docker compose --env-file .env -f infra/docker/docker-compose.dev.yaml

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup:
	uv sync --extra dev --extra ml
	uv run pre-commit install
	uv run python -m spacy download en_core_web_lg

# Regenerate uv.lock after pyproject.toml changes, then make dev-full to rebuild
lock:
	uv lock

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	uv run python -m pytest -x --cov=platform --cov=modules -v

test-unit:
	uv run python -m pytest -m unit -v

test-integration:
	uv run python -m pytest -m integration -v

test-module:
	uv run python -m pytest modules/$(M)/tests/ -v

test-golden:
	uv run python -m pytest -m golden -v

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy platform/ modules/ api/

format:
	uv run ruff check --fix .
	uv run ruff format .

validate-contracts:
	uv run python infra/scripts/validate_contracts.py

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

dev:
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  UI          → http://localhost:5173"
	@echo "  API docs    → http://localhost:8000/api/docs"
	@echo "  API health  → http://localhost:8000/health"
	@echo "  Qdrant      → http://localhost:6333/dashboard"
	@echo ""

dev-down:
	$(COMPOSE) down

dev-down-v:
	$(COMPOSE) down -v


dev-logs:
	$(COMPOSE) logs -f

dev-ps:
	$(COMPOSE) ps

# Run pending SQL migrations inside the api container (on the Docker network).
# Tracks applied versions in schema_migrations — never re-runs a migration.
# Requires: make dev (stack must be up).
# Usage: make db-migrate
db-migrate:
	$(COMPOSE) exec api uv run python infra/scripts/migrate.py

# ---------------------------------------------------------------------------
# Knowledge base seeding
# ---------------------------------------------------------------------------
seed-kb:
	$(COMPOSE) exec api uv run python -m infra.scripts.seed_knowledge_base --product $(PRODUCT)

seed-kb-lite:
	$(COMPOSE) exec api uv run python -m infra.scripts.seed_knowledge_base --product d365_fo --source lite --reset

smoke-test:
	uv run python -m infra.scripts.smoke_test

# ---------------------------------------------------------------------------
# Running the platform locally (outside Docker)
# ---------------------------------------------------------------------------
run:
	uv run uvicorn api.main:app --reload --port 8000

ui-install:
	cd ui && npm install

ui:
	cd ui && npm run dev

test-ui:
	cd ui && npm test

test-ui-docker:
	docker compose --env-file .env -f infra/docker/docker-compose.ui-test.yaml run --rm ui-test

test-ui-coverage:
	cd ui && npm run test:coverage

type-check-ui:
	cd ui && npm run type-check

# ---------------------------------------------------------------------------
# CI gate
# ---------------------------------------------------------------------------
ci: lint validate-contracts test type-check-ui test-ui
	@echo "CI passed — all gates green"
