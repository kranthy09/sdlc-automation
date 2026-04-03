"""
Unified multimodal document ingestion pipeline.

Entry point for Steps 2-5: Document conversion, element extraction, artifact storage,
multimodal narration/description, and semantic chunking with overlap.

Usage:
    from platform.ingestion import (
        RawDocument, DocumentElement, UnifiedElement, EnrichedChunk,
        DocumentConverter, ElementExtractor, ArtifactStore,
        TableNarrator, ImageDescriptor, Unifier, SemanticChunker,
        get_ingestion_config,
    )

For large documents (30+ pages), the pipeline supports page-windowed processing:
    cfg = get_ingestion_config()
    converter = DocumentConverter(cfg)
    docling_doc = converter.convert(raw_doc)  # Docling handles windowing internally

    # Process in 5-page windows for memory efficiency
    element_extractor = ElementExtractor(window_size=5)
    for window_elements in element_extractor.extract_windowed(docling_doc):
        # Process window_elements → store artifacts → narrate/describe → chunk
        ...
"""

from __future__ import annotations

from platform.ingestion._config import (
    IngestionConfig,
    get_ingestion_config,
)
from platform.ingestion._errors import (
    ArtifactStorageError,
    DocumentConversionError,
    IngestionError,
    LLMNarrationError,
    VLMDescriptionError,
)
from platform.ingestion.artifact_store import ArtifactStore
from platform.ingestion.converter import (
    DocumentConverter,
    get_converter,
)
from platform.ingestion.description import ImageDescriptor
from platform.ingestion.element_extractor import ElementExtractor
from platform.ingestion.narration import (
    NarratedRow,
    NarratedTable,
    TableNarrator,
)
from platform.ingestion.schemas import (
    ArtifactRef,
    ChunkMetadata,
    DocumentElement,
    EnrichedChunk,
    RawDocument,
    UnifiedElement,
)
from platform.ingestion.unifier import Unifier
from platform.ingestion.chunker import SemanticChunker

__all__ = [
    # Exceptions
    "IngestionError",
    "DocumentConversionError",
    "LLMNarrationError",
    "VLMDescriptionError",
    "ArtifactStorageError",
    # Config
    "IngestionConfig",
    "get_ingestion_config",
    # Schemas (Steps 1-5 data contracts)
    "RawDocument",
    "DocumentElement",
    "ArtifactRef",
    "UnifiedElement",
    "ChunkMetadata",
    "EnrichedChunk",
    # Phase B: Converter + ElementExtractor (Step 2)
    "DocumentConverter",
    "get_converter",
    "ElementExtractor",
    # Phase C: ArtifactStore (Step 3)
    "ArtifactStore",
    # Phase D: TableNarrator, ImageDescriptor, Unifier (Step 4)
    "TableNarrator",
    "NarratedRow",
    "NarratedTable",
    "ImageDescriptor",
    "Unifier",
    # Phase E: SemanticChunker (Step 5)
    "SemanticChunker",
]
