"""
Docling document parser — converts PDF, DOCX, and TXT files into structured
table records and prose chunks for downstream requirement extraction.

Uses IBM Docling as the primary parsing engine (layout-aware, table-structure
preserving). `DocumentConverter` is lazy-loaded so importing this module never
triggers the heavy model download.

Every ``parse()`` call is wrapped in ``record_call("docling", "parse")`` for
Prometheus.

Usage::

    from platform.parsers.docling_parser import DoclingParser

    parser = DoclingParser()
    result = parser.parse(Path("requirements.pdf"))
    # result.tables → list[dict[str, str]]  (one dict per table row)
    # result.prose  → list[ProseChunk]      (text chunks with section context)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus_client import CollectorRegistry

from platform.observability.logger import get_logger
from platform.observability.metrics import MetricsRecorder
from platform.schemas.errors import ParseError  # noqa: F401 — re-exported

__all__ = [
    "DoclingParser",
    "ParseResult",
    "ProseChunk",
    "ParseError",
]

log = get_logger(__name__)

_MAX_CHUNK_CHARS = 1500
_OVERLAP_SENTENCES = 2


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProseChunk:
    """A chunk of prose text with section context.

    Attributes:
        text:        The chunk text (may start with overlap from prior chunk).
        section:     The most recent section heading above this chunk.
        page:        Page number where the chunk starts (1-based).
        char_offset: Cumulative character offset from start of document.
        has_overlap: True when this chunk's leading text is a repeat of the
                     tail of the previous chunk (overlap stitching).
    """

    text: str
    section: str
    page: int
    char_offset: int
    has_overlap: bool


@dataclass(frozen=True)
class ParseResult:
    """Output of a successful ``DoclingParser.parse()`` call.

    Attributes:
        tables: Flat list of row dicts extracted from all tables in the doc.
                Column names are the original header strings from the document.
        prose:  Ordered list of prose chunks, each ≤ 1500 chars with optional
                2-sentence overlap prefix for context continuity.
    """

    tables: list[dict[str, str]]
    prose: list[ProseChunk]


# ---------------------------------------------------------------------------
# DoclingParser
# ---------------------------------------------------------------------------


class DoclingParser:
    """PDF/DOCX/TXT parser backed by IBM Docling.

    Args:
        registry:   Prometheus CollectorRegistry — inject a fresh one in tests.
        _converter: Pre-built converter instance — for testing only; bypasses
                    the lazy ``DocumentConverter()`` construction.
    """

    def __init__(
        self,
        *,
        registry: CollectorRegistry | None = None,
        _converter: Any = None,
    ) -> None:
        self._recorder = MetricsRecorder(registry)
        self._converter: Any = _converter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, path: Path) -> ParseResult:
        """Parse a document file into table records and prose chunks.

        Args:
            path: Path to a PDF, DOCX, or TXT file.

        Returns:
            ``ParseResult`` with ``tables`` and ``prose`` populated.

        Raises:
            ``ParseError``: If Docling fails to convert the document.
        """
        try:
            with self._recorder.record_call("docling", "parse"):
                result = self._get_converter().convert(str(path))
                doc: Any = result.document
                tables = _extract_tables(doc)
                prose = _extract_prose(doc)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(filename=path.name, reason=str(exc)) from exc

        log.debug(
            "docling_parse_ok",
            file=str(path),
            n_tables=len(tables),
            n_chunks=len(prose),
        )
        return ParseResult(tables=tables, prose=prose)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_converter(self) -> Any:
        if self._converter is None:
            from docling.document_converter import DocumentConverter  # noqa: PLC0415

            log.info("docling_converter_init")
            self._converter = DocumentConverter()
        return self._converter


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_tables(doc: Any) -> list[dict[str, str]]:
    """Extract all table rows from a DoclingDocument as flat dicts."""
    records: list[dict[str, str]] = []
    for table in doc.tables:
        df: Any = table.export_to_dataframe(doc)
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            records.append({str(k): str(v) for k, v in row.items()})
    return records


def _extract_prose(doc: Any) -> list[ProseChunk]:
    """Extract prose text from a DoclingDocument as chunked ProseChunks.

    Algorithm:
    1. Walk ``doc.texts`` in document order.
    2. Track the current section heading (SECTION_HEADER / TITLE labels).
    3. Accumulate PARAGRAPH / TEXT / LIST_ITEM items into a buffer.
    4. Emit a ProseChunk when the buffer exceeds ``_MAX_CHUNK_CHARS``.
    5. Stitch overlap: last ``_OVERLAP_SENTENCES`` sentences of chunk N are
       prepended to chunk N+1 for retrieval context continuity.
    6. Flush remaining buffer at end of document and at every section change.
    """
    from docling_core.types.doc import DocItemLabel  # noqa: PLC0415

    PROSE: frozenset[Any] = frozenset(
        {DocItemLabel.TEXT, DocItemLabel.PARAGRAPH, DocItemLabel.LIST_ITEM}
    )
    HEADERS: frozenset[Any] = frozenset({DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE})

    chunks: list[ProseChunk] = []
    section: str = ""
    buf: list[str] = []
    buf_page: int = 1
    char_offset: int = 0
    overlap_prefix: str = ""

    def flush(*, end_section: bool = False) -> None:
        nonlocal buf, overlap_prefix
        if not buf:
            return
        joined = " ".join(buf)
        full = (overlap_prefix + " " + joined).strip() if overlap_prefix else joined
        chunks.append(
            ProseChunk(
                text=full,
                section=section,
                page=buf_page,
                char_offset=char_offset,
                has_overlap=bool(overlap_prefix),
            )
        )
        overlap_prefix = "" if end_section else _last_sentences(joined, _OVERLAP_SENTENCES)
        buf = []

    for item in doc.texts:
        text: str = (item.text or "").strip()
        if not text:
            continue
        page: int = item.prov[0].page_no if item.prov else 1

        if item.label in HEADERS:
            flush(end_section=True)
            section = text
            overlap_prefix = ""
            continue

        if item.label not in PROSE:
            continue

        if not buf:
            buf_page = page

        buf.append(text)
        char_offset += len(text) + 1

        if sum(len(t) for t in buf) >= _MAX_CHUNK_CHARS:
            flush()

    flush(end_section=True)
    return chunks


def _last_sentences(text: str, n: int) -> str:
    """Return the last *n* sentences from *text* (period-based split)."""
    parts = [s.strip() for s in text.split(". ") if s.strip()]
    tail = parts[-n:] if len(parts) > n else []
    if not tail:
        return ""
    joined = ". ".join(tail)
    return joined if joined.endswith(".") else joined + "."
