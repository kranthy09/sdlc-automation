"""
TDD — platform/parsers/format_detector.py

Tests cover the six behaviours that matter:
  - PDF magic bytes (%PDF)         → DocumentFormat.PDF
  - DOCX (ZIP + word/document.xml) → DocumentFormat.DOCX
  - Plain UTF-8 text               → DocumentFormat.TXT
  - Unknown binary (null bytes)    → UnsupportedFormatError
  - Empty file                     → UnsupportedFormatError
  - XLSX (ZIP but no word/ dir)    → UnsupportedFormatError

All tests use tmp_path fixtures and write raw bytes — no real file dependencies.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_docx(path: Path) -> None:
    """Write a minimal valid DOCX to *path* (ZIP with word/document.xml)."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("[Content_Types].xml", "<Types/>")
    path.write_bytes(buf.getvalue())


def _make_xlsx(path: Path) -> None:
    """Write a minimal XLSX to *path* (ZIP with xl/ but no word/)."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("[Content_Types].xml", "<Types/>")
    path.write_bytes(buf.getvalue())


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_pdf(tmp_path: Path) -> None:
    """Magic bytes %PDF → DocumentFormat.PDF with correct MIME."""
    from platform.parsers.format_detector import DocumentFormat, detect_format

    pdf = tmp_path / "reqs.pdf"
    pdf.write_bytes(b"%PDF-1.4 some body content here")

    result = detect_format(pdf)

    assert result.format == DocumentFormat.PDF
    assert result.mime == "application/pdf"


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_docx(tmp_path: Path) -> None:
    """ZIP with word/document.xml → DocumentFormat.DOCX."""
    from platform.parsers.format_detector import DocumentFormat, detect_format

    docx = tmp_path / "reqs.docx"
    _make_docx(docx)

    result = detect_format(docx)

    assert result.format == DocumentFormat.DOCX
    assert "wordprocessingml" in result.mime


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_txt(tmp_path: Path) -> None:
    """UTF-8 text with no null bytes → DocumentFormat.TXT."""
    from platform.parsers.format_detector import DocumentFormat, detect_format

    txt = tmp_path / "reqs.txt"
    txt.write_text("Requirement 1: the system must support three-way matching.", encoding="utf-8")

    result = detect_format(txt)

    assert result.format == DocumentFormat.TXT
    assert result.mime == "text/plain"


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rejects_unknown_binary(tmp_path: Path) -> None:
    """Binary file with null bytes and no known magic → UnsupportedFormatError."""
    from platform.parsers.format_detector import detect_format
    from platform.schemas.errors import UnsupportedFormatError

    unknown = tmp_path / "data.xyz"
    unknown.write_bytes(b"\x00\x00\x00\xff\xfe\xfa")

    with pytest.raises(UnsupportedFormatError) as exc_info:
        detect_format(unknown)

    assert exc_info.value.filename == "data.xyz"


@pytest.mark.unit
def test_rejects_empty_file(tmp_path: Path) -> None:
    """Empty file → UnsupportedFormatError (no content to detect from)."""
    from platform.parsers.format_detector import detect_format
    from platform.schemas.errors import UnsupportedFormatError

    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")

    with pytest.raises(UnsupportedFormatError):
        detect_format(empty)


@pytest.mark.unit
def test_rejects_xlsx(tmp_path: Path) -> None:
    """ZIP without word/document.xml (e.g. XLSX) → UnsupportedFormatError with MIME hint."""
    from platform.parsers.format_detector import detect_format
    from platform.schemas.errors import UnsupportedFormatError

    xlsx = tmp_path / "data.xlsx"
    _make_xlsx(xlsx)

    with pytest.raises(UnsupportedFormatError) as exc_info:
        detect_format(xlsx)

    assert "excel" in (exc_info.value.detected_mime or "").lower()
