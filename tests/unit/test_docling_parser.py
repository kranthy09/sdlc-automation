"""
TDD — platform/parsers/docling_parser.py

Tests cover the six behaviours that matter:
  - Tables   → extract() converts table rows to list[dict[str, str]].
  - Prose    → extract() groups text items into ProseChunks with section label.
  - Empty    → empty doc (no tables, no texts) returns empty ParseResult.
  - Error    → DocumentConverter failure is wrapped in ParseError.
  - ok metric  → platform_external_calls_total{status="ok"} increments.
  - err metric → platform_external_calls_total{status="error"} increments.

All tests inject _converter via the DoclingParser constructor — no real Docling
calls, no file system dependencies beyond a tmp_path sentinel file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_doc(
    *,
    table_dfs: list[list[dict[str, str]]] | None = None,
    text_items: list[tuple[object, str, int]] | None = None,
) -> MagicMock:
    """Build a MagicMock docling document with controllable tables and texts."""
    doc = MagicMock()

    # Tables — each entry in table_dfs becomes one TableItem mock
    mock_tables: list[MagicMock] = []
    for rows in table_dfs or []:
        t = MagicMock()
        t.export_to_dataframe.return_value = pd.DataFrame(rows)
        mock_tables.append(t)
    doc.tables = mock_tables

    # Texts — each tuple is (DocItemLabel, text_str, page_no)
    mock_texts: list[MagicMock] = []
    for label, text, page in text_items or []:
        ti = MagicMock()
        ti.label = label
        ti.text = text
        prov = MagicMock()
        prov.page_no = page
        ti.prov = [prov]
        mock_texts.append(ti)
    doc.texts = mock_texts

    return doc


def _make_converter(doc: MagicMock) -> MagicMock:
    """Wrap a mock document in a mock DocumentConverter."""
    result = MagicMock()
    result.document = doc
    converter = MagicMock()
    converter.convert.return_value = result
    return converter


def _counter(registry: CollectorRegistry, labels: dict[str, str]) -> float:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == "platform_external_calls_total" and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_extracts_table_rows_as_dicts(tmp_path: Path) -> None:
    """Table rows are returned as list[dict[str, str]] with original column names."""
    from platform.parsers.docling_parser import DoclingParser

    rows = [
        {"Req ID": "REQ-001", "Description": "Three-way matching", "Module": "AP"},
        {"Req ID": "REQ-002", "Description": "Automated payment proposals", "Module": "AP"},
    ]
    doc = _make_mock_doc(table_dfs=[rows])
    registry = CollectorRegistry()
    parser = DoclingParser(registry=registry, _converter=_make_converter(doc))

    sentinel = tmp_path / "reqs.pdf"
    sentinel.write_bytes(b"%PDF-1.4")
    result = parser.parse(sentinel)

    assert len(result.tables) == 2
    assert result.tables[0]["Req ID"] == "REQ-001"
    assert result.tables[1]["Description"] == "Automated payment proposals"


# ---------------------------------------------------------------------------
# Prose extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_extracts_prose_chunks_with_section(tmp_path: Path) -> None:
    """Prose items are grouped under their section heading."""
    from docling_core.types.doc import DocItemLabel

    from platform.parsers.docling_parser import DoclingParser

    text_items = [
        (DocItemLabel.SECTION_HEADER, "Accounts Payable", 1),
        (DocItemLabel.PARAGRAPH, "System must support three-way matching.", 1),
        (DocItemLabel.TEXT, "Automated payment proposals are required.", 2),
    ]
    doc = _make_mock_doc(text_items=text_items)
    registry = CollectorRegistry()
    parser = DoclingParser(registry=registry, _converter=_make_converter(doc))

    sentinel = tmp_path / "reqs.docx"
    sentinel.write_bytes(b"PK\x03\x04")
    result = parser.parse(sentinel)

    assert len(result.prose) >= 1
    chunk = result.prose[0]
    assert chunk.section == "Accounts Payable"
    assert "three-way matching" in chunk.text
    assert chunk.has_overlap is False


# ---------------------------------------------------------------------------
# Empty document
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_empty_document_returns_empty_result(tmp_path: Path) -> None:
    """An empty DoclingDocument produces empty tables and prose lists."""
    from platform.parsers.docling_parser import DoclingParser

    doc = _make_mock_doc()
    registry = CollectorRegistry()
    parser = DoclingParser(registry=registry, _converter=_make_converter(doc))

    sentinel = tmp_path / "empty.txt"
    sentinel.write_text("", encoding="utf-8")
    result = parser.parse(sentinel)

    assert result.tables == []
    assert result.prose == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_wraps_converter_failure_in_parse_error(tmp_path: Path) -> None:
    """RuntimeError from DocumentConverter is re-raised as ParseError."""
    from platform.parsers.docling_parser import DoclingParser
    from platform.schemas.errors import ParseError

    converter = MagicMock()
    converter.convert.side_effect = RuntimeError("conversion failed")

    registry = CollectorRegistry()
    parser = DoclingParser(registry=registry, _converter=converter)

    sentinel = tmp_path / "bad.pdf"
    sentinel.write_bytes(b"%PDF-1.4")

    with pytest.raises(ParseError) as exc_info:
        parser.parse(sentinel)

    assert exc_info.value.filename == "bad.pdf"
    assert "conversion failed" in exc_info.value.reason


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_records_ok_metric_on_success(tmp_path: Path) -> None:
    """platform_external_calls_total{service=docling,operation=parse,status=ok} == 1."""
    from platform.parsers.docling_parser import DoclingParser

    doc = _make_mock_doc()
    registry = CollectorRegistry()
    parser = DoclingParser(registry=registry, _converter=_make_converter(doc))

    sentinel = tmp_path / "reqs.txt"
    sentinel.write_text("text", encoding="utf-8")
    parser.parse(sentinel)

    value = _counter(registry, {"service": "docling", "operation": "parse", "status": "ok"})
    assert value == 1.0


@pytest.mark.unit
def test_parse_records_error_metric_on_failure(tmp_path: Path) -> None:
    """platform_external_calls_total{service=docling,operation=parse,status=error} == 1."""
    from platform.parsers.docling_parser import DoclingParser

    converter = MagicMock()
    converter.convert.side_effect = RuntimeError("crash")

    registry = CollectorRegistry()
    parser = DoclingParser(registry=registry, _converter=converter)

    sentinel = tmp_path / "bad.txt"
    sentinel.write_text("x", encoding="utf-8")

    from platform.schemas.errors import ParseError

    with pytest.raises(ParseError):
        parser.parse(sentinel)

    value = _counter(registry, {"service": "docling", "operation": "parse", "status": "error"})
    assert value == 1.0
