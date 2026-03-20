"""
Format detector — classifies uploaded documents as PDF, DOCX, or TXT.

Supported formats (PDF/DOCX/TXT only — see docs/lessons.md):
  - PDF  → magic bytes ``%PDF`` at offset 0
  - DOCX → ZIP magic ``PK\\x03\\x04`` with ``word/document.xml`` inside
  - TXT  → no binary magic; no null bytes in the first 8 KiB

Everything else raises ``UnsupportedFormatError``.

Usage::

    from platform.parsers.format_detector import detect_format, DocumentFormat

    result = detect_format(Path("requirements.pdf"))
    assert result.format == DocumentFormat.PDF
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from platform.observability.logger import get_logger
from platform.schemas.errors import UnsupportedFormatError  # noqa: F401 — re-exported

__all__ = [
    "detect_format",
    "DocumentFormat",
    "DetectionResult",
    "UnsupportedFormatError",
]

log = get_logger(__name__)

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"
_READ_BYTES = 8192  # header window for detection


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DocumentFormat(StrEnum):
    """Document formats the platform can process."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"


@dataclass(frozen=True)
class DetectionResult:
    """Result of a successful format detection.

    Attributes:
        format: The detected document format.
        path:   The inspected file path.
        mime:   MIME type string for the detected format.
    """

    format: DocumentFormat
    path: Path
    mime: str


_MIME: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: "application/pdf",
    DocumentFormat.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    DocumentFormat.TXT: "text/plain",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_format(path: Path) -> DetectionResult:
    """Detect the format of a document file by inspecting its content.

    Detection is purely content-based (magic bytes / null-byte heuristic),
    never by file extension.

    Args:
        path: Path to the file to inspect.

    Returns:
        ``DetectionResult`` with the detected format and MIME type.

    Raises:
        ``UnsupportedFormatError``: File is empty, binary, or not PDF/DOCX/TXT.
    """
    header = _read_header(path)

    if header.startswith(_PDF_MAGIC):
        fmt = DocumentFormat.PDF
    elif header.startswith(_ZIP_MAGIC):
        fmt = _resolve_zip(path)
    elif _is_text(header):
        fmt = DocumentFormat.TXT
    else:
        log.warning("format_detector_rejected", file=str(path), reason="binary_no_magic")
        raise UnsupportedFormatError(filename=path.name, detected_mime=None)

    log.debug("format_detector_detected", file=str(path), format=fmt.value)
    return DetectionResult(format=fmt, path=path, mime=_MIME[fmt])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _read_header(path: Path) -> bytes:
    """Read the first ``_READ_BYTES`` bytes; raise if file is empty or unreadable."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UnsupportedFormatError(filename=path.name, detected_mime=None) from exc

    if not data:
        raise UnsupportedFormatError(filename=path.name, detected_mime=None)

    return data[:_READ_BYTES]


def _resolve_zip(path: Path) -> DocumentFormat:
    """Return DOCX if the ZIP contains ``word/document.xml``, else raise."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise UnsupportedFormatError(filename=path.name, detected_mime="application/zip") from exc

    if "word/document.xml" in names:
        return DocumentFormat.DOCX

    detected_mime = (
        "application/vnd.ms-excel" if any(n.startswith("xl/") for n in names) else "application/zip"
    )
    log.warning("format_detector_zip_rejected", file=str(path), names_sample=names[:5])
    raise UnsupportedFormatError(filename=path.name, detected_mime=detected_mime)


def _is_text(data: bytes) -> bool:
    """Return True when data contains no null bytes (binary-detection heuristic)."""
    return b"\x00" not in data
