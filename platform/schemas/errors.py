"""
Typed platform exceptions.

These are structured Python exceptions — not raw strings — so callers can
inspect fields programmatically (e.g. to build ErrorEvent payloads).

Each exception carries typed fields alongside a human-readable str() message.
"""

from __future__ import annotations


class UnsupportedFormatError(Exception):
    """Raised by the format detector when a file's format cannot be handled.

    The file is quarantined and must not proceed through the pipeline.
    """

    def __init__(self, *, filename: str, detected_mime: str | None) -> None:
        self.filename = filename
        self.detected_mime = detected_mime
        mime_part = f" (detected mime: {detected_mime})" if detected_mime else ""
        super().__init__(f"Unsupported format: {filename!r}{mime_part}")


class ParseError(Exception):
    """Raised when a document cannot be parsed into requirement records.

    Typical cause: the required ``requirement_text`` column was not found
    after exhausting exact-match, fuzzy-match, and positional fallback.
    """

    def __init__(
        self,
        *,
        filename: str,
        reason: str,
        column_attempted: str | None = None,
    ) -> None:
        self.filename = filename
        self.reason = reason
        self.column_attempted = column_attempted
        col_part = f" (column attempted: {column_attempted!r})" if column_attempted else ""
        super().__init__(f"Parse failed for {filename!r}: {reason}{col_part}")


class RetrievalError(Exception):
    """Raised when a retrieval source (Qdrant, pgvector, MS Learn) fails.

    The pipeline proceeds with available results from other sources.
    If Source A (capability KB) also fails, the atom gets
    ``retrieval_confidence=LOW``.
    """

    def __init__(self, *, source: str, atom_id: str, reason: str) -> None:
        self.source = source
        self.atom_id = atom_id
        self.reason = reason
        super().__init__(f"Retrieval failed from {source!r} for atom {atom_id!r}: {reason}")
