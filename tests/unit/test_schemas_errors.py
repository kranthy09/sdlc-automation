"""
Tests for platform/schemas/errors.py — typed platform exceptions.

One test per error type: catchable as Exception, carries structured fields, str() includes key info.
"""

from __future__ import annotations

import pytest

from platform.schemas.errors import (
    ParseError,
    RetrievalError,
    UnsupportedFormatError,
)


@pytest.mark.unit
def test_unsupported_format_error() -> None:
    """UnsupportedFormatError is catchable and carries filename + mime."""
    with pytest.raises(UnsupportedFormatError) as exc_info:
        raise UnsupportedFormatError(filename="data.bin", detected_mime="application/octet-stream")
    err = exc_info.value
    assert isinstance(err, Exception)
    assert err.filename == "data.bin"
    assert err.detected_mime == "application/octet-stream"
    assert "data.bin" in str(err)


@pytest.mark.unit
def test_parse_error() -> None:
    """ParseError is catchable and carries filename + reason."""
    with pytest.raises(ParseError) as exc_info:
        raise ParseError(filename="reqs.pdf", reason="requirement_text column not found")
    err = exc_info.value
    assert isinstance(err, Exception)
    assert err.filename == "reqs.pdf"
    assert err.reason == "requirement_text column not found"
    assert "reqs.pdf" in str(err)


@pytest.mark.unit
def test_retrieval_error() -> None:
    """RetrievalError is catchable and carries source + atom_id + reason."""
    with pytest.raises(RetrievalError) as exc_info:
        raise RetrievalError(source="qdrant", atom_id="atom-001", reason="timeout")
    err = exc_info.value
    assert isinstance(err, Exception)
    assert err.source == "qdrant"
    assert err.atom_id == "atom-001"
    assert "qdrant" in str(err)
