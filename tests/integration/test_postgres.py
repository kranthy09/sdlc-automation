"""
Integration — platform/storage/postgres.py

Requires a PostgreSQL server with pgvector installed.
Set POSTGRES_URL=postgresql+asyncpg://user:pw@host/db to run.
Skip automatically when POSTGRES_URL is absent.

Tests cover:
  - ensure_schema is idempotent (no error on repeat call)
  - save_upload + update_upload_status round-trip
  - save_fitment + get_similar_fitments returns the nearest record
  - module filter narrows results to matching records only
  - reviewer overrides rank first within similar results
  - save_fitment rejects REVIEW_REQUIRED classification
  - get_similar_fitments returns [] when table is empty
  - Prometheus ok counter increments after successful save_fitment
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(index: int, dim: int = 1024) -> list[float]:
    """Return a 1024-dim unit vector with 1.0 at *index*, 0.0 elsewhere."""
    v = [0.0] * dim
    v[index % dim] = 1.0
    return v


def _make_result(
    atom_id: str,
    *,
    module: str = "AccountsPayable",
    country: str = "DE",
    wave: int = 1,
    classification: str = "FIT",
    confidence: float = 0.90,
) -> Any:
    from platform.schemas.fitment import ClassificationResult, FitLabel, RouteLabel

    return ClassificationResult(
        atom_id=atom_id,
        requirement_text="System must support three-way matching for purchase invoices.",
        module=module,
        country=country,
        wave=wave,
        classification=FitLabel(classification),
        confidence=confidence,
        rationale="D365 AP module handles this natively via standard configuration.",
        route_used=RouteLabel.FAST_TRACK,
    )


def _sample(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def postgres_url() -> str:
    url = os.getenv("POSTGRES_URL")
    if not url:
        pytest.skip("POSTGRES_URL not set — run 'make dev' to start PostgreSQL")
    return url


@pytest.fixture
async def store(postgres_url: str) -> Any:  # type: ignore[misc]
    """
    Fresh PostgresStore per test.

    Each call creates a new async engine (and therefore a new event loop
    binding — avoids cross-loop errors with pytest-asyncio auto mode).
    ensure_schema is idempotent so running it on every test is cheap after
    the first call. Tables are truncated for a clean baseline.
    """
    from sqlalchemy import text

    from platform.storage.postgres import PostgresStore

    s = PostgresStore(postgres_url, registry=CollectorRegistry())
    try:
        await s.ensure_schema()
    except Exception as exc:
        await s.dispose()
        pytest.skip(f"PostgreSQL not reachable or pgvector not installed: {exc}")

    async with s._get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE TABLE fitments, uploads RESTART IDENTITY"))

    yield s
    await s.dispose()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ensure_schema_is_idempotent(store: Any) -> None:
    """Second ensure_schema call must not raise."""
    await store.ensure_schema()


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_save_upload_and_update_status(store: Any) -> None:
    """save_upload inserts a row; update_upload_status changes the status column."""
    from sqlalchemy import text

    from platform.schemas.requirement import RawUpload

    upload = RawUpload(
        upload_id="up-001",
        filename="requirements.pdf",
        file_bytes=b"%PDF-1.4",
        product_id="d365_fo",
        country="DE",
        wave=1,
    )
    await store.save_upload(upload)
    await store.update_upload_status("up-001", "complete")

    engine = store._get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT status FROM uploads WHERE upload_id = 'up-001'"))
        ).one()
    assert row[0] == "complete"


@pytest.mark.integration
async def test_save_upload_is_idempotent(store: Any) -> None:
    """Duplicate save_upload (same upload_id) must not raise."""
    from platform.schemas.requirement import RawUpload

    upload = RawUpload(
        upload_id="up-dup",
        filename="dup.pdf",
        file_bytes=b"%PDF",
        product_id="d365_fo",
        wave=1,
    )
    await store.save_upload(upload)
    await store.save_upload(upload)  # ON CONFLICT DO NOTHING


# ---------------------------------------------------------------------------
# Fitments — save and retrieve
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_save_and_retrieve_similar_fitment(store: Any) -> None:
    """save_fitment persists a record; get_similar_fitments returns it as the top hit."""
    result = _make_result("REQ-AP-001")
    vec = _unit(0)

    await store.save_fitment(result, vec, upload_id="up-001", product_id="d365_fo")

    priors = await store.get_similar_fitments(vec, top_k=5)

    assert len(priors) == 1
    assert priors[0].atom_id == "REQ-AP-001"
    assert priors[0].classification == "FIT"
    assert priors[0].confidence == pytest.approx(0.90)
    assert priors[0].country == "DE"
    assert priors[0].wave == 1


@pytest.mark.integration
async def test_module_filter_narrows_results(store: Any) -> None:
    """module= filter excludes records from other modules."""
    await store.save_fitment(
        _make_result("REQ-AP-001", module="AccountsPayable"),
        _unit(0),
        upload_id="up-001",
        product_id="d365_fo",
    )
    await store.save_fitment(
        _make_result("REQ-GL-001", module="GeneralLedger"),
        _unit(1),
        upload_id="up-001",
        product_id="d365_fo",
    )

    results = await store.get_similar_fitments(_unit(0), top_k=10, module="AccountsPayable")

    assert all(p.atom_id == "REQ-AP-001" for p in results)
    assert not any(p.atom_id == "REQ-GL-001" for p in results)


# ---------------------------------------------------------------------------
# Reviewer override ranking
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reviewer_override_ranks_first(store: Any) -> None:
    """Consultant override ranks before an AI result even if it is less similar."""
    # REQ-AI is most similar to the query vector (unit(0))
    await store.save_fitment(
        _make_result("REQ-AI"),
        _unit(0),
        upload_id="up-001",
        product_id="d365_fo",
        reviewer_override=False,
    )
    # REQ-CONSULTANT is less similar (unit(1)) but has reviewer_override=True
    await store.save_fitment(
        _make_result("REQ-CONSULTANT"),
        _unit(1),
        upload_id="up-001",
        product_id="d365_fo",
        reviewer_override=True,
        consultant="john.doe",
    )

    priors = await store.get_similar_fitments(_unit(0), top_k=2)

    assert len(priors) == 2
    assert priors[0].atom_id == "REQ-CONSULTANT"
    assert priors[0].reviewer_override is True
    assert priors[0].consultant == "john.doe"
    assert priors[1].atom_id == "REQ-AI"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_save_fitment_rejects_review_required(store: Any) -> None:
    """save_fitment raises ValueError for REVIEW_REQUIRED classification."""
    result = _make_result("REQ-PENDING", classification="REVIEW_REQUIRED")

    with pytest.raises(ValueError, match="REVIEW_REQUIRED"):
        await store.save_fitment(result, _unit(0), upload_id="up-001", product_id="d365_fo")


@pytest.mark.integration
async def test_get_similar_fitments_empty_table(store: Any) -> None:
    """get_similar_fitments returns [] when no fitments exist."""
    priors = await store.get_similar_fitments(_unit(0), top_k=5)
    assert priors == []


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_prometheus_ok_metric_increments_on_save_fitment(postgres_url: str) -> None:
    """platform_external_calls_total{service=postgres, status=ok} increments on success."""
    from platform.storage.postgres import PostgresStore

    registry = CollectorRegistry()
    s = PostgresStore(postgres_url, registry=registry)
    await s.ensure_schema()

    # Use a unique atom_id so this test is independent of other table state
    result = _make_result(f"REQ-METRICS-{uuid.uuid4().hex[:8]}")
    await s.save_fitment(result, _unit(7), upload_id="up-metrics", product_id="d365_fo")

    value = _sample(
        registry,
        {"service": "postgres", "operation": "save_fitment", "status": "ok"},
    )
    assert value == 1.0
    await s.dispose()
