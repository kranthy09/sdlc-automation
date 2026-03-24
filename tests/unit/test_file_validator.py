"""
TDD — platform/guardrails/file_validator.py (G1-lite)

Behaviours under test:
  - PDF magic bytes         → is_valid=True, hash and size populated
  - Unsupported binary      → is_valid=False, rejection_reason="unsupported_format:..."
  - File over max_mb        → is_valid=False, rejection_reason="file_too_large:..."
  - SHA-256 hash accuracy   → matches hashlib.sha256(raw_bytes).hexdigest()
  - Hash present on rejected files → audit trail survives rejection
"""

from __future__ import annotations

import hashlib

import pytest


# ---------------------------------------------------------------------------
# Valid formats
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_pdf() -> None:
    """PDF magic bytes → accepted, hash and size populated."""
    from platform.guardrails.file_validator import validate_file

    data = b"%PDF-1.4 minimal content"
    result = validate_file(data, "requirements.pdf")

    assert result.is_valid is True
    assert result.rejection_reason is None
    assert result.size_bytes == len(data)
    assert len(result.file_hash) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# Format rejections
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rejects_binary_unknown() -> None:
    """Binary with null bytes and no magic → unsupported_format rejection."""
    from platform.guardrails.file_validator import validate_file

    result = validate_file(b"\x00\x01\x02\xff\xfe", "data.xyz")

    assert result.is_valid is False
    assert result.rejection_reason is not None
    assert result.rejection_reason.startswith("unsupported_format:")


# ---------------------------------------------------------------------------
# Size rejections
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rejects_oversized_file() -> None:
    """Valid PDF that exceeds max_mb → file_too_large rejection."""
    from platform.guardrails.file_validator import validate_file

    oversized = b"%PDF-1.4 " + b"x" * (3 * 1024 * 1024)  # ~3 MiB PDF
    result = validate_file(oversized, "large.pdf", max_mb=2)

    assert result.is_valid is False
    assert result.rejection_reason is not None
    assert result.rejection_reason.startswith("file_too_large:")


# ---------------------------------------------------------------------------
# Hash accuracy + audit trail
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_hash_matches_sha256() -> None:
    """file_hash == hashlib.sha256(raw_bytes).hexdigest() for a valid file."""
    from platform.guardrails.file_validator import validate_file

    data = b"%PDF-1.4 some content"
    result = validate_file(data, "test.pdf")

    assert result.file_hash == hashlib.sha256(data).hexdigest()


@pytest.mark.unit
def test_hash_present_on_rejected_file() -> None:
    """Rejected files still carry the SHA-256 hash for audit trail."""
    from platform.guardrails.file_validator import validate_file

    data = b"\x00\x00\xff\xfe"
    result = validate_file(data, "bad.bin")

    assert result.is_valid is False
    assert result.file_hash == hashlib.sha256(data).hexdigest()
