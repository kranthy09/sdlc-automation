"""
Tests for platform/schemas/product.py — ProductConfig validation boundaries.

Keeps: threshold ordering invariant (review < fit), code_language whitelist,
required fields, range constraints.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform.schemas.product import ProductConfig

VALID_KWARGS = {
    "product_id": "d365_fo",
    "display_name": "D365 F&O",
    "llm_model": "claude-sonnet-4-6",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "capability_kb_namespace": "d365_fo_capabilities",
    "doc_corpus_namespace": "d365_fo_docs",
    "historical_fitments_table": "d365_fo_fitments",
    "fit_confidence_threshold": 0.85,
    "review_confidence_threshold": 0.60,
    "auto_approve_with_history": True,
    "country_rules_path": "knowledge_bases/d365_fo/country_rules",
    "fdd_template_path": "knowledge_bases/d365_fo/fdd_templates/fit_template.j2",
    "code_language": "xpp",
}


@pytest.mark.unit
def test_creates_valid() -> None:
    cfg = ProductConfig(**VALID_KWARGS)
    assert cfg.product_id == "d365_fo"
    assert cfg.fit_confidence_threshold == 0.85


@pytest.mark.unit
def test_invalid_code_language_raises() -> None:
    with pytest.raises(ValidationError):
        ProductConfig(**{**VALID_KWARGS, "code_language": "java"})


@pytest.mark.unit
def test_fit_threshold_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        ProductConfig(**{**VALID_KWARGS, "fit_confidence_threshold": 1.5})


@pytest.mark.unit
def test_review_threshold_must_be_less_than_fit() -> None:
    """review_confidence_threshold >= fit_confidence_threshold is a business rule violation."""
    with pytest.raises(ValidationError):
        ProductConfig(
            **{
                **VALID_KWARGS,
                "fit_confidence_threshold": 0.75,
                "review_confidence_threshold": 0.75,
            }
        )

    with pytest.raises(ValidationError):
        ProductConfig(
            **{
                **VALID_KWARGS,
                "fit_confidence_threshold": 0.70,
                "review_confidence_threshold": 0.80,
            }
        )


@pytest.mark.unit
def test_missing_required_field_raises() -> None:
    kwargs = {k: v for k, v in VALID_KWARGS.items() if k != "product_id"}
    with pytest.raises(ValidationError):
        ProductConfig(**kwargs)


@pytest.mark.unit
def test_whitespace_stripped() -> None:
    cfg = ProductConfig(**{**VALID_KWARGS, "product_id": "  d365_fo  "})
    assert cfg.product_id == "d365_fo"
