# TDD Implementation Guide — Building DYNAFIT from Foundation

## MVP Testing Philosophy

**Goal: fast to market, high confidence in core value, low maintenance cost.**

| Layer | Test type | What to test |
|-------|-----------|--------------|
| Platform schemas | Unit | One valid case + invalid enum/range/required — trust Pydantic for the rest |
| Platform utilities | Unit | Complex logic only: error-path branching, counter accuracy, retry behaviour |
| Module nodes | Unit (mocked) | Non-trivial algorithms; skip simple pass-through nodes |
| End-to-end workflows | Integration | The critical user journeys (upload → classify → report) with real services |
| LLM calls | Golden fixture | Capture once, replay in CI — never live in CI |

**Do NOT write tests for:**
- Object construction ("can I instantiate X") — trust the import
- Simple defaults — they're in the schema definition, read it
- Every valid enum value — one valid + one invalid covers the contract
- Framework features: Pydantic `frozen`, `str_strip_whitespace`, SQLAlchemy sessions
- Duplicate-pattern validation (e.g. testing each missing required field separately)

**Write tests for:**
- Business rules: score ranges, wave ≥ 1, non-empty required text
- Error paths: exception re-raise, status="error" counter, transaction rollback
- Core journeys: requirement upload → fitment CSV output (integration)

---

> **Read CLAUDE.md before this file.** The build order here maps directly to the Layer 0–4
> sequence defined there. Do not skip layers. Do not start DYNAFIT before Layers 0–2 are done.
>
> **The starting point is not DYNAFIT. It is the platform.**
> DYNAFIT is the first module that proves the platform works.

---

## 0. Layer 0 — Scaffold + CI (Before Any Logic)

**Deliverable:** `make ci` passes on an empty codebase. Docker services start. Import boundary
validator runs. All of this before a single schema or parser is written.

### Step 0a: Initialize the monorepo

```bash
# Create project
mkdir enterprise-ai-platform && cd enterprise-ai-platform
git init
uv init --python 3.12

# Core structure
mkdir -p platform/{schemas,llm,retrieval,parsers,storage,observability,config,testing}
mkdir -p knowledge_bases/d365_fo/{seed_data,fdd_templates,code_rules,country_rules}
mkdir -p agents/{ingestion,rag,classifier,validator,code_analysis}
mkdir -p modules/dynafit/{prompts,tests}
mkdir -p api/{routes,middleware,workers,websocket}
mkdir -p ui
mkdir -p infra/{docker,helm,scripts}
mkdir -p tests/{unit,integration,fixtures}
mkdir -p docs/{architecture,module_drill_downs,runbooks}

# Touch __init__.py everywhere
find platform agents modules api -type d -exec touch {}/__init__.py \;
```

### Step 0b: Import Boundary Validator

This script runs in CI on every PR. Add it before writing any application code.

```python
# infra/scripts/validate_contracts.py
"""
Enforces architectural import rules and manifest schema references.
Fails with a clear error message indicating which rule was violated.
Run via: make validate-contracts
"""
import ast
import sys
from pathlib import Path

RULES = [
    # (importer_prefix, forbidden_import_prefixes, description)
    ("platform", ["agents", "modules", "api"],
     "platform/ cannot import from agents/, modules/, or api/"),
    ("agents", ["modules", "api"],
     "agents/ cannot import from modules/ or api/"),
]

def check_imports(root: Path) -> list[str]:
    violations = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root)
        parts = rel.parts
        if not parts:
            continue
        layer = parts[0]
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = node.names[0].name if node.names else ""
                for importer, forbidden_list, desc in RULES:
                    if layer == importer:
                        for forbidden in forbidden_list:
                            if module.startswith(forbidden):
                                violations.append(
                                    f"VIOLATION [{desc}]\n"
                                    f"  File: {rel}\n"
                                    f"  Import: {module}"
                                )
    return violations

def check_cross_module_imports(root: Path) -> list[str]:
    """No module may import from a sibling module."""
    violations = []
    modules_dir = root / "modules"
    if not modules_dir.exists():
        return violations
    module_names = [d.name for d in modules_dir.iterdir() if d.is_dir()]
    for py_file in modules_dir.rglob("*.py"):
        rel = py_file.relative_to(root)
        owning_module = rel.parts[1]  # modules/{this}/...
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = node.names[0].name if node.names else ""
                for other in module_names:
                    if other != owning_module and module.startswith(f"modules.{other}"):
                        violations.append(
                            f"VIOLATION [modules cannot import from sibling modules]\n"
                            f"  File: {rel}\n"
                            f"  Import: {module}"
                        )
    return violations

if __name__ == "__main__":
    root = Path(__file__).parent.parent.parent
    all_violations = check_imports(root) + check_cross_module_imports(root)
    if all_violations:
        print(f"\n{'='*60}")
        print("CONTRACT VIOLATIONS FOUND")
        print('='*60)
        for v in all_violations:
            print(f"\n{v}")
        print(f"\n{len(all_violations)} violation(s). Fix before merging.\n")
        sys.exit(1)
    print("All import contracts valid.")
```

### Step 0c: CI Workflow

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: ai_platform_test
          POSTGRES_USER: platform
          POSTGRES_PASSWORD: test_password
        ports: ["5432:5432"]
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
      qdrant:
        image: qdrant/qdrant:latest
        ports: ["6333:6333"]

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: make lint
      - run: make validate-contracts
      - run: make test
        env:
          POSTGRES_URL: postgresql+asyncpg://platform:test_password@localhost/ai_platform_test
          REDIS_URL: redis://localhost:6379/0
          QDRANT_URL: http://localhost:6333
```

**Layer 0 complete when:** `git push` triggers CI. All three gates (lint, validate-contracts, test) run and pass on the empty scaffold.

---

## 1. Layer 1 — Platform Schemas (The Contracts)

```toml
[project]
name = "enterprise-ai-platform"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Core
    "pydantic>=2.6",
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "langchain-anthropic>=0.3",
    "langfuse>=2.0",           # MIT, self-hosted — open-source LLM observability

    # Parsing (PDF, DOCX, TXT only — see docs/lessons.md)
    "docling>=2.0",

    # NLP
    "spacy>=3.7",
    "rapidfuzz>=3.6",

    # Vector / Retrieval
    "qdrant-client>=1.8",
    "sentence-transformers>=2.5",
    "rank-bm25>=0.2",

    # Storage
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "redis>=5.0",

    # API
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "celery[redis]>=5.3",

    # Observability
    "structlog>=24.1",
    "prometheus-client>=0.20",

    # Templating
    "jinja2>=3.1",

]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.3",
    "mypy>=1.8",
    "pre-commit>=3.6",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests", "modules/dynafit/tests"]
markers = [
    "unit: fast, no external deps",
    "integration: needs Docker services",
    "golden: uses golden fixture files",
    "llm: needs live LLM (skip in CI)",
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
```

### Step 1a: Write your FIRST test (before any implementation)

```python
# tests/unit/test_schemas.py
"""
TDD anchor: schemas must exist and validate correctly.
Write this FIRST, then implement to make it pass.
"""
import pytest
from pydantic import ValidationError


def test_requirement_atom_valid():
    """A well-formed requirement atom passes validation."""
    from platform.schemas.requirement import RequirementAtom
    
    atom = RequirementAtom(
        atom_id="REQ-AP-001",
        requirement_text="System must support three-way matching for purchase invoices",
        module="AccountsPayable",
        priority="MUST",
        country="DE",
        wave=2,
        source_ref="row_14:Sheet1",
        content_type="table",
        completeness_score=85.0,
    )
    assert atom.atom_id == "REQ-AP-001"
    assert atom.module == "AccountsPayable"


def test_requirement_atom_rejects_empty_text():
    """Requirement text cannot be empty."""
    from platform.schemas.requirement import RequirementAtom
    
    with pytest.raises(ValidationError):
        RequirementAtom(
            atom_id="REQ-AP-001",
            requirement_text="",  # must fail
            module="AccountsPayable",
            priority="MUST",
            country="DE",
            wave=2,
        )


def test_classification_result_valid():
    """Classification must be FIT, PARTIAL_FIT, or GAP."""
    from platform.schemas.fitment import ClassificationResult
    
    result = ClassificationResult(
        requirement_id="REQ-AP-001",
        classification="FIT",
        confidence=0.92,
        d365_capability_ref="cap-ap-0147",
        rationale="D365 standard AP module supports three-way matching natively.",
        d365_module="AccountsPayable",
        country="DE",
        wave=2,
    )
    assert result.classification == "FIT"
    assert result.confidence >= 0.7


def test_classification_rejects_invalid_type():
    """Classification must be one of the three allowed values."""
    from platform.schemas.fitment import ClassificationResult
    
    with pytest.raises(ValidationError):
        ClassificationResult(
            requirement_id="REQ-AP-001",
            classification="MAYBE",  # must fail
            confidence=0.5,
            d365_capability_ref="cap-ap-0147",
            rationale="unclear",
            d365_module="AccountsPayable",
            country="DE",
            wave=2,
        )
```

### Step 1b: Implement schemas to make tests pass

```python
# platform/schemas/base.py
from pydantic import BaseModel, ConfigDict


class PlatformModel(BaseModel):
    """Base for all platform schemas."""
    model_config = ConfigDict(
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )
```

```python
# platform/schemas/requirement.py
from typing import Literal
from pydantic import Field, field_validator
from .base import PlatformModel


class RequirementAtom(PlatformModel):
    """Single atomic business requirement, extracted from source docs."""
    atom_id: str
    requirement_text: str = Field(min_length=5)
    module: str
    priority: Literal["MUST", "SHOULD", "COULD", "WONT"] = "MUST"
    country: str = Field(pattern=r"^[A-Z]{2}$")
    wave: int = Field(ge=1)
    source_ref: str = ""
    content_type: Literal["table", "prose", "ocr", "user_story", "image_derived"] = "table"
    image_type: Literal["ARCHITECTURE_DIAGRAM", "SCREENSHOT", "CHART", "DATA_TABLE"] | None = None
    image_components: list[str] = Field(default_factory=list)  # systems/entities named in diagram
    original_lang: str = "en"
    completeness_score: float = Field(default=0.0, ge=0, le=100)
    ambiguity_flags: list[str] = Field(default_factory=list)

    @field_validator("requirement_text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("requirement_text cannot be blank")
        return v
```

```python
# platform/schemas/fitment.py
from typing import Literal
from pydantic import Field
from .base import PlatformModel


class ClassificationResult(PlatformModel):
    """Output of Phase 4: LLM classification of a single requirement."""
    requirement_id: str
    classification: Literal["FIT", "PARTIAL_FIT", "GAP"]
    confidence: float = Field(ge=0.0, le=1.0)
    d365_capability_ref: str
    rationale: str = Field(min_length=10)
    d365_module: str
    country: str
    wave: int
    caveats: list[str] = Field(default_factory=list)
    historical_match: bool = False


class ValidatedFitmentResult(PlatformModel):
    """Output of Phase 5: after human review + consistency check."""
    requirement_id: str
    requirement_text: str
    classification: Literal["FIT", "PARTIAL_FIT", "GAP"]
    confidence: float
    d365_capability_ref: str
    rationale: str
    d365_module: str
    country: str
    wave: int
    reviewer_override: bool = False
    override_reason: str = ""
```

Now run: `uv run pytest tests/unit/test_schemas.py -v`
All 4 tests pass. TDD is established from the first commit.

**Also write ProductConfig tests** — this is the multi-product key:

```python
# tests/unit/test_product_config.py
def test_product_config_d365():
    from platform.schemas.product import ProductConfig
    config = ProductConfig(
        product_id="d365_fo",
        display_name="Dynamics 365 Finance & Operations",
        llm_model="claude-sonnet-4-20250514",
        embedding_model="BAAI/bge-large-en-v1.5",
        capability_kb_namespace="d365_fo_capabilities",
        doc_corpus_namespace="d365_fo_docs",
        historical_fitments_table="d365_fo_fitments",
        fit_confidence_threshold=0.85,
        review_confidence_threshold=0.60,
        auto_approve_with_history=True,
        country_rules_path="knowledge_bases/d365_fo/country_rules/",
        fdd_template_path="knowledge_bases/d365_fo/fdd_templates/fit_template.j2",
        code_language="xpp",
    )
    assert config.fit_confidence_threshold == 0.85

def test_product_config_rejects_bad_threshold():
    from platform.schemas.product import ProductConfig
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ProductConfig(..., fit_confidence_threshold=1.5)  # must be 0–1
```

**Layer 1 complete when:** All schema tests pass. `mypy --strict` passes. `make validate-contracts` passes.

---

## 2. Layer 2 — Platform Utilities

Build each utility with TDD before DYNAFIT phases touch it.
Each test file follows RED → GREEN → REFACTOR before moving to the next component.

**Order matters** — observability before LLM client (so the client can log from birth):

```
platform/config/settings.py        → tests/unit/test_settings.py
platform/observability/logger.py   → tests/unit/test_logger.py
platform/observability/metrics.py  → tests/unit/test_metrics.py
platform/llm/client.py             → tests/unit/test_llm_client.py (mocked)
platform/retrieval/embedder.py     → tests/unit/test_embedder.py (mocked model)
platform/retrieval/vector_store.py → tests/integration/test_vector_store.py (real Qdrant)
platform/parsers/format_detector.py → tests/unit/test_format_detector.py
platform/parsers/docling_parser.py → tests/unit/test_docling_parser.py
platform/parsers/image_extractor.py → tests/unit/test_image_extractor.py (mocked vision LLM)
platform/storage/postgres.py       → tests/integration/test_postgres.py (real DB)
platform/storage/redis_pub.py      → tests/integration/test_redis_pub.py (real Redis)
platform/testing/factories.py      → no test (it IS the test helper)
```

**Layer 2 complete when:** `make test-unit` and `make test-integration` both pass.

---

## 3. Loading rules and knowledge into the platform

### Knowledge base structure (data, not code)

```yaml
# knowledge_bases/d365_fo/product_config.yaml
product_id: d365_fo
display_name: "Dynamics 365 Finance & Operations"

capability_kb_namespace: d365_fo_capabilities
doc_corpus_namespace: d365_fo_docs
historical_fitments_table: d365_fo_fitments

fit_confidence_threshold: 0.85
review_confidence_threshold: 0.60
auto_approve_with_history: true

fdd_template_path: knowledge_bases/d365_fo/fdd_templates/fit_template.j2
code_language: xpp
code_review_rules: knowledge_bases/d365_fo/code_rules/xpp_rules.yaml

embedding_model: BAAI/bge-large-en-v1.5
llm_model: claude-sonnet-4-20250514
classification_llm: claude-sonnet-4-20250514
country_rules_path: knowledge_bases/d365_fo/country_rules/
```

### Capability KB format (JSONL — one capability per line)

```jsonl
{"id": "cap-ap-0001", "module": "AccountsPayable", "feature": "Three-way matching", "description": "Validates purchase order, product receipt, and vendor invoice quantities and amounts before payment approval", "navigation": "AP > Invoices > Invoice matching", "version": "10.0.38"}
{"id": "cap-ap-0002", "module": "AccountsPayable", "feature": "Vendor invoice automation", "description": "Automated processing of vendor invoices with OCR capture, header/line recognition, and workflow routing", "navigation": "AP > Invoices > Pending vendor invoices", "version": "10.0.38"}
{"id": "cap-gl-0001", "module": "GeneralLedger", "feature": "Financial dimensions", "description": "Configurable dimension framework supporting cost center, department, business unit segmentation across all transactions", "navigation": "GL > Chart of accounts > Dimensions", "version": "10.0.38"}
```

### Seeding script (loads JSONL → Qdrant)

```python
# infra/scripts/seed_knowledge_base.py
"""
Load product knowledge base into Qdrant.
Usage: python -m infra.scripts.seed_knowledge_base --product d365_fo
"""
import json
import click
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

@click.command()
@click.option("--product", required=True, help="Product ID (e.g., d365_fo)")
def seed(product: str):
    config_path = Path(f"knowledge_bases/{product}/product_config.yaml")
    # ... load config, read JSONL, embed, upsert to Qdrant
    
    caps_path = Path(f"knowledge_bases/{product}/seed_data/capabilities.jsonl")
    model = SentenceTransformer("BAAI/bge-large-en-v1.5")
    client = QdrantClient(url="http://localhost:6333")
    
    # Create collection
    client.recreate_collection(
        collection_name=f"{product}_capabilities",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )
    
    # Load and embed
    points = []
    for i, line in enumerate(caps_path.read_text().splitlines()):
        cap = json.loads(line)
        text = f"{cap['feature']}: {cap['description']}"
        embedding = model.encode(text).tolist()
        points.append(PointStruct(
            id=i,
            vector=embedding,
            payload=cap,
        ))
    
    client.upsert(collection_name=f"{product}_capabilities", points=points)
    click.echo(f"Seeded {len(points)} capabilities into {product}_capabilities")

if __name__ == "__main__":
    seed()
```

---

## 4. Docker Compose — local dev stack

```yaml
# infra/docker/docker-compose.yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: ["qdrant_data:/qdrant/storage"]

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ai_platform
      POSTGRES_USER: platform
      POSTGRES_PASSWORD: dev_password
    ports: ["5432:5432"]
    volumes: ["pg_data:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3000:3000"]
    environment:
      DATABASE_URL: postgresql://platform:dev_password@postgres/langfuse
      NEXTAUTH_SECRET: dev_secret_change_in_prod
      NEXTAUTH_URL: http://localhost:3000
    depends_on: [postgres]

  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes: ["./prometheus.yml:/etc/prometheus/prometheus.yml"]

  grafana:
    image: grafana/grafana:latest
    ports: ["3001:3000"]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin

volumes:
  qdrant_data:
  pg_data:
```

---

## 5. TDD cycle for each DYNAFIT phase (Layer 3)

### The pattern: RED → GREEN → REFACTOR

For every phase, follow this exact order:

```
1. Write the test (it fails — RED)
2. Write minimal code to pass (GREEN)
3. Refactor for production quality (REFACTOR)
4. Add edge case tests (RED again)
5. Handle edge cases (GREEN)
6. Move to next step/phase
```

### Example: Phase 1, Step 1 — Format Detector

```python
# modules/dynafit/tests/test_phase1_format_detector.py
import pytest
from pathlib import Path


class TestFormatDetector:
    """TDD for Phase 1 · Step 1 · Sub-step A: Format Detector."""

    def test_detects_pdf(self, tmp_path):
        from platform.parsers.format_detector import detect_format, DocumentFormat
        
        pdf = tmp_path / "reqs.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        
        result = detect_format(pdf)
        assert result.format == DocumentFormat.PDF

    def test_detects_docx(self, tmp_path):
        from platform.parsers.format_detector import detect_format, DocumentFormat
        
        docx = tmp_path / "reqs.docx"
        docx.write_bytes(b"PK\x03\x04")
        # Differentiate from Excel by checking internal structure
        # In real test: create actual minimal DOCX
        
    def test_rejects_unknown_format(self, tmp_path):
        from platform.parsers.format_detector import detect_format, UnsupportedFormatError
        
        unknown = tmp_path / "data.xyz"
        unknown.write_bytes(b"\x00\x00\x00")
        
        with pytest.raises(UnsupportedFormatError):
            detect_format(unknown)

    def test_handles_empty_file(self, tmp_path):
        from platform.parsers.format_detector import detect_format, UnsupportedFormatError
        
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        
        with pytest.raises(UnsupportedFormatError):
            detect_format(empty)
```

Write the test → run it (fails) → implement `detect_format()` → run again (passes).

---

## 6. Golden fixtures for LLM testing

Never call live LLMs in CI. Instead, capture real responses once and replay them.

```python
# tests/fixtures/golden/phase4_classification.json
{
  "input": {
    "requirement_id": "REQ-AP-041",
    "requirement_text": "System must support three-way matching for purchase invoices",
    "top_capabilities": [
      {"id": "cap-ap-0001", "feature": "Three-way matching", "score": 0.94}
    ],
    "historical_precedent": {"wave_1_DE": "FIT", "confidence": 0.91}
  },
  "expected_output": {
    "classification": "FIT",
    "confidence_min": 0.85,
    "rationale_contains": ["three-way matching", "standard", "AP module"]
  }
}
```

```python
# tests/integration/test_phase4_golden.py
import json
import pytest
from pathlib import Path

GOLDEN_DIR = Path("tests/fixtures/golden")

@pytest.mark.golden
class TestClassificationGolden:
    
    @pytest.fixture
    def golden_cases(self):
        return json.loads((GOLDEN_DIR / "phase4_classification.json").read_text())
    
    def test_classification_matches_golden(self, golden_cases, mock_llm):
        """Classification output matches golden fixture expectations."""
        from modules.dynafit.nodes import classify_requirement
        
        result = classify_requirement(golden_cases["input"], llm=mock_llm)
        expected = golden_cases["expected_output"]
        
        assert result.classification == expected["classification"]
        assert result.confidence >= expected["confidence_min"]
        for term in expected["rationale_contains"]:
            assert term.lower() in result.rationale.lower()
```

---

## 7. Project documents to maintain for Claude Code

Keep these files in the repo root — Claude Code reads them automatically:

| File | Purpose | Update frequency |
|------|---------|-----------------|
| `CLAUDE.md` | Project intelligence — architecture, stack, conventions | Every major change |
| `docs/architecture.md` | System overview with diagrams | Monthly |
| `docs/module_drill_downs/dynafit.md` | Phase-by-phase technical deep dive | Per phase |
| `docs/adr/` | Architecture Decision Records | Per decision |
| `docs/runbooks/local_dev.md` | How to set up and run locally | As needed |
| `Makefile` | All commands in one place | Per new command |
| `CONTRIBUTING.md` | PR process, test requirements, code style | Rarely |

### Architecture Decision Record template

```markdown
# ADR-001: LangGraph for orchestration

## Status: Accepted

## Context
We need an agent orchestration framework that supports checkpointing,
human-in-the-loop interrupts, and conditional routing.

## Decision
Use LangGraph StateGraph as the orchestration spine.

## Consequences
+ Built-in checkpointing and resume
+ interrupt() for HITL at Phase 5
+ Typed state dictionary accumulates data across phases
- Learning curve for graph-based thinking
- Vendor coupling to LangChain ecosystem
```

---

## 8. Makefile — your command center

```makefile
.PHONY: setup test lint dev seed run ui

# Setup
setup:
	uv sync
	uv run pre-commit install
	uv run python -m spacy download en_core_web_lg

# Testing
test:
	uv run pytest -x --cov=platform --cov=modules --cov=agents -v

test-unit:
	uv run pytest -m unit -v

test-module:
	uv run pytest modules/$(M)/tests/ -v

test-golden:
	uv run pytest -m golden -v

# Quality
lint:
	uv run ruff check .
	uv run mypy platform/ modules/ agents/

validate-contracts:
	uv run python infra/scripts/validate_contracts.py

# Infrastructure
dev:
	docker compose -f infra/docker/docker-compose.yaml up -d

dev-down:
	docker compose -f infra/docker/docker-compose.yaml down

seed-kb:
	uv run python -m infra.scripts.seed_knowledge_base --product $(PRODUCT)

seed-corpus:
	uv run python -m infra.scripts.seed_ms_learn_corpus --product $(PRODUCT)

# Run
run:
	uv run uvicorn api.main:app --reload --port 8000

ui:
	cd ui && npm run dev

# Full pipeline
ci: lint test validate-contracts
```

---

## 9. Implementation order — what to build each week

> The week plan maps directly to CLAUDE.md Layers 0–4.
> A layer is not "done" until its tests pass and `make ci` is green.

### Week 1: Layer 0 + Layer 1 — Scaffold, CI, and Schemas

**Layer 0:**
- [ ] Monorepo directory structure + `__init__.py` everywhere
- [ ] `pyproject.toml` with all dependencies declared
- [ ] `Makefile` (all commands: setup, test, lint, dev, seed-kb, run, ci)
- [ ] `infra/docker/docker-compose.yaml` (Qdrant, Postgres+pgvector, Redis, Prometheus, Grafana)
- [ ] `.github/workflows/ci.yml` (lint + validate-contracts + test)
- [ ] `infra/scripts/validate_contracts.py` (import boundary + manifest checker)
- [ ] `pre-commit` hooks (ruff, mypy)
- [ ] `make ci` passes on empty scaffold ← **Layer 0 done**

**Layer 1:**
- [ ] `platform/schemas/base.py` — PlatformModel
- [ ] `platform/schemas/product.py` — ProductConfig (multi-product key)
- [ ] `platform/schemas/requirement.py` — RawUpload, RequirementAtom, ValidatedAtom
- [ ] `platform/schemas/retrieval.py` — RetrievalQuery, AssembledContext
- [ ] `platform/schemas/fitment.py` — MatchResult, ClassificationResult, ValidatedFitmentBatch
- [ ] `platform/schemas/events.py` — WebSocket message types
- [ ] `platform/schemas/errors.py` — typed error classes
- [ ] Schema tests (8+ tests: valid cases, invalid cases, cross-field rules)
- [ ] `mypy --strict` passes on all schemas ← **Layer 1 done**

### Week 2: Layer 2 — Platform Utilities

Build each utility TDD-first. Observability components come before LLM client.

- [ ] `platform/config/settings.py` + test
- [ ] `platform/observability/logger.py` + test (structlog JSON, correlation_id)
- [ ] `platform/observability/metrics.py` + test (Prometheus counters/histograms)
- [ ] `platform/llm/client.py` + test (mocked — retry, structured output, cost emit)
- [ ] `platform/retrieval/embedder.py` + test (mocked model)
- [ ] `platform/retrieval/vector_store.py` + integration test (real Qdrant)
- [ ] `platform/retrieval/bm25.py` + test
- [ ] `platform/retrieval/reranker.py` + test (mocked model)
- [ ] `platform/parsers/format_detector.py` + test
- [ ] `platform/parsers/docling_parser.py` + test
- [ ] `platform/storage/postgres.py` + integration test (real DB)
- [ ] `platform/storage/redis_pub.py` + integration test (real Redis)
- [ ] `platform/testing/factories.py` — mock LLM, Qdrant, Redis for all module tests
- [ ] `make test-unit` and `make test-integration` both pass ← **Layer 2 done**

### Week 3: Layer 3 — DYNAFIT Phases 1 + 2

Read `DYNAFIT_IMPLEMENTATION_SPEC.md` Phase 1 and Phase 2 sections before writing any node.

- [ ] `modules/dynafit/manifest.yaml`
- [ ] `modules/dynafit/schemas.py` — RequirementState TypedDict
- [ ] Phase 1 nodes: Format Detector → Table Extractor → Prose Splitter → Header Map → Atomizer → Intent Classifier → Module Tagger → Deduplicator → Term Aligner → Validator
- [ ] Phase 2 nodes: Query Builder → Parallel Retrieval → RRF Fusion → Cross-Encoder Rerank → Context Assembly
- [ ] Golden fixtures captured for Phases 1–2
- [ ] `make test-module M=dynafit` passes (no live LLM, no live infrastructure)

### Week 4: Layer 3 — DYNAFIT Phases 3 + 4 + 5 + Graph Wiring

Read `DYNAFIT_IMPLEMENTATION_SPEC.md` Phases 3–5 and LangGraph wiring sections.

- [ ] Phase 3 nodes: Multi-Signal Scorer → Composite Scorer + Router → Candidate Ranker
- [ ] Phase 4 nodes: Short-Circuit Check → Prompt Builder → LLM Reasoning Engine (FAST_TRACK/DEEP_REASON/GAP_CONFIRM) → Response Parser → Sanity Check
- [ ] Phase 5 nodes: Dependency Graph → Country Overrides → Confidence Filter → Human Review (HITL interrupt) → CSV Report Builder → Audit Trail → Prometheus Metrics
- [ ] `modules/dynafit/graph.py` — `build_dynafit_graph()` with PostgresSaver checkpoint
- [ ] `modules/dynafit/prompts/` — all Jinja2 templates
- [ ] End-to-end golden fixture test through all 5 phases
- [ ] `make test-module M=dynafit` passes fully ← **Layer 3 done**

### Week 5: RAG Sources + Knowledge Base + Integration Validation

Three RAG sources must be ready before any end-to-end test is meaningful.
See DYNAFIT_IMPLEMENTATION_SPEC.md "RAG Sources — When and How to Build" for full detail.

**Source A — D365 Capability KB (authored data, Qdrant):**
- [ ] `knowledge_bases/d365_fo/seed_data/capabilities.jsonl` — minimum 200 capabilities covering AP, GL, AR, Procurement
- [ ] `knowledge_bases/d365_fo/seed_data/header_synonyms.yaml`
- [ ] `knowledge_bases/d365_fo/seed_data/term_aligner.yaml`
- [ ] `knowledge_bases/d365_fo/country_rules/DE.yaml`, `FR.yaml`
- [ ] `make seed-kb PRODUCT=d365_fo` completes without error
- [ ] Verify: Qdrant `d365_fo_capabilities` collection has expected point count

**Source B — MS Learn Corpus (crawled docs, Qdrant):**
- [ ] `infra/scripts/seed_ms_learn_corpus.py` implemented (crawl → chunk → embed → upsert)
- [ ] `make seed-corpus PRODUCT=d365_fo` runs (~45 min first time)
- [ ] Verify: Qdrant `d365_fo_docs` collection populated with ~15K–25K chunks
- [ ] Monthly refresh cron documented in `docs/runbooks/corpus_refresh.md`

**Source C — Historical Fitments (auto-populated, PostgreSQL+pgvector):**
- [ ] `d365_fo_fitments` table created with `vector(1024)` column and HNSW index
- [ ] Phase 5 write-back implemented: `ValidatedFitmentResult` → postgres insert with embedding
- [ ] Verify write-back: after a test wave runs, table has rows, pgvector similarity query returns results
- [ ] Confirm consultant override records (`reviewer_override=TRUE`) rank first in Phase 2 retrieval

**Integration validation:**
- [ ] Integration tests with real data (20-requirement sample, all 3 sources live)
- [ ] Source A: top-1 capability score > 0.7 for known requirements
- [ ] Source B: at least 1 doc chunk returned per requirement
- [ ] Source C: empty on Wave 1, populated after Wave 1 completes
- [ ] Performance benchmark: 50 requirements < 2 min end-to-end (parallelized phases)
- [ ] `make validate-contracts` passes

### Week 6: Layer 4 — API + Workers + UI

Read `FRONTEND_BACKEND_SPEC.md` in full before writing any route.

- [ ] `api/main.py` — FastAPI app, router mounting, health check
- [ ] `api/routes/dynafit.py` — POST /upload, POST /run, GET /results, review endpoints, GET /report
- [ ] `api/workers/tasks.py` — Celery task invokes `build_dynafit_graph()`, emits Redis progress
- [ ] `api/websocket/progress.py` — subscribes Redis channel, forwards to WebSocket
- [ ] React UI: UploadPage, ProgressPage, ResultsPage, ReviewPage, DashboardPage
- [ ] Grafana dashboard: phase latency, LLM call count, LLM cost, human override rate
- [ ] Full end-to-end manual test: upload → progress → results → review → report
- [ ] `make ci` passes ← **Layer 4 done**

### Week 7: Extensibility Proof + Hardening

**This week is the real test.** If a second product requires platform changes, fix the platform first.

- [ ] Onboard product #2 (SAP S/4HANA or Power Platform stub) — zero platform changes
- [ ] `make validate-contracts` passes with two products registered
- [ ] Load test: 10 concurrent 50-requirement batches without errors
- [ ] Failure mode tests: Qdrant timeout, LLM malformed output, Celery worker crash, WebSocket reconnect
- [ ] LLM cost guardrail test: Prometheus alert fires at threshold
- [ ] Documentation: update `docs/architecture.md`, write `docs/runbooks/local_dev.md`
- [ ] ADR written for every key design decision (LangGraph choice, ProductConfig pattern, etc.)
