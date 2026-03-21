"""
Lite API contract tests for DYNAFIT routes.

Mark: unit — no Docker required.
All external deps (Celery, disk format detection) are handled via:
  - real file I/O to /tmp (fast, always available)
  - _dispatch patched to a no-op
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

import api.routes.dynafit as routes_module
from api.main import app

BASE = "/api/v1"


@pytest.fixture(autouse=True)
def clear_stores() -> None:  # type: ignore[return]
    routes_module._uploads.clear()
    routes_module._batches.clear()
    yield  # type: ignore[misc]
    routes_module._uploads.clear()
    routes_module._batches.clear()


@pytest.fixture
async def client() -> AsyncClient:  # type: ignore[return]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c  # type: ignore[misc]


@pytest.fixture
def seeded_batch() -> str:
    routes_module._batches["bat_abc123"] = {
        "batch_id": "bat_abc123",
        "upload_id": "upl_test01",
        "upload_filename": "reqs.pdf",
        "country": "DE",
        "wave": 3,
        "status": "complete",
        "results": [
            {
                "atom_id": "REQ-AP-001",
                "requirement_text": "Three-way matching",
                "classification": "FIT",
                "confidence": 0.94,
                "module": "AccountsPayable",
                "country": "DE",
                "wave": 3,
                "rationale": "D365 supports it natively.",
                "reviewer_override": False,
            }
        ],
        "review_items": [
            {
                "atom_id": "REQ-AP-055",
                "requirement_text": "Custom vendor scorecard",
                "ai_classification": "GAP",
                "ai_confidence": 0.58,
                "ai_rationale": "No standard composite scoring.",
                "review_reason": "low_confidence",
                "reviewed": False,
            }
        ],
        "summary": {"total": 1, "fit": 1, "partial_fit": 0, "gap": 0},
        "report_path": None,
        "created_at": "2026-03-21T10:00:00+00:00",
        "completed_at": "2026-03-21T10:05:00+00:00",
    }
    return "bat_abc123"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_upload_pdf_success(client: AsyncClient) -> None:
    resp = await client.post(
        f"{BASE}/upload",
        files={"file": ("reqs.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={"product": "d365_fo", "country": "DE", "wave": "3"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["detected_format"] == "PDF"
    assert body["filename"] == "reqs.pdf"
    assert body["status"] == "uploaded"
    assert body["upload_id"].startswith("upl_")


@pytest.mark.unit
async def test_upload_invalid_format_rejected(client: AsyncClient) -> None:
    # Valid ZIP magic but not a DOCX → UnsupportedFormatError → 422
    resp = await client.post(
        f"{BASE}/upload",
        files={"file": ("data.zip", io.BytesIO(b"PK\x03\x04garbage"), "application/zip")},
        data={"product": "d365_fo", "country": "DE", "wave": "3"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_run_queues_pipeline(client: AsyncClient) -> None:
    routes_module._uploads["upl_test01"] = {
        "upload_id": "upl_test01",
        "filename": "reqs.pdf",
        "size_bytes": 100,
        "detected_format": "PDF",
        "path": "/tmp/reqs.pdf",
        "product": "d365_fo",
        "country": "DE",
        "wave": 3,
    }
    with patch.object(routes_module, "_dispatch") as mock_dispatch:
        resp = await client.post(
            f"{BASE}/d365_fo/dynafit/run",
            json={"upload_id": "upl_test01"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["batch_id"].startswith("bat_")
    mock_dispatch.assert_called_once()


@pytest.mark.unit
async def test_run_unknown_upload_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        f"{BASE}/d365_fo/dynafit/run",
        json={"upload_id": "upl_missing"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_results(client: AsyncClient, seeded_batch: str) -> None:
    resp = await client.get(f"{BASE}/d365_fo/dynafit/{seeded_batch}/results")
    assert resp.status_code == 200
    body = resp.json()
    assert body["batch_id"] == seeded_batch
    assert len(body["results"]) == 1
    assert body["results"][0]["classification"] == "FIT"


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_submit_review_approve(client: AsyncClient, seeded_batch: str) -> None:
    resp = await client.post(
        f"{BASE}/d365_fo/dynafit/{seeded_batch}/review/REQ-AP-055",
        json={"decision": "APPROVE", "reviewer": "s.weber@abc.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_classification"] == "GAP"
    assert body["reviewer_override"] is False
    assert body["remaining_reviews"] == 0


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_batches(client: AsyncClient, seeded_batch: str) -> None:
    resp = await client.get(f"{BASE}/d365_fo/dynafit/batches")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["batches"]) == 1
    assert body["batches"][0]["status"] == "complete"
    assert body["batches"][0]["country"] == "DE"
