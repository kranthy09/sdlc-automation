"""
Ingestion pipeline configuration via environment variables.

All Docling, LLM narration, VLM description, and chunking parameters are configured
via env vars with sensible defaults. Supports zero-config operation for typical
5-50 page documents; tunable for larger batches.

Usage:
    from platform.ingestion._config import get_ingestion_config

    cfg = get_ingestion_config()
    print(cfg.chunk_max_tokens)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionConfig(BaseSettings):
    """Configuration for the unified ingestion pipeline (Steps 2-5).

    Subsection of platform Settings; can also be instantiated standalone for testing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="INGESTION_",  # env vars prefixed with INGESTION_
    )

    # -----------------------------------------------------------------------
    # Docling document conversion (Step 2)
    # -----------------------------------------------------------------------
    docling_ocr_engine: str = "tesseract"
    """OCR backend for scanned PDFs in standard pipeline. Options: 'tesseract', 'easyocr'.
    Requires system dependency (tesseract-ocr binary) or Python package (easyocr).
    """

    docling_table_mode: Literal["accurate", "fast"] = "accurate"
    """TableFormer mode: 'accurate' (default, slower, better table structure) or 'fast' (quicker, less accurate).
    Use 'fast' in CI or for quick prototyping. 'accurate' for production.
    """

    docling_vlm_model: str = "smoldocling"
    """VLM model identifier for scanned/image-heavy document fallback.
    Default: 'smoldocling' (ds4sd/SmolDocling-256M-preview from HuggingFace).
    Alternative: other HuggingFace model IDs supporting document understanding.
    """

    docling_force_vlm: bool = False
    """Force VLM pipeline on all documents (bypass text extraction ratio check).
    Useful for testing or documents where standard pipeline consistently fails.
    """

    docling_vlm_fallback_threshold: float = 0.3
    """Text extraction ratio below which standard pipeline falls back to VLM.
    Ratio = (total_extracted_text_chars) / (page_count * 2000 est_chars_per_page).
    If ratio < threshold, document is treated as scanned/image-heavy.
    """

    # -----------------------------------------------------------------------
    # Multimodal narration and description (Step 4)
    # -----------------------------------------------------------------------
    image_description_model: Literal["smolvlm", "claude", "gpt4o", "none"] = "smolvlm"
    """VLM for image descriptions.
    - 'smolvlm': local SmolVLM (fast, private)
    - 'claude': Claude API vision (rich descriptions, costs per call)
    - 'gpt4o': GPT-4o vision (rich descriptions, costs per call)
    - 'none': skip VLM; use caption or fallback placeholder (testing)
    """

    narration_concurrency: int = 5
    """Max parallel LLM calls for table narration. Balanced default for moderate
    table volumes. Increase for document-heavy batches; decrease if LLM is rate-limited.
    """

    description_concurrency: int = 3
    """Max parallel VLM calls for image description. Lower than narration due to
    VLM cost/latency being higher. Increase if you have many images; decrease if
    VLM is slow or rate-limited.
    """

    # -----------------------------------------------------------------------
    # Semantic chunking (Step 5)
    # -----------------------------------------------------------------------
    chunk_max_tokens: int = 512
    """Maximum tokens per chunk (measured by CHUNK_TOKENIZER).
    Aligns with embedding model context window. Typical: 256-1024.
    Larger chunks = fewer chunks but less granularity. Smaller = more chunks, more granularity.
    """

    chunk_overlap_tokens: int = 64
    """Overlap between adjacent chunks (in tokens). Preserves context continuity
    across chunk boundaries. Typical: 32-128. Higher = more redundancy, better context recovery.
    """

    chunk_tokenizer: str = "BAAI/bge-large-en-v1.5"
    """Tokenizer model for token counting during chunking.
    Must match the embedding model used in Phase 2 (Knowledge Retrieval).
    Downloaded on first use from HuggingFace transformers.
    """

    # -----------------------------------------------------------------------
    # Artifact storage (Step 3)
    # -----------------------------------------------------------------------
    artifact_store_root: str = ""
    """Root directory for content-addressable artifact storage.
    Default (empty string) → {PROJECT_DATA_DIR}/artifacts/ (resolved at runtime).
    Can be a local path or S3 URI (s3://bucket/path) if s3fs is installed.
    """

    def artifact_store_root_resolved(self) -> Path:
        """Resolve artifact_store_root to an absolute Path.
        If empty, uses {PROJECT_DATA_DIR}/artifacts/.
        """
        if self.artifact_store_root:
            return Path(self.artifact_store_root)

        # Fallback: {PROJECT_DATA_DIR}/artifacts/
        # PROJECT_DATA_DIR typically set in docker-compose or kubernetes
        from platform.config.settings import get_settings
        settings = get_settings()
        data_dir = getattr(settings, 'data_dir', None)
        if not data_dir:
            # Last resort: use /tmp/project_artifacts
            data_dir = "/tmp/project_artifacts"
        return Path(data_dir) / "artifacts"


@lru_cache(maxsize=1)
def get_ingestion_config() -> IngestionConfig:
    """Return the cached IngestionConfig instance.

    Call get_ingestion_config.cache_clear() in tests that monkeypatch env vars.
    """
    return IngestionConfig()
