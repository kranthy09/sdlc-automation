"""
Document text parser — converts PDF, DOCX, and TXT files into prose chunks
for downstream requirement extraction.

Engines (all MIT-licensed, no ML models):
  PDF  → pypdf       — pure-Python, selects embedded text only (no OCR)
  DOCX → python-docx — paragraph-level extraction, heading styles preserved
  TXT  → stdlib pathlib

No table extraction. No image extraction. Text only.

Every ``parse()`` call is wrapped in ``record_call("docling", "parse")`` so
the Prometheus metric label is unchanged — zero impact on dashboards.

Usage::

    from platform.parsers.docling_parser import DoclingParser

    parser = DoclingParser()
    result = parser.parse(Path("requirements.pdf"))
    # result.tables → []               (always — text-only extraction)
    # result.prose  → list[ProseChunk]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

# Internal item type: (is_heading, text, page_no)
_TextItem = tuple[bool, str, int]


# ---------------------------------------------------------------------------
# Public result types  (API unchanged from the docling implementation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProseChunk:
    """A chunk of prose text with section context.

    Attributes:
        text:        The chunk text (may start with overlap from prior chunk).
        section:     The most recent section heading above this chunk.
        page:        Page number where the chunk starts (1-based).
        char_offset: Cumulative character offset from start of document.
        has_overlap: True when this chunk's leading text repeats the tail of
                     the previous chunk (overlap stitching for retrieval).
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
        tables: Always ``[]`` — text-only extraction; callers that previously
                consumed table rows will fall through to prose (same behaviour
                as an empty table in the original implementation).
        prose:  Ordered list of prose chunks, each ≤ 1500 chars with optional
                2-sentence overlap prefix for context continuity.
    """

    tables: list[dict[str, str]]
    prose: list[ProseChunk]


# ---------------------------------------------------------------------------
# DoclingParser
# ---------------------------------------------------------------------------


class DoclingParser:
    """PDF/DOCX/TXT parser backed by pypdf and python-docx.

    Args:
        registry: Prometheus CollectorRegistry — inject a fresh one in tests.
    """

    def __init__(self, *, registry: CollectorRegistry | None = None) -> None:
        self._recorder = MetricsRecorder(registry)

    def parse(self, path: Path) -> ParseResult:
        """Parse a document file into prose chunks.

        Args:
            path: Path to a PDF, DOCX, or TXT file.

        Returns:
            ``ParseResult`` with ``tables=[]`` and ``prose`` populated.

        Raises:
            ``ParseError``: If the file cannot be read or parsed.
        """
        try:
            with self._recorder.record_call("docling", "parse"):
                suffix = path.suffix.lower()
                if suffix == ".pdf":
                    items = _extract_pdf(path)
                elif suffix == ".docx":
                    items = _extract_docx(path)
                else:
                    items = _extract_txt(path)
                prose = _chunk(items)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(filename=path.name, reason=str(exc)) from exc

        log.debug("parser_parse_ok", file=str(path), n_chunks=len(prose))
        return ParseResult(tables=[], prose=prose)


# ---------------------------------------------------------------------------
# Format extractors
# ---------------------------------------------------------------------------


def _extract_pdf(path: Path) -> list[_TextItem]:
    """Extract text from a PDF using pypdf.

    Each page is split into paragraphs (double-newline separated) and yielded
    as individual items.  All items are non-heading (no reliable heading
    detection from raw PDF text streams).
    """
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(str(path))
    items: list[_TextItem] = []
    for page_no, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        for para in page_text.split("\n\n"):
            para = para.strip()
            if para:
                items.append((False, para, page_no))
    return items


def _extract_docx(path: Path) -> list[_TextItem]:
    """Extract text from a DOCX using python-docx.

    Paragraphs whose style name starts with ``Heading`` or equals ``Title``
    are treated as section headings; everything else is prose.
    """
    import io  # noqa: PLC0415

    from docx import Document  # noqa: PLC0415

    doc = Document(io.BytesIO(path.read_bytes()))
    items: list[_TextItem] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name if para.style else ""
        is_heading = style_name.startswith("Heading") or style_name == "Title"
        items.append((is_heading, text, 1))
    return items


def _extract_txt(path: Path) -> list[_TextItem]:
    """Extract text from a plain-text file.

    Splits on double newlines to produce paragraph-sized items.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    items: list[_TextItem] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            items.append((False, para, 1))
    return items


# ---------------------------------------------------------------------------
# Chunker  (algorithm identical to the original docling implementation)
# ---------------------------------------------------------------------------


def _chunk(items: list[_TextItem]) -> list[ProseChunk]:
    """Group text items into ProseChunks with overlap stitching.

    Algorithm:
    1. Walk items in document order.
    2. Track the current section heading (is_heading == True items).
    3. Accumulate prose items into a buffer.
    4. Emit a ProseChunk when the buffer exceeds ``_MAX_CHUNK_CHARS``.
    5. Stitch overlap: last ``_OVERLAP_SENTENCES`` sentences of chunk N are
       prepended to chunk N+1 for retrieval context continuity.
    6. Flush remaining buffer at end of document and at every section change.
    """
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

    for is_heading, text, page in items:
        text = text.strip()
        if not text:
            continue

        if is_heading:
            flush(end_section=True)
            section = text
            overlap_prefix = ""
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
