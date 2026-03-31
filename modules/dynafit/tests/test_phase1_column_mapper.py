"""Unit tests for Phase 1 header column mapping (Block D).

Covers all three resolution tiers plus the multi-table row mapper.
Zero live infrastructure — no LLM, no spaCy model required for
Tiers 1 and 2; Tier 3 is tested via a monkeypatched spaCy mock.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import modules.dynafit.nodes.ingestion_column_mapper as mapper_mod
from modules.dynafit.nodes.ingestion_column_mapper import (
    ColumnMappingResult,
    _map_column_to_canonical,
    _map_table_rows_to_canonical,
)


# ---------------------------------------------------------------------------
# ColumnMappingResult dataclass
# ---------------------------------------------------------------------------


def test_column_mapping_result_fields() -> None:
    r = ColumnMappingResult(
        canonical="requirement_text",
        original_header="Business Requirement",
        confidence=1.0,
        tier_used="exact",
    )
    assert r.canonical == "requirement_text"
    assert r.original_header == "Business Requirement"
    assert r.confidence == 1.0
    assert r.tier_used == "exact"


def test_column_mapping_result_is_frozen() -> None:
    r = ColumnMappingResult(
        canonical=None,
        original_header="x",
        confidence=0.0,
        tier_used="unmatched",
    )
    with pytest.raises((AttributeError, TypeError)):
        r.canonical = "something"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tier 1 — exact match
# ---------------------------------------------------------------------------


def test_tier1_exact_match_known_synonym() -> None:
    r = _map_column_to_canonical("Business Requirement")
    assert r.canonical == "requirement_text"
    assert r.tier_used == "exact"
    assert r.confidence == 1.0
    assert r.original_header == "Business Requirement"


def test_tier1_case_insensitive() -> None:
    r = _map_column_to_canonical("BUSINESS REQUIREMENT")
    assert r.canonical == "requirement_text"
    assert r.tier_used == "exact"
    assert r.confidence == 1.0


def test_tier1_strips_whitespace() -> None:
    r = _map_column_to_canonical("  Requirement ID  ")
    assert r.canonical == "req_id"
    assert r.tier_used == "exact"


def test_tier1_other_canonicals() -> None:
    cases = [
        ("Module", "module"),
        ("Priority", "priority"),
        ("Country", "country"),
        ("Req ID", "req_id"),
    ]
    for header, expected_canonical in cases:
        r = _map_column_to_canonical(header)
        assert r.canonical == expected_canonical, (
            f"{header!r} → expected {expected_canonical!r}, got {r.canonical!r}"
        )
        assert r.tier_used == "exact"


# ---------------------------------------------------------------------------
# Tier 2 — fuzzy match
# ---------------------------------------------------------------------------


def test_tier2_fuzzy_match_truncated_synonym() -> None:
    # "Req Descrip" is not in YAML but token_set_ratio against
    # "Req Description" / "req desc" should be > 70
    r = _map_column_to_canonical("Req Descrip")
    assert r.canonical == "requirement_text"
    assert r.tier_used == "fuzzy"
    assert 0.70 <= r.confidence < 1.0


def test_tier2_fuzzy_confidence_is_normalised() -> None:
    # Confidence should be in [0.0, 1.0], never > 1
    r = _map_column_to_canonical("Req Descrip")
    assert 0.0 <= r.confidence <= 1.0


# ---------------------------------------------------------------------------
# Tier 3 — spaCy similarity (mocked)
# ---------------------------------------------------------------------------


def _make_spacy_mock(similarity_map: dict[str, float]) -> MagicMock:
    """Build a minimal spaCy-like mock.

    similarity_map: {canonical_phrase_prefix: score}
    The mock nlp(text) returns a Doc whose .similarity(other) looks up
    the other doc's text in the map.
    """

    def _make_doc(text: str) -> MagicMock:
        doc = MagicMock()
        doc.text = text

        def _sim(other: Any) -> float:
            for key, score in similarity_map.items():
                if key in other.text:
                    return score
            return 0.1

        doc.similarity.side_effect = _sim
        return doc

    nlp = MagicMock()
    nlp.vocab.vectors.shape = (100, 300)  # non-zero → vectors present
    nlp.side_effect = _make_doc
    return nlp


@pytest.fixture(autouse=True)
def reset_spacy_state():
    """Reset spaCy module-level state before each test to avoid cross-test leakage."""
    original_nlp = mapper_mod._spacy_nlp
    original_unavailable = mapper_mod._spacy_unavailable
    original_docs = mapper_mod._CANONICAL_DOCS
    yield
    mapper_mod._spacy_nlp = original_nlp
    mapper_mod._spacy_unavailable = original_unavailable
    mapper_mod._CANONICAL_DOCS = original_docs


def test_tier3_spacy_resolves_semantic_header() -> None:
    """A header not in YAML but semantically close should resolve via Tier 3."""
    nlp_mock = _make_spacy_mock(
        # "business requirement" appears in the canonical doc for requirement_text
        {"business": 0.82}
    )
    mapper_mod._spacy_nlp = nlp_mock
    mapper_mod._spacy_unavailable = False
    mapper_mod._CANONICAL_DOCS = None  # force rebuild with mock

    # "Functional Specification" is not in YAML and won't fuzzy-match well
    r = _map_column_to_canonical("Functional Specification")
    assert r.tier_used == "nlp"
    assert r.canonical == "requirement_text"
    assert r.confidence > 0.65


def test_tier3_skipped_when_spacy_unavailable() -> None:
    """When spaCy is flagged unavailable, result must be unmatched, not nlp."""
    mapper_mod._spacy_unavailable = True
    r = _map_column_to_canonical("Totally Unknown Header XYZ")
    assert r.tier_used == "unmatched"
    assert r.canonical is None


def test_tier3_skipped_when_no_vectors() -> None:
    """A model with zero vectors should set _spacy_unavailable and skip Tier 3."""
    nlp_mock = MagicMock()
    nlp_mock.vocab.vectors.shape = (0, 0)  # no vectors

    with patch("spacy.load", return_value=nlp_mock):
        mapper_mod._spacy_nlp = None
        mapper_mod._spacy_unavailable = False
        result = mapper_mod._load_spacy_for_mapper()

    assert result is False
    assert mapper_mod._spacy_unavailable is True


# ---------------------------------------------------------------------------
# Unmatched
# ---------------------------------------------------------------------------


def test_unmatched_header_returns_none() -> None:
    mapper_mod._spacy_unavailable = True  # disable Tier 3 for this test
    r = _map_column_to_canonical("XYZZY_IMPOSSIBLE_HEADER_9999")
    assert r.canonical is None
    assert r.tier_used == "unmatched"
    assert r.confidence == 0.0


# ---------------------------------------------------------------------------
# _map_table_rows_to_canonical
# ---------------------------------------------------------------------------


def test_map_rows_empty_input_returns_empty() -> None:
    assert _map_table_rows_to_canonical([]) == []


def test_map_rows_rejects_table_without_requirement_column() -> None:
    rows = [
        {"Module": "Finance", "Priority": "MUST"},
        {"Module": "HR", "Priority": "SHOULD"},
    ]
    assert _map_table_rows_to_canonical(rows) == []


def test_map_rows_resolves_and_filters_empty_req_text() -> None:
    rows = [
        {"Business Requirement": "System shall do X", "Priority": "MUST"},
        {"Business Requirement": "", "Priority": "SHOULD"},  # blank — dropped
        {"Business Requirement": "System shall do Y", "Priority": "COULD"},
    ]
    result = _map_table_rows_to_canonical(rows)
    assert len(result) == 2
    assert result[0]["requirement_text"] == "System shall do X"
    assert result[1]["requirement_text"] == "System shall do Y"


def test_map_rows_maps_all_canonical_fields() -> None:
    rows = [
        {
            "Business Requirement": "The system must export to Excel",
            "Req ID": "REQ-001",
            "Module": "Finance",
            "Priority": "MUST",
            "Country": "DE",
        }
    ]
    result = _map_table_rows_to_canonical(rows)
    assert len(result) == 1
    row = result[0]
    assert row["requirement_text"] == "The system must export to Excel"
    assert row["req_id"] == "REQ-001"
    assert row["module"] == "Finance"
    assert row["priority"] == "MUST"
    assert row["country"] == "DE"


def test_map_rows_multi_table_union_of_keys() -> None:
    """Rows from different tables (different schemas) are all mapped correctly.

    Simulates pdfplumber returning rows from two tables with different headers
    in the same flat list.  Without the union-of-keys fix only Table A rows
    would have been mapped.
    """
    table_a_rows = [
        {"Business Requirement": "Req from table A", "Priority": "MUST"},
    ]
    table_b_rows = [
        # Table B uses different column names for the same canonical fields
        {"Requirement Text": "Req from table B", "Importance": "SHOULD"},
    ]
    rows = table_a_rows + table_b_rows
    result = _map_table_rows_to_canonical(rows)
    req_texts = [r["requirement_text"] for r in result]
    assert "Req from table A" in req_texts
    assert "Req from table B" in req_texts
