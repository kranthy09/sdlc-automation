"""
Tests for platform/schemas/errors.py — typed platform exceptions.

TDD Layer 1: errors must be typed Python exceptions (not raw strings),
catchable as standard Exception, and carry structured fields.
"""

from __future__ import annotations

import pytest

from platform.schemas.errors import ParseError, RetrievalError, UnsupportedFormatError


@pytest.mark.unit
class TestUnsupportedFormatError:
    def test_is_exception(self) -> None:
        err = UnsupportedFormatError(filename="data.bin", detected_mime="application/octet-stream")
        assert isinstance(err, Exception)

    def test_carries_filename(self) -> None:
        err = UnsupportedFormatError(filename="report.xyz", detected_mime=None)
        assert err.filename == "report.xyz"

    def test_carries_detected_mime(self) -> None:
        err = UnsupportedFormatError(filename="file.bin", detected_mime="application/x-unknown")
        assert err.detected_mime == "application/x-unknown"

    def test_detected_mime_optional(self) -> None:
        err = UnsupportedFormatError(filename="file.bin", detected_mime=None)
        assert err.detected_mime is None

    def test_str_contains_filename(self) -> None:
        err = UnsupportedFormatError(filename="weirdfile.xyz", detected_mime=None)
        assert "weirdfile.xyz" in str(err)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(UnsupportedFormatError) as exc_info:
            raise UnsupportedFormatError(filename="bad.bin", detected_mime="text/plain")
        assert exc_info.value.filename == "bad.bin"

    def test_also_catchable_as_generic_exception(self) -> None:
        err = UnsupportedFormatError(filename="f.bin", detected_mime=None)
        assert isinstance(err, Exception)


@pytest.mark.unit
class TestParseError:
    def test_is_exception(self) -> None:
        err = ParseError(filename="reqs.pdf", reason="requirement_text column not found")
        assert isinstance(err, Exception)

    def test_carries_filename(self) -> None:
        err = ParseError(filename="reqs.pdf", reason="no header row")
        assert err.filename == "reqs.pdf"

    def test_carries_reason(self) -> None:
        err = ParseError(filename="reqs.pdf", reason="requirement_text column not found")
        assert err.reason == "requirement_text column not found"

    def test_column_attempted_optional(self) -> None:
        err = ParseError(filename="f.pdf", reason="missing column", column_attempted=None)
        assert err.column_attempted is None

    def test_column_attempted_stored(self) -> None:
        err = ParseError(filename="f.pdf", reason="fuzzy match failed", column_attempted="Req Desc")
        assert err.column_attempted == "Req Desc"

    def test_str_contains_filename_and_reason(self) -> None:
        err = ParseError(filename="data.pdf", reason="no requirement_text")
        assert "data.pdf" in str(err)
        assert "no requirement_text" in str(err)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            raise ParseError(filename="f.pdf", reason="bad header")
        assert exc_info.value.reason == "bad header"


@pytest.mark.unit
class TestRetrievalError:
    def test_is_exception(self) -> None:
        err = RetrievalError(source="qdrant", atom_id="atom-001", reason="timeout")
        assert isinstance(err, Exception)

    def test_carries_source(self) -> None:
        err = RetrievalError(source="pgvector", atom_id="atom-001", reason="connection refused")
        assert err.source == "pgvector"

    def test_carries_atom_id(self) -> None:
        err = RetrievalError(source="qdrant", atom_id="atom-42", reason="timeout")
        assert err.atom_id == "atom-42"

    def test_carries_reason(self) -> None:
        err = RetrievalError(source="qdrant", atom_id="a1", reason="5s timeout exceeded")
        assert err.reason == "5s timeout exceeded"

    def test_str_contains_all_fields(self) -> None:
        err = RetrievalError(source="qdrant", atom_id="a-007", reason="network error")
        s = str(err)
        assert "qdrant" in s
        assert "a-007" in s
        assert "network error" in s

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(RetrievalError) as exc_info:
            raise RetrievalError(source="ms_learn", atom_id="a1", reason="DNS failure")
        assert exc_info.value.source == "ms_learn"
