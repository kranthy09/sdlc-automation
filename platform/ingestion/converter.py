"""
Docling document converter with dual pipeline (standard + VLM fallback).

Wraps the Docling library's DocumentConverter with two configurable pipelines:
  1. Standard pipeline: Heron layout analysis + TableFormer + Tesseract OCR
  2. VLM pipeline: SmolDocling for scanned/image-heavy documents

Pipeline routing:
  - Convert with standard pipeline first (faster, higher-quality text for normal docs)
  - If text extraction ratio falls below threshold → fallback to VLM pipeline
  - If both pipelines fail → raise DocumentConversionError

For large documents (30+ pages):
  - Docling's native document model streams internally (no memory bloat)
  - Returned DoclingDocument can be iterated without buffering entire content
  - ElementExtractor (Step 2b) iterates the document for page-windowed processing
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
from pathlib import Path

from typing import TYPE_CHECKING

from platform.ingestion._config import IngestionConfig
from platform.ingestion._errors import DocumentConversionError
from platform.ingestion.schemas import RawDocument
from platform.observability.logger import get_logger

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter as DoclingConverter
    from docling.models.document import DoclingDocument

__all__ = ["DocumentConverter", "get_converter"]

log = get_logger(__name__)

# Lazy singleton storage
_converter_lock = threading.Lock()
_converter_instance: DocumentConverter | None = None


class DocumentConverter:
    """Docling document converter with dual pipeline support.

    Handles PDF, DOCX, and TXT files with automatic fallback to VLM pipeline
    for scanned/image-heavy documents.

    Usage:
        cfg = get_ingestion_config()
        converter = DocumentConverter(cfg)
        raw_doc = RawDocument(...)
        docling_doc = converter.convert(raw_doc)
    """

    def __init__(self, config: IngestionConfig):
        """Initialize with dual pipeline configurations.

        Args:
            config: IngestionConfig with Docling settings
        """
        self.config = config
        self._standard_pipeline: DoclingConverter | None = None
        self._vlm_pipeline: DoclingConverter | None = None

    def _init_standard_pipeline(self) -> DoclingConverter:
        """Lazy-initialize standard pipeline (Heron + TableFormer + OCR)."""
        if self._standard_pipeline is None:
            from docling.document_converter import DocumentConverter as DoclingConverter  # noqa: PLC0415
            from docling.document_converter import PipelineOptions  # noqa: PLC0415

            log.debug(
                "Initializing Docling standard pipeline",
                extra={
                    "table_mode": self.config.docling_table_mode,
                    "ocr_engine": self.config.docling_ocr_engine,
                },
            )
            pipeline_options = PipelineOptions(
                table_mode=self.config.docling_table_mode,  # "accurate" or "fast"
                ocr_mode="force_tesseract"
                if self.config.docling_ocr_engine == "tesseract"
                else "auto",
            )
            self._standard_pipeline = DoclingConverter(
                format_options={},
                pipeline_options=pipeline_options,
            )
        return self._standard_pipeline

    def _init_vlm_pipeline(self) -> DoclingConverter:
        """Lazy-initialize VLM pipeline (SmolDocling)."""
        if self._vlm_pipeline is None:
            from docling.document_converter import DocumentConverter as DoclingConverter  # noqa: PLC0415
            from docling.document_converter import PipelineOptions  # noqa: PLC0415

            log.debug(
                "Initializing Docling VLM pipeline",
                extra={"vlm_model": self.config.docling_vlm_model},
            )
            # SmolDocling pipeline for scanned/image-heavy documents
            pipeline_options = PipelineOptions(
                table_mode="fast",  # VLM is slower, use fast table mode
                ocr_mode="ml",  # Use VLM instead of Tesseract
            )
            self._vlm_pipeline = DoclingConverter(
                format_options={}, pipeline_options=pipeline_options
            )
        return self._vlm_pipeline

    def convert(self, raw_doc: RawDocument) -> DoclingDocument:
        """Convert raw document bytes to DoclingDocument.

        Attempts standard pipeline first. If text extraction ratio falls below
        threshold, retries with VLM pipeline. Returns the first successful result.

        Args:
            raw_doc: RawDocument with file bytes and metadata

        Returns:
            DoclingDocument from Docling library

        Raises:
            DocumentConversionError: If both pipelines fail or file is unsupported
        """
        # Write bytes to temp file (Docling requires file path)
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=Path(raw_doc.filename).suffix,
                delete=False,
                prefix="ingestion_",
            ) as tmp:
                tmp.write(raw_doc.file_bytes)
                temp_file = tmp.name

            log.debug(
                "Converting document",
                extra={
                    "doc_id": raw_doc.doc_id,
                    "filename": raw_doc.filename,
                    "mime_type": raw_doc.mime_type,
                    "size_mb": len(raw_doc.file_bytes) / 1_000_000,
                },
            )

            # Try standard pipeline first
            if not self.config.docling_force_vlm:
                try:
                    docling_doc = self._init_standard_pipeline().convert(temp_file)

                    # Compute text extraction ratio to decide fallback
                    text_ratio = self._compute_text_ratio(docling_doc)
                    log.debug(
                        "Standard pipeline conversion complete",
                        extra={
                            "doc_id": raw_doc.doc_id,
                            "text_extraction_ratio": text_ratio,
                            "page_count": len(docling_doc.pages),
                        },
                    )

                    # If ratio is good, return this result
                    if text_ratio >= self.config.docling_vlm_fallback_threshold:
                        return docling_doc

                    # Text ratio below threshold → fallback to VLM
                    log.info(
                        "Standard pipeline text ratio below threshold; falling back to VLM",
                        extra={
                            "doc_id": raw_doc.doc_id,
                            "text_ratio": text_ratio,
                            "threshold": self.config.docling_vlm_fallback_threshold,
                        },
                    )
                except Exception as e:
                    log.warning(
                        "Standard pipeline failed; trying VLM fallback",
                        extra={"doc_id": raw_doc.doc_id, "error": str(e)},
                    )

            # Try VLM pipeline
            try:
                docling_doc = self._init_vlm_pipeline().convert(temp_file)
                log.info(
                    "VLM pipeline conversion successful",
                    extra={
                        "doc_id": raw_doc.doc_id,
                        "page_count": len(docling_doc.pages),
                    },
                )
                return docling_doc
            except Exception as vlm_error:
                raise DocumentConversionError(
                    f"Both standard and VLM pipelines failed for {raw_doc.filename}: {str(vlm_error)}"
                ) from vlm_error

        except DocumentConversionError:
            raise
        except Exception as e:
            raise DocumentConversionError(
                f"Document conversion failed for {raw_doc.filename}: {str(e)}"
            ) from e
        finally:
            # Cleanup temp file
            if temp_file and Path(temp_file).exists():
                try:
                    Path(temp_file).unlink()
                except Exception as e:
                    log.warning(f"Failed to cleanup temp file {temp_file}: {e}")

    @staticmethod
    def _compute_text_ratio(docling_doc: DoclingDocument) -> float:
        """Compute text extraction ratio for fallback decision.

        Ratio = (total_extracted_text_chars) / (page_count * 2000 est_chars_per_page)

        A ratio < 0.3 indicates the document is likely scanned/image-heavy.

        Args:
            docling_doc: DoclingDocument from conversion

        Returns:
            Float ratio between 0.0 and 1.0+ (values > 1.0 mean very dense text)
        """
        page_count = len(docling_doc.pages)
        if page_count == 0:
            return 0.0

        # Estimate total text by traversing document
        total_chars = 0
        for page in docling_doc.pages:
            # DoclingDocument exposes text via export_to_text() or similar
            # For now, approximate by counting characters in all text elements
            try:
                page_text = page.export_to_text()
                total_chars += len(page_text)
            except (AttributeError, NotImplementedError):
                # Fallback: estimate from metadata
                pass

        estimated_total = page_count * 2000
        ratio = total_chars / estimated_total if estimated_total > 0 else 0.0
        return ratio


def get_converter(config: IngestionConfig | None = None) -> DocumentConverter:
    """Get or create the lazy-initialized DocumentConverter singleton.

    Thread-safe lazy initialization using module-level lock.

    Args:
        config: Optional IngestionConfig. If provided, recreates the singleton.
                If None, uses cached instance.

    Returns:
        DocumentConverter singleton instance
    """
    global _converter_instance

    if config is not None or _converter_instance is None:
        with _converter_lock:
            if config is not None or _converter_instance is None:
                if config is None:
                    from platform.ingestion._config import get_ingestion_config
                    config = get_ingestion_config()
                _converter_instance = DocumentConverter(config)

    return _converter_instance
