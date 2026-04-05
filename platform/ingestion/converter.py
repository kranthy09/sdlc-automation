"""
Docling document converter with dual pipeline (standard + OCR fallback).

Wraps the Docling library's DocumentConverter with two pipelines:
  1. Standard pipeline: Heron layout + TableFormer + Tesseract OCR
  2. Aggressive-OCR fallback: full-page Tesseract for scanned documents

Pipeline routing:
  - Convert with standard pipeline first (faster, better text for normal docs)
  - If text extraction ratio falls below threshold → fallback pipeline
  - If both pipelines fail → raise DocumentConversionError

For large documents (30+ pages):
  - Docling's native document model streams internally (no memory bloat)
  - Returned DoclingDocument can be iterated without buffering all content
  - ElementExtractor (Step 2b) iterates document for page-windowed processing
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from platform.ingestion._config import IngestionConfig
from platform.ingestion._errors import DocumentConversionError
from platform.ingestion.schemas import RawDocument
from platform.observability.logger import get_logger

if TYPE_CHECKING:
    from docling.document_converter import (
        DocumentConverter as DoclingConverter,
    )
    from docling.models.document import DoclingDocument

__all__ = ["DocumentConverter", "get_converter"]

log = get_logger(__name__)

# Lazy singleton storage
_converter_lock = threading.Lock()
_converter_instance: DocumentConverter | None = None


class DocumentConverter:
    """Docling document converter with dual pipeline support.

    Handles PDF, DOCX, and TXT files with automatic fallback to the
    aggressive-OCR pipeline for scanned/image-heavy documents.

    Usage:
        cfg = get_ingestion_config()
        converter = DocumentConverter(cfg)
        raw_doc = RawDocument(...)
        docling_doc = converter.convert(raw_doc)
    """

    def __init__(self, config: IngestionConfig):
        self.config = config
        self._standard_pipeline: DoclingConverter | None = None
        self._vlm_pipeline: DoclingConverter | None = None

    def _init_standard_pipeline(self) -> DoclingConverter:
        """Lazy-initialize standard pipeline (Heron + TableFormer + OCR)."""
        if self._standard_pipeline is None:
            from docling.datamodel.base_models import (  # noqa: PLC0415
                InputFormat,
            )
            from docling.datamodel.pipeline_options import (  # noqa: PLC0415
                OcrAutoOptions,
                PdfPipelineOptions,
                TableFormerMode,
                TableStructureOptions,
                TesseractCliOcrOptions,
            )
            from docling.document_converter import (  # noqa: PLC0415
                DocumentConverter as DoclingConverter,
                PdfFormatOption,
            )

            log.debug(
                "Initializing Docling standard pipeline",
                extra={
                    "table_mode": self.config.docling_table_mode,
                    "ocr_engine": self.config.docling_ocr_engine,
                },
            )
            table_mode = (
                TableFormerMode.ACCURATE
                if self.config.docling_table_mode == "accurate"
                else TableFormerMode.FAST
            )
            ocr_options = (
                TesseractCliOcrOptions()
                if self.config.docling_ocr_engine == "tesseract"
                else OcrAutoOptions()
            )
            pipeline_options = PdfPipelineOptions(
                do_ocr=True,
                table_structure_options=TableStructureOptions(
                    mode=table_mode
                ),
                ocr_options=ocr_options,
            )
            self._standard_pipeline = DoclingConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    )
                }
            )
        return self._standard_pipeline

    def _init_vlm_pipeline(self) -> DoclingConverter:
        """Lazy-initialize aggressive-OCR fallback for scanned documents.

        Forces full-page Tesseract OCR on every page — used when standard
        pipeline text extraction ratio falls below vlm_fallback_threshold.
        """
        if self._vlm_pipeline is None:
            from docling.datamodel.base_models import (  # noqa: PLC0415
                InputFormat,
            )
            from docling.datamodel.pipeline_options import (  # noqa: PLC0415
                PdfPipelineOptions,
                TableFormerMode,
                TableStructureOptions,
                TesseractCliOcrOptions,
            )
            from docling.document_converter import (  # noqa: PLC0415
                DocumentConverter as DoclingConverter,
                PdfFormatOption,
            )

            log.debug(
                "Initializing Docling aggressive-OCR fallback pipeline"
            )
            pipeline_options = PdfPipelineOptions(
                do_ocr=True,
                table_structure_options=TableStructureOptions(
                    mode=TableFormerMode.FAST
                ),
                ocr_options=TesseractCliOcrOptions(
                    force_full_page_ocr=True
                ),
            )
            self._vlm_pipeline = DoclingConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    )
                }
            )
        return self._vlm_pipeline

    def convert(self, raw_doc: RawDocument) -> DoclingDocument:
        """Convert raw document bytes to DoclingDocument.

        Attempts standard pipeline first. If text extraction ratio falls
        below threshold, retries with the aggressive-OCR fallback pipeline.

        Args:
            raw_doc: RawDocument with file bytes and metadata

        Returns:
            DoclingDocument from Docling library

        Raises:
            DocumentConversionError: If both pipelines fail
        """
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

            if not self.config.docling_force_vlm:
                try:
                    docling_doc = (
                        self._init_standard_pipeline().convert(temp_file)
                    )
                    text_ratio = self._compute_text_ratio(docling_doc)
                    log.debug(
                        "Standard pipeline conversion complete",
                        extra={
                            "doc_id": raw_doc.doc_id,
                            "text_extraction_ratio": text_ratio,
                            "page_count": len(docling_doc.pages),
                        },
                    )
                    if (
                        text_ratio
                        >= self.config.docling_vlm_fallback_threshold
                    ):
                        return docling_doc

                    log.info(
                        "Standard pipeline text ratio below threshold;"
                        " falling back to OCR pipeline",
                        extra={
                            "doc_id": raw_doc.doc_id,
                            "text_ratio": text_ratio,
                            "threshold": (
                                self.config.docling_vlm_fallback_threshold
                            ),
                        },
                    )
                except Exception as e:
                    log.warning(
                        "Standard pipeline failed; trying OCR fallback",
                        extra={"doc_id": raw_doc.doc_id, "error": str(e)},
                    )

            try:
                docling_doc = (
                    self._init_vlm_pipeline().convert(temp_file)
                )
                log.info(
                    "OCR fallback pipeline conversion successful",
                    extra={
                        "doc_id": raw_doc.doc_id,
                        "page_count": len(docling_doc.pages),
                    },
                )
                return docling_doc
            except Exception as vlm_error:
                raise DocumentConversionError(
                    f"Both standard and OCR-fallback pipelines failed"
                    f" for {raw_doc.filename}: {vlm_error}"
                ) from vlm_error

        except DocumentConversionError:
            raise
        except Exception as e:
            raise DocumentConversionError(
                f"Document conversion failed for"
                f" {raw_doc.filename}: {e}"
            ) from e
        finally:
            if temp_file and Path(temp_file).exists():
                try:
                    Path(temp_file).unlink()
                except Exception as cleanup_err:
                    log.warning(
                        f"Failed to cleanup temp file"
                        f" {temp_file}: {cleanup_err}"
                    )

    @staticmethod
    def _compute_text_ratio(docling_doc: DoclingDocument) -> float:
        """Compute text extraction ratio for fallback decision.

        Ratio = total_chars / (page_count * 2000 estimated chars/page).
        A ratio < 0.3 indicates the document is likely scanned/image-heavy.
        """
        page_count = len(docling_doc.pages)
        if page_count == 0:
            return 0.0

        total_chars = 0
        for page in docling_doc.pages:
            try:
                total_chars += len(page.export_to_text())
            except (AttributeError, NotImplementedError):
                pass

        estimated_total = page_count * 2000
        return total_chars / estimated_total if estimated_total > 0 else 0.0


def get_converter(
    config: IngestionConfig | None = None,
) -> DocumentConverter:
    """Get or create the lazy-initialized DocumentConverter singleton.

    Thread-safe lazy initialization using module-level lock.

    Args:
        config: Optional IngestionConfig. If provided, recreates singleton.
                If None, uses cached instance.

    Returns:
        DocumentConverter singleton instance
    """
    global _converter_instance

    if config is not None or _converter_instance is None:
        with _converter_lock:
            if config is not None or _converter_instance is None:
                if config is None:
                    from platform.ingestion._config import (  # noqa: PLC0415
                        get_ingestion_config,
                    )
                    config = get_ingestion_config()
                _converter_instance = DocumentConverter(config)

    return _converter_instance
