"""
Integration test — G2 (PII Redactor) + G11 (Response PII Scanner) + pipeline wiring.

Validates:
  1. redact → restore roundtrip (platform layer)
  2. response PII scanning (platform layer)
  3. pipeline wiring: ingestion redacts, classification scans, Phase 5 flags + de-redacts
  4. tasks.py review_reason mapping for pii_detected
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _force_regex_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use regex fallback so tests run without presidio installed."""
    import platform.guardrails.pii_redactor as mod

    monkeypatch.setattr(mod, "_analyzer", None)
    monkeypatch.setattr(mod, "_presidio_available", False)


@pytest.mark.integration
def test_redact_and_restore_roundtrip() -> None:
    """G2: redact PII then restore — original text is fully recovered."""
    from platform.guardrails import redact_pii, restore_pii

    original = (
        "Contact john.doe@example.com or call 555-123-4567. "
        "SSN is 123-45-6789. Server at 10.0.0.1."
    )
    result = redact_pii(original)

    assert result.entity_count >= 3
    assert "john.doe@example.com" not in result.redacted_text
    assert "555-123-4567" not in result.redacted_text
    assert "123-45-6789" not in result.redacted_text

    restored = restore_pii(result.redacted_text, result.redaction_map)
    assert restored == original


@pytest.mark.integration
def test_clean_text_passes_through() -> None:
    """G2: text without PII returns unchanged with empty map."""
    from platform.guardrails import redact_pii

    text = "The system shall support multi-currency transactions in D365."
    result = redact_pii(text)

    assert result.entity_count == 0
    assert result.redacted_text == text
    assert result.redaction_map == {}


@pytest.mark.integration
def test_response_pii_scanner_detects_leak() -> None:
    """G11: LLM response containing PII is flagged for review."""
    from platform.guardrails import scan_response_pii

    llm_output = "Based on analysis, john@corp.com should configure the AP module."
    result = scan_response_pii(llm_output)

    assert result.has_pii is True
    assert result.action == "FLAG_FOR_REVIEW"
    assert result.entity_count >= 1


@pytest.mark.integration
def test_response_pii_scanner_clean_passes() -> None:
    """G11: clean LLM response passes without flagging."""
    from platform.guardrails import scan_response_pii

    llm_output = "This requirement maps to standard FIT with D365 AP configuration."
    result = scan_response_pii(llm_output)

    assert result.has_pii is False
    assert result.action == "PASS"
    assert result.entity_count == 0


@pytest.mark.integration
def test_csv_deredaction_via_write_fdd() -> None:
    """Phase 5: CSV writer restores PII placeholders to original values."""
    import csv
    import io
    import tempfile
    from pathlib import Path

    from platform.guardrails import redact_pii
    from platform.schemas.fitment import ClassificationResult, FitLabel, RouteLabel

    from modules.dynafit.nodes.validation_output import _MergedResult, _write_fdd_csv

    original_text = "Contact john.doe@example.com for AP setup."
    pii_result = redact_pii(original_text)

    result = ClassificationResult(
        atom_id="REQ-TEST-0001",
        requirement_text=pii_result.redacted_text,
        module="AP",
        country="US",
        wave=1,
        classification=FitLabel.FIT,
        confidence=0.92,
        rationale="Standard AP configuration.",
        route_used=RouteLabel.FAST_TRACK,
        llm_calls_used=1,
    )
    merged = [_MergedResult(result=result)]

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        tmp_path = f.name

    try:
        _write_fdd_csv(tmp_path, merged, pii_result.redaction_map)
        content = Path(tmp_path).read_text()
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 1
        assert "john.doe@example.com" in rows[0]["requirement"]
        assert "<PII_" not in rows[0]["requirement"]
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@pytest.mark.integration
def test_phase5_flags_pii_leak_in_caveats() -> None:
    """Phase 5: _check_flags detects G11 caveat and adds response_pii_leak flag."""
    from platform.schemas.fitment import ClassificationResult, FitLabel, RouteLabel

    from modules.dynafit.nodes.phase5_validation import ValidationNode
    from modules.dynafit.product_config import get_product_config

    node = ValidationNode(report_dir="/tmp/test_reports")

    result = ClassificationResult(
        atom_id="REQ-TEST-0002",
        requirement_text="Test requirement",
        module="AP",
        country="US",
        wave=1,
        classification=FitLabel.FIT,
        confidence=0.95,
        rationale="Good fit.",
        route_used=RouteLabel.FAST_TRACK,
        llm_calls_used=1,
        caveats=(
            "G11: PII detected in LLM response "
            "(1 entities: EMAIL_ADDRESS). Flagged for human review."
        ),
    )

    config = get_product_config("d365_fo")
    flags = node._check_flags(result, None, config)
    assert "response_pii_leak" in flags


@pytest.mark.integration
def test_review_reason_maps_pii_flag() -> None:
    """tasks.py: response_pii_leak flag maps to pii_detected review_reason."""
    from api.workers.tasks import _review_reason

    assert _review_reason(["response_pii_leak"]) == "pii_detected"
    assert _review_reason(["response_pii_leak", "low_confidence"]) == "pii_detected"
    assert _review_reason(["high_confidence_gap"]) == "anomaly"
    assert _review_reason(["low_confidence"]) == "low_confidence"
