"""
Ingestion pipeline exceptions.

All exceptions in the ingestion pipeline inherit from IngestionError for unified
error handling at the LangGraph node boundary.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base exception for all ingestion pipeline failures.

    Raised when document conversion, element extraction, or artifact storage fails
    at any step. Includes optional chained exception for root-cause diagnosis.
    """
    pass


class DocumentConversionError(IngestionError):
    """Raised when Docling document conversion fails on both standard and VLM pipelines."""
    pass


class LLMNarrationError(IngestionError):
    """Raised when LLM table narration fails (transient or permanent).

    Transient failures (LLM timeout, rate limit) should be retried by the caller.
    Permanent failures (invalid table format, context window exceeded) are fatal.
    """
    pass


class VLMDescriptionError(IngestionError):
    """Raised when VLM image description fails (transient or permanent).

    Transient failures (model loading timeout) trigger fallback to caption/placeholder.
    Permanent failures abort the image description step.
    """
    pass


class ArtifactStorageError(IngestionError):
    """Raised when artifact storage (table image, DataFrame, figure image) fails."""
    pass
