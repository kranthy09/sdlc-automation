"""
G1-lite: File Validator — MIME check + size cap + SHA-256 audit hash.

Called at the top of the Phase 1 ingestion node, before any bytes touch a parser.
Returns FileValidationResult; never raises. The caller decides how to handle
is_valid=False (typically: abort the node and emit an ErrorEvent).

Reuses:
  platform/parsers/format_detector.detect_format()  — magic-byte MIME detection
  hashlib (stdlib)                                   — SHA-256 digest
  tempfile (stdlib)                                  — ephemeral path for detect_format
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from platform.observability.logger import get_logger
from platform.parsers.format_detector import detect_format
from platform.schemas.errors import UnsupportedFormatError
from platform.schemas.guardrails import FileValidationResult

__all__ = ["validate_file"]

log = get_logger(__name__)


def validate_file(
    file_bytes: bytes,
    filename: str,
    max_mb: int = 50,
) -> FileValidationResult:
    """Validate that *file_bytes* is an acceptable document for the pipeline.

    Checks (in order):
    1. SHA-256 hash — computed first so the audit trail records rejected files too.
    2. Format check via detect_format() — rejects anything that is not PDF/DOCX/TXT.
    3. Size check — rejects files larger than *max_mb* MiB.

    Args:
        file_bytes: Raw bytes of the uploaded document.
        filename:   Original filename (used for the temp file suffix and log context).
        max_mb:     Maximum allowed file size in mebibytes.  Default 50 MiB.

    Returns:
        FileValidationResult with is_valid=True on success, or is_valid=False
        and a rejection_reason string on failure.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    size_bytes = len(file_bytes)

    # --- Format check ----------------------------------------------------------
    # detect_format() needs a Path.  Write bytes to a NamedTemporaryFile so the
    # existing magic-byte logic is reused without duplication.
    suffix = Path(filename).suffix or ".bin"
    tmp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(tmp_file.name)
    try:
        tmp_file.write(file_bytes)
        tmp_file.flush()
        tmp_file.close()
        detect_format(tmp_path)
    except UnsupportedFormatError as exc:
        log.warning(
            "file_validator_format_rejected",
            filename=filename,
            detected_mime=exc.detected_mime,
        )
        return FileValidationResult(
            file_hash=file_hash,
            size_bytes=size_bytes,
            is_valid=False,
            rejection_reason=f"unsupported_format: {exc.detected_mime or 'unknown'}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    # --- Size check ------------------------------------------------------------
    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        log.warning(
            "file_validator_size_rejected",
            filename=filename,
            size_bytes=size_bytes,
            max_bytes=max_bytes,
        )
        return FileValidationResult(
            file_hash=file_hash,
            size_bytes=size_bytes,
            is_valid=False,
            rejection_reason=f"file_too_large: {size_bytes} bytes exceeds {max_mb}MB limit",
        )

    log.debug("file_validator_accepted", filename=filename, size_bytes=size_bytes)
    return FileValidationResult(
        file_hash=file_hash,
        size_bytes=size_bytes,
        is_valid=True,
    )
