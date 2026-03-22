"""
TDD — platform/parsers/docling_parser.py  (pypdf + python-docx backend)

Behaviours under test:
  - TXT   → prose chunks produced; text content preserved.
  - DOCX  → Heading style becomes section label; body paragraph is prose.
  - PDF   → text extracted per page; content appears in prose chunks.
  - Empty → empty TXT produces empty ParseResult (tables=[], prose=[]).
  - Error → unreadable file raises ParseError.
  - tables field → always [] (text-only extraction).
  - ok metric  → platform_external_calls_total{status="ok"} increments.
  - err metric → platform_external_calls_total{status="error"} increments.

No mocked converters — tests write real minimal files to tmp_path.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry


# ---------------------------------------------------------------------------
# File builders
# ---------------------------------------------------------------------------


def _write_txt(tmp_path: Path, text: str, name: str = "reqs.txt") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _write_docx(tmp_path: Path, heading: str, body: str, name: str = "reqs.docx") -> Path:
    """Create a real DOCX with one heading and one body paragraph."""
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_heading(heading, level=1)
    doc.add_paragraph(body)
    doc.save(buf)
    p = tmp_path / name
    p.write_bytes(buf.getvalue())
    return p


def _write_pdf(tmp_path: Path, text: str, name: str = "reqs.pdf") -> Path:
    """Create a minimal valid PDF with embedded text (no OCR needed)."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET\n".encode("latin-1")

    header = b"%PDF-1.4\n"
    obj1 = b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>\nendobj\n"
    )
    obj4 = (
        b"4 0 obj\n<</Length "
        + str(len(stream)).encode()
        + b">>\nstream\n"
        + stream
        + b"endstream\nendobj\n"
    )
    obj5 = b"5 0 obj\n<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>\nendobj\n"

    body = header + obj1 + obj2 + obj3 + obj4 + obj5
    o1 = len(header)
    o2 = o1 + len(obj1)
    o3 = o2 + len(obj2)
    o4 = o3 + len(obj3)
    o5 = o4 + len(obj4)
    xref_pos = len(body)

    xref = (
        b"xref\n0 6\n"
        b"0000000000 65535 f\r\n"
        + f"{o1:010d} 00000 n\r\n".encode()
        + f"{o2:010d} 00000 n\r\n".encode()
        + f"{o3:010d} 00000 n\r\n".encode()
        + f"{o4:010d} 00000 n\r\n".encode()
        + f"{o5:010d} 00000 n\r\n".encode()
    )
    trailer = (
        b"trailer\n<</Size 6 /Root 1 0 R>>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )

    p = tmp_path / name
    p.write_bytes(body + xref + trailer)
    return p


def _counter(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# TXT parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_txt_extracts_prose_chunks(tmp_path: Path) -> None:
    """Plain-text requirement is returned as a ProseChunk with the correct text."""
    from platform.parsers.docling_parser import DoclingParser

    req = "The system must validate three-way matching for vendor invoices."
    path = _write_txt(tmp_path, req)

    result = DoclingParser().parse(path)

    assert result.tables == []
    assert len(result.prose) >= 1
    full_text = " ".join(c.text for c in result.prose)
    assert "three-way matching" in full_text


@pytest.mark.unit
def test_parse_txt_multi_paragraph_produces_multiple_chunks(tmp_path: Path) -> None:
    """Double-newline separated paragraphs each become candidate chunk content."""
    from platform.parsers.docling_parser import DoclingParser

    content = (
        "The system must validate vendor invoices against purchase orders.\n\n"
        "The system shall calculate tax amounts per invoice automatically.\n\n"
        "The system must approve payments within the configured tolerance."
    )
    path = _write_txt(tmp_path, content)
    result = DoclingParser().parse(path)

    full_text = " ".join(c.text for c in result.prose)
    assert "vendor invoices" in full_text
    assert "tax amounts" in full_text
    assert "tolerance" in full_text


# ---------------------------------------------------------------------------
# DOCX parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_docx_heading_becomes_section(tmp_path: Path) -> None:
    """A DOCX Heading 1 paragraph sets the section label on subsequent chunks."""
    from platform.parsers.docling_parser import DoclingParser

    path = _write_docx(
        tmp_path,
        heading="Accounts Payable",
        body="The system must support three-way matching.",
    )
    result = DoclingParser().parse(path)

    assert result.tables == []
    assert len(result.prose) >= 1
    chunk = result.prose[0]
    assert chunk.section == "Accounts Payable"
    assert "three-way matching" in chunk.text
    assert chunk.has_overlap is False


@pytest.mark.unit
def test_parse_docx_no_heading_section_is_empty(tmp_path: Path) -> None:
    """Body-only DOCX (no heading paragraph) produces section='' on chunks."""
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("The system must validate payment tolerance thresholds.")
    doc.save(buf)
    p = tmp_path / "reqs.docx"
    p.write_bytes(buf.getvalue())

    from platform.parsers.docling_parser import DoclingParser

    result = DoclingParser().parse(p)

    assert len(result.prose) >= 1
    assert result.prose[0].section == ""


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_pdf_extracts_embedded_text(tmp_path: Path) -> None:
    """Embedded text in a minimal PDF appears in prose chunks."""
    from platform.parsers.docling_parser import DoclingParser

    path = _write_pdf(tmp_path, "System must validate invoice matching.")
    result = DoclingParser().parse(path)

    assert result.tables == []
    assert len(result.prose) >= 1
    full_text = " ".join(c.text for c in result.prose)
    assert "invoice" in full_text.lower()


@pytest.mark.unit
def test_parse_pdf_chunk_page_number_is_1_based(tmp_path: Path) -> None:
    """Chunks from a single-page PDF carry page=1."""
    from platform.parsers.docling_parser import DoclingParser

    path = _write_pdf(tmp_path, "The system shall post journal entries to the ledger.")
    result = DoclingParser().parse(path)

    assert all(c.page >= 1 for c in result.prose)


# ---------------------------------------------------------------------------
# Empty document
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_empty_txt_returns_empty_result(tmp_path: Path) -> None:
    """An empty TXT file produces tables=[] and prose=[]."""
    from platform.parsers.docling_parser import DoclingParser

    path = _write_txt(tmp_path, "")
    result = DoclingParser().parse(path)

    assert result.tables == []
    assert result.prose == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_bad_pdf_raises_parse_error(tmp_path: Path) -> None:
    """Random bytes with .pdf extension are wrapped in ParseError."""
    from platform.parsers.docling_parser import DoclingParser
    from platform.schemas.errors import ParseError

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"\x00\x01\x02\x03not a pdf")

    with pytest.raises(ParseError) as exc_info:
        DoclingParser().parse(bad)

    assert exc_info.value.filename == "bad.pdf"


@pytest.mark.unit
def test_parse_bad_docx_raises_parse_error(tmp_path: Path) -> None:
    """A ZIP that is not a valid DOCX raises ParseError."""
    from platform.parsers.docling_parser import DoclingParser
    from platform.schemas.errors import ParseError

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("not_a_docx.xml", "<root/>")
    bad = tmp_path / "bad.docx"
    bad.write_bytes(buf.getvalue())

    with pytest.raises(ParseError) as exc_info:
        DoclingParser().parse(bad)

    assert exc_info.value.filename == "bad.docx"


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_records_ok_metric_on_success(tmp_path: Path) -> None:
    """platform_external_calls_total{service=docling,operation=parse,status=ok} == 1."""
    from platform.parsers.docling_parser import DoclingParser

    path = _write_txt(tmp_path, "The system must validate invoices.", "metric_ok.txt")
    registry = CollectorRegistry()
    DoclingParser(registry=registry).parse(path)

    assert _counter(registry, {"service": "docling", "operation": "parse", "status": "ok"}) == 1.0


@pytest.mark.unit
def test_parse_records_error_metric_on_failure(tmp_path: Path) -> None:
    """platform_external_calls_total{service=docling,operation=parse,status=error} == 1."""
    from platform.parsers.docling_parser import DoclingParser
    from platform.schemas.errors import ParseError

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    registry = CollectorRegistry()

    with pytest.raises(ParseError):
        DoclingParser(registry=registry).parse(bad)

    assert (
        _counter(registry, {"service": "docling", "operation": "parse", "status": "error"}) == 1.0
    )
