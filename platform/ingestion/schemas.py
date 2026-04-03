"""
Ingestion pipeline data schemas.

Six immutable Pydantic models that define contracts between ingestion steps:
  1. RawDocument          — uploaded file bytes + metadata
  2. DocumentElement      — raw extracted element from DoclingDocument
  3. ArtifactRef          — pointer to stored table image / figure image / DataFrame
  4. UnifiedElement       — post-narration/description element (all modalities as text)
  5. ChunkMetadata        — rich metadata attached to a chunk
  6. EnrichedChunk        — final output of chunking pipeline

All inherit from PlatformModel (frozen=True, validated at boundaries).
All IDs are deterministic (content hashes) for reproducibility and streaming.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, field_validator

from platform.schemas.base import PlatformModel

__all__ = [
    "RawDocument",
    "DocumentElement",
    "ArtifactRef",
    "UnifiedElement",
    "ChunkMetadata",
    "EnrichedChunk",
]


class RawDocument(PlatformModel):
    """Entry point to the ingestion pipeline: uploaded file with metadata.

    Wraps file bytes from the API layer with upload context.
    Consumed by DocumentConverter (Step 2).
    """

    doc_id: str = Field(
        ...,
        description="Unique identifier for this document (typically batch_id or UUID)",
    )
    file_bytes: bytes = Field(
        ..., description="Raw file content (PDF, DOCX, or TXT)"
    )
    mime_type: str = Field(
        ...,
        description="MIME type of the file (e.g., 'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
    )
    filename: str = Field(..., description="Original filename for logging/provenance")
    upload_metadata: dict = Field(
        default_factory=dict,
        description="Upload context: 'country', 'wave', 'product' at minimum",
    )


class DocumentElement(PlatformModel):
    """Single extracted element from a DoclingDocument, before unification.

    Modality is one of three types: TEXT (prose), TABLE (markdown-serialized),
    or IMAGE (raw caption string or empty).

    These are produced by ElementExtractor (Step 2b) and flow into artifact storage
    (Step 3) and narration/description (Step 4).
    """

    element_id: str = Field(
        ...,
        description="Content-hash ID (SHA256 truncated to 16 hex chars) for reproducibility",
    )
    raw_content: str = Field(
        ...,
        description="Raw extracted content: text for TEXT/CAPTION, markdown table for TABLE, caption or empty string for IMAGE",
    )
    modality: Literal["TEXT", "TABLE", "IMAGE"] = Field(
        ..., description="Element type"
    )
    page_no: int = Field(..., description="1-indexed page number")
    position_index: int = Field(
        ...,
        description="Reading order index within the document (for stable ordering after windowing)",
    )
    section_path: list[str] = Field(
        default_factory=list,
        description="Hierarchical section heading ancestry (e.g., ['Accounts Payable', 'Invoice Processing'])",
    )
    bounding_box: tuple[float, float, float, float] | None = Field(
        default=None,
        description="Optional (x0, y0, x1, y1) for artifact extraction from PDFs",
    )
    source_doc: str = Field(
        ..., description="Original filename this element was extracted from"
    )


class ArtifactRef(PlatformModel):
    """Pointer to a stored artifact (table image, DataFrame, figure image).

    Produced by ArtifactStore (Step 3). Multiple ArtifactRef objects can be
    attached to a single UnifiedElement (e.g., both TABLE_IMAGE and TABLE_DATAFRAME
    for a table).

    Used by Phase 5 HITL review to retrieve original visual evidence.
    """

    artifact_id: str = Field(
        ...,
        description="Content-hash ID for the artifact (SHA256 truncated to 16 hex)",
    )
    artifact_type: Literal["TABLE_IMAGE", "TABLE_DATAFRAME", "FIGURE_IMAGE"] = Field(
        ..., description="Type of artifact stored"
    )
    storage_path: str = Field(
        ..., description="Relative path under artifact_store_root (deterministic)"
    )
    page_no: int = Field(..., description="Page number where the artifact originated")
    section_path: list[str] = Field(
        default_factory=list,
        description="Section context where artifact appears",
    )


class UnifiedElement(PlatformModel):
    """Post-unification element where all modalities are natural language text.

    Produced by Unifier (Step 4). Every UnifiedElement has a .text field,
    regardless of source modality:
    - TEXT: original prose
    - TABLE: narrated by LLM (one element per table row)
    - IMAGE: described by VLM or fallback caption

    Consumed by SemanticChunker (Step 5).
    """

    element_id: str = Field(
        ...,
        description="Unique ID (content-hash or sequential for narrated table rows)",
    )
    text: str = Field(
        ...,
        description="Natural language text (prose, narrated table row, or image description)",
    )

    @field_validator("text")
    @classmethod
    def text_nonempty(cls, v: str) -> str:
        """Ensure text is non-empty after narration/description."""
        if not v or not v.strip():
            raise ValueError("UnifiedElement.text must be non-empty")
        return v

    modality: Literal["TEXT", "TABLE", "IMAGE"] = Field(
        ...,
        description="Original modality (tag for downstream phase metadata)",
    )
    section_path: list[str] = Field(
        default_factory=list, description="Section hierarchy"
    )
    page_no: int = Field(..., description="Page number")
    position_index: int = Field(
        ..., description="Reading order position (preserved from DocumentElement)"
    )
    artifact_refs: list[ArtifactRef] = Field(
        default_factory=list,
        description="Pointers to stored originals (table images, DataFrames, figures)",
    )
    source_doc: str = Field(..., description="Original filename")
    extraction_confidence: float = Field(
        default=1.0,
        description="Confidence in the extraction (1.0 for original text, <1.0 for LLM/VLM descriptions or fallbacks)",
        ge=0.0,
        le=1.0,
    )


class ChunkMetadata(PlatformModel):
    """Rich metadata computed during chunking, attached to each EnrichedChunk.

    Used by downstream phases (especially Phase 4 Classification and Phase 5 HITL)
    to understand chunk composition and retrieve original evidence.
    """

    headings: list[str] = Field(
        default_factory=list,
        description="Heading text of sections in this chunk",
    )
    has_table: bool = Field(
        default=False, description="True if chunk contains table-derived content"
    )
    has_image: bool = Field(
        default=False, description="True if chunk contains image-derived content"
    )
    table_row_count: int | None = Field(
        default=None,
        description="Number of narrated table rows in this chunk (None if no table)",
    )
    image_descriptions: list[str] | None = Field(
        default=None,
        description="List of image descriptions in this chunk (None if no images)",
    )
    cross_references: list[str] | None = Field(
        default=None,
        description="Detected cross-references ('See Section X', 'Refer to Y', 'per Figure Z')",
    )
    source_pages: list[int] = Field(
        default_factory=list,
        description="Deduplicated, sorted page numbers of elements in this chunk",
    )


class EnrichedChunk(PlatformModel):
    """Final output of the chunking pipeline (Step 5).

    Produced by SemanticChunker. Consumed by the atomizer (Phase 1, Step 2).
    Each chunk is token-bounded, respects section boundaries, and carries rich metadata.

    The unified_text field is the embedding source in Phase 2 (Knowledge Retrieval).
    """

    chunk_id: str = Field(
        ...,
        description="Deterministic hash of (unified_text + section_path) for reproducibility",
    )
    unified_text: str = Field(
        ..., description="Concatenated text of all constituent UnifiedElements"
    )
    chunk_metadata: ChunkMetadata = Field(
        default_factory=ChunkMetadata,
        description="Rich metadata computed during chunking",
    )
    modality_composition: dict[str, float] = Field(
        default_factory=dict,
        description="Token-count ratios per modality: {'TEXT': 0.6, 'TABLE': 0.3, 'IMAGE': 0.1}",
    )

    @field_validator("modality_composition")
    @classmethod
    def modality_composition_sums_to_one(
        cls, v: dict[str, float]
    ) -> dict[str, float]:
        """Ensure modality_composition values sum to approximately 1.0 (±0.05)."""
        if not v:
            return v
        total = sum(v.values())
        if not (0.95 <= total <= 1.05):
            raise ValueError(
                f"modality_composition values must sum to ~1.0 (got {total})"
            )
        return v

    artifact_refs: list[ArtifactRef] = Field(
        default_factory=list,
        description="All artifacts from constituent elements (deduplicated)",
    )
    section_path: list[str] = Field(
        default_factory=list,
        description="Top-level section for this chunk (single path; no section crossing)",
    )
    page_range: tuple[int, int] = Field(
        ...,
        description="(min_page, max_page) of constituent elements",
    )
    source_doc: str = Field(..., description="Original filename")
    token_count: int = Field(
        ...,
        description="Number of tokens in unified_text (measured by chunk_tokenizer)",
        ge=1,
        le=600,
    )
