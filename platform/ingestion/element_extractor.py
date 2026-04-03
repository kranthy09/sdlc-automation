"""
DoclingDocument → DocumentElement stream extractor.

Iterates a Docling document in reading order (page by page, element by element),
extracting individual elements while preserving section hierarchy.

Key principle: Modality-agnostic stream.
  - Every element (prose, table row, image) flows through the same pipeline
  - Section context (section_path) is preserved for all modalities
  - Position in document (page_no, position_index) enables reconstruction

Handles large documents (30+ pages) efficiently:
  - Yields elements one at a time (no buffering)
  - Raw Docling table objects stored in side-channel for artifact extraction
  - Supports explicit windowed iteration (5-page windows) if needed
"""

from __future__ import annotations

import hashlib
from typing import Generator

from typing import TYPE_CHECKING

from platform.ingestion.schemas import DocumentElement
from platform.observability.logger import get_logger

if TYPE_CHECKING:
    from docling.models.document import DoclingDocument

__all__ = ["ElementExtractor"]

log = get_logger(__name__)


class ElementExtractor:
    """Extract DocumentElements from DoclingDocument in reading order.

    Iterates pages sequentially, tracks section headings, emits one element
    per text item, table, or image.

    For large documents, yields elements incrementally (streaming) rather
    than buffering entire document in memory.

    Usage:
        extractor = ElementExtractor()
        elements = extractor.extract(docling_doc, source_doc="requirements.pdf")
        for elem in elements:
            print(elem.modality, elem.section_path)
    """

    def __init__(self, window_size: int = 5):
        """Initialize element extractor.

        Args:
            window_size: For explicit windowing, process N pages at a time.
                        Default 5 pages = ~10MB memory footprint per window.
                        Unused in standard extract() flow (full document); useful
                        for advanced streaming scenarios.
        """
        self.window_size = window_size
        self._docling_tables: dict[str, object] = {}
        """Side-channel storage for raw Docling table objects.
        Keyed by element_id; used by artifact_store.py to extract table images/DataFrames.
        """

    def extract(
        self, docling_doc: DoclingDocument, source_doc: str
    ) -> list[DocumentElement]:
        """Extract all elements from a DoclingDocument.

        Iterates in reading order, preserving section hierarchy and page positions.

        Args:
            docling_doc: Docling document object
            source_doc: Original filename for provenance

        Returns:
            List of DocumentElements sorted by (page_no, position_index)
        """
        from docling_core.models.document import Heading, ListItem, Picture, Table, TextItem  # noqa: PLC0415

        elements = []
        section_path: list[str] = []

        for page_no, page in enumerate(docling_doc.pages, start=1):
            position_index = 0

            for item in page.children or []:
                # Update section path on heading
                if isinstance(item, Heading):
                    # Build hierarchical path from heading text and level
                    heading_text = item.export_to_text().strip()
                    heading_level = getattr(item, "level", 0)

                    # Trim section_path to match heading level
                    # E.g., level=1 → root section, level=2 → subsection
                    if heading_level > 0:
                        section_path = section_path[: heading_level - 1]
                    section_path.append(heading_text)

                    # Heading itself is not emitted as element (included in section_path)
                    continue

                # Extract text elements (prose, list items, captions)
                if isinstance(item, (TextItem, ListItem)):
                    text_content = item.export_to_text()
                    if text_content.strip():  # Skip empty
                        elem = self._make_element(
                            raw_content=text_content,
                            modality="TEXT",
                            page_no=page_no,
                            position_index=position_index,
                            section_path=section_path.copy(),
                            bounding_box=self._extract_bbox(item),
                            source_doc=source_doc,
                        )
                        elements.append(elem)
                        position_index += 1

                # Extract table elements
                elif isinstance(item, Table):
                    table_markdown = item.export_to_markdown()
                    if table_markdown.strip():
                        element_id = self._hash_id(table_markdown)
                        # Store raw Docling table for artifact extraction later
                        self._docling_tables[element_id] = item

                        elem = self._make_element(
                            raw_content=table_markdown,
                            modality="TABLE",
                            page_no=page_no,
                            position_index=position_index,
                            section_path=section_path.copy(),
                            bounding_box=self._extract_bbox(item),
                            source_doc=source_doc,
                            element_id=element_id,  # Explicit ID for table lookup
                        )
                        elements.append(elem)
                        position_index += 1

                # Extract image elements
                elif isinstance(item, Picture):
                    # Docling provides image caption and binary data
                    caption_text = item.export_to_text() or ""
                    element_id = self._hash_id(caption_text or f"image_{page_no}_{position_index}")

                    # Store raw Docling picture for artifact extraction later
                    self._docling_tables[element_id] = item

                    elem = self._make_element(
                        raw_content=caption_text,  # Caption (may be empty)
                        modality="IMAGE",
                        page_no=page_no,
                        position_index=position_index,
                        section_path=section_path.copy(),
                        bounding_box=self._extract_bbox(item),
                        source_doc=source_doc,
                        element_id=element_id,  # For later retrieval
                    )
                    elements.append(elem)
                    position_index += 1

        log.debug(
            "Extracted elements from document",
            extra={
                "source_doc": source_doc,
                "total_elements": len(elements),
                "tables": sum(1 for e in elements if e.modality == "TABLE"),
                "images": sum(1 for e in elements if e.modality == "IMAGE"),
                "text": sum(1 for e in elements if e.modality == "TEXT"),
            },
        )

        # Sort by reading order (page, then position within page)
        elements.sort(key=lambda e: (e.page_no, e.position_index))

        return elements

    def extract_windowed(
        self, docling_doc: DoclingDocument, source_doc: str, window_size: int | None = None
    ) -> Generator[list[DocumentElement], None, None]:
        """Extract elements in page-sized windows (memory-efficient for large docs).

        Yields lists of elements, one window at a time. Each window contains
        elements from `window_size` consecutive pages (default 5 pages).

        Useful for processing 100+ page documents with bounded memory.

        Args:
            docling_doc: Docling document object
            source_doc: Original filename for provenance
            window_size: Pages per window (default: self.window_size)

        Yields:
            Lists of DocumentElements, one per window
        """
        from docling_core.models.document import Heading, ListItem, Picture, Table, TextItem  # noqa: PLC0415

        if window_size is None:
            window_size = self.window_size

        section_path: list[str] = []
        window_elements: list[DocumentElement] = []

        for page_no, page in enumerate(docling_doc.pages, start=1):
            position_index = 0

            for item in page.children or []:
                # Update section path
                if isinstance(item, Heading):
                    heading_text = item.export_to_text().strip()
                    heading_level = getattr(item, "level", 0)
                    if heading_level > 0:
                        section_path = section_path[: heading_level - 1]
                    section_path.append(heading_text)
                    continue

                # Extract element (same logic as extract())
                elem = None
                if isinstance(item, (TextItem, ListItem)):
                    text_content = item.export_to_text()
                    if text_content.strip():
                        elem = self._make_element(
                            raw_content=text_content,
                            modality="TEXT",
                            page_no=page_no,
                            position_index=position_index,
                            section_path=section_path.copy(),
                            bounding_box=self._extract_bbox(item),
                            source_doc=source_doc,
                        )
                        position_index += 1

                elif isinstance(item, Table):
                    table_markdown = item.export_to_markdown()
                    if table_markdown.strip():
                        element_id = self._hash_id(table_markdown)
                        self._docling_tables[element_id] = item
                        elem = self._make_element(
                            raw_content=table_markdown,
                            modality="TABLE",
                            page_no=page_no,
                            position_index=position_index,
                            section_path=section_path.copy(),
                            bounding_box=self._extract_bbox(item),
                            source_doc=source_doc,
                            element_id=element_id,
                        )
                        position_index += 1

                elif isinstance(item, Picture):
                    caption_text = item.export_to_text() or ""
                    element_id = self._hash_id(
                        caption_text or f"image_{page_no}_{position_index}"
                    )
                    self._docling_tables[element_id] = item
                    elem = self._make_element(
                        raw_content=caption_text,
                        modality="IMAGE",
                        page_no=page_no,
                        position_index=position_index,
                        section_path=section_path.copy(),
                        bounding_box=self._extract_bbox(item),
                        source_doc=source_doc,
                        element_id=element_id,
                    )
                    position_index += 1

                if elem:
                    window_elements.append(elem)

            # Yield window when full, or at end of document
            if len(window_elements) > 0 and (
                page_no % window_size == 0
                or page_no == len(docling_doc.pages)
            ):
                log.debug(
                    f"Yielding window of {len(window_elements)} elements "
                    f"(pages {page_no - len(window_elements) + 1}-{page_no})"
                )
                yield sorted(
                    window_elements, key=lambda e: (e.page_no, e.position_index)
                )
                window_elements = []

    def get_docling_object(self, element_id: str) -> object | None:
        """Retrieve stored Docling table or picture object.

        Used by ArtifactStore (Step 3) to extract table images and DataFrames.

        Args:
            element_id: Element ID from DocumentElement.element_id

        Returns:
            Raw Docling object (Table or Picture), or None if not found
        """
        return self._docling_tables.get(element_id)

    def clear_docling_cache(self) -> None:
        """Clear stored Docling objects to free memory.

        Call after artifact extraction is complete and artifacts are on disk.
        """
        self._docling_tables.clear()

    @staticmethod
    def _make_element(
        raw_content: str,
        modality: str,
        page_no: int,
        position_index: int,
        section_path: list[str],
        bounding_box: tuple[float, float, float, float] | None,
        source_doc: str,
        element_id: str | None = None,
    ) -> DocumentElement:
        """Factory method to construct a DocumentElement.

        Args:
            raw_content: Extracted text or markdown content
            modality: "TEXT", "TABLE", or "IMAGE"
            page_no: 1-indexed page number
            position_index: Reading order within page
            section_path: Hierarchical section headings
            bounding_box: Optional (x0, y0, x1, y1) for PDFs
            source_doc: Original filename
            element_id: Optional explicit ID (defaults to content hash)

        Returns:
            DocumentElement instance
        """
        if element_id is None:
            element_id = ElementExtractor._hash_id(raw_content)

        return DocumentElement(
            element_id=element_id,
            raw_content=raw_content,
            modality=modality,
            page_no=page_no,
            position_index=position_index,
            section_path=section_path,
            bounding_box=bounding_box,
            source_doc=source_doc,
        )

    @staticmethod
    def _hash_id(content: str) -> str:
        """Generate content-hash ID (SHA-256 truncated to 16 hex chars).

        Deterministic for reproducibility; enables tracking same element across runs.

        Args:
            content: Text content to hash

        Returns:
            16-character hex string
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _extract_bbox(
        item: object,
    ) -> tuple[float, float, float, float] | None:
        """Extract bounding box from Docling item if available.

        Args:
            item: Docling document item (TextItem, Table, Picture, etc.)

        Returns:
            (x0, y0, x1, y1) tuple, or None if not available
        """
        try:
            if hasattr(item, "bbox"):
                bbox = item.bbox
                if bbox:
                    return (bbox.l, bbox.t, bbox.r, bbox.b)
        except (AttributeError, TypeError):
            pass
        return None
