"""
TDD — platform/guardrails/file_validator.py (G1-lite)

Behaviours under test:
  - PDF magic bytes         → is_valid=True
  - DOCX (ZIP + word/)      → is_valid=True
  - Plain UTF-8 text        → is_valid=True
  - Unsupported binary      → is_valid=False, rejection_reason="unsupported_format:..."
  - Empty bytes             → is_valid=False, rejection_reason="unsupported_format:..."
  - File over max_mb        → is_valid=False, rejection_reason="file_too_large:..."
  - File exactly at limit   → is_valid=True  (> is strict; equal is allowed)
  - SHA-256 hash accuracy   → matches hashlib.sha256(raw_bytes).hexdigest()
  - Hash present on rejected files → audit trail survives rejection
"""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_docx_bytes() -> bytes:
    """Build minimal DOCX bytes (ZIP with word/document.xml)."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


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


@pytest.mark.unit
def test_valid_docx() -> None:
    """DOCX (ZIP + word/document.xml) → accepted."""
    from platform.guardrails.file_validator import validate_file

    result = validate_file(_make_docx_bytes(), "requirements.docx")

    assert result.is_valid is True
    assert result.rejection_reason is None


@pytest.mark.unit
def test_valid_txt() -> None:
    """Plain UTF-8 text → accepted."""
    from platform.guardrails.file_validator import validate_file

    data = b"System must support three-way matching for purchase invoices."
    result = validate_file(data, "requirements.txt")

    assert result.is_valid is True
    assert result.rejection_reason is None


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


@pytest.mark.unit
def test_rejects_empty_file() -> None:
    """Empty bytes → unsupported_format (detect_format raises on empty)."""
    from platform.guardrails.file_validator import validate_file

    result = validate_file(b"", "empty.pdf")

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


@pytest.mark.unit
def test_file_exactly_at_limit_is_valid() -> None:
    """File whose size == max_mb * 1024 * 1024 is not rejected (check is strict >)."""
    from platform.guardrails.file_validator import validate_file

    max_mb = 1
    exact_size = max_mb * 1024 * 1024
    # Build exactly exact_size bytes starting with PDF magic
    prefix = b"%PDF-1.4 "
    data = prefix + b"x" * (exact_size - len(prefix))
    assert len(data) == exact_size

    result = validate_file(data, "exact.pdf", max_mb=max_mb)

    assert result.is_valid is True


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
