"""
Tests for platform/schemas/product.py — ProductConfig.

ProductConfig is the multi-product key: all product-variant parameters
live here, never hardcoded in nodes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform.schemas.product import ProductConfig

# ---------------------------------------------------------------------------
# Minimal valid fixture
# ---------------------------------------------------------------------------

VALID_KWARGS = {
    "product_id": "d365_fo",
    "display_name": "D365 F&O",
    "llm_model": "claude-sonnet-4-6",
    "embedding_model": "BAAI/bge-large-en-v1.5",
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
class TestProductConfigValid:
    def test_creates_with_all_fields(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        assert cfg.product_id == "d365_fo"

    def test_all_string_fields_accessible(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        assert cfg.display_name == "D365 F&O"
        assert cfg.llm_model == "claude-sonnet-4-6"
        assert cfg.embedding_model == "BAAI/bge-large-en-v1.5"
        assert cfg.capability_kb_namespace == "d365_fo_capabilities"
        assert cfg.doc_corpus_namespace == "d365_fo_docs"
        assert cfg.historical_fitments_table == "d365_fo_fitments"

    def test_thresholds_stored(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        assert cfg.fit_confidence_threshold == 0.85
        assert cfg.review_confidence_threshold == 0.60

    def test_code_language_xpp(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        assert cfg.code_language == "xpp"

    def test_code_language_abap(self) -> None:
        cfg = ProductConfig(**{**VALID_KWARGS, "code_language": "abap"})
        assert cfg.code_language == "abap"

    def test_code_language_apex(self) -> None:
        cfg = ProductConfig(**{**VALID_KWARGS, "code_language": "apex"})
        assert cfg.code_language == "apex"

    def test_auto_approve_with_history(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        assert cfg.auto_approve_with_history is True

    def test_whitespace_stripped_on_product_id(self) -> None:
        cfg = ProductConfig(**{**VALID_KWARGS, "product_id": "  d365_fo  "})
        assert cfg.product_id == "d365_fo"

    def test_whitespace_stripped_on_display_name(self) -> None:
        cfg = ProductConfig(**{**VALID_KWARGS, "display_name": "  D365 F&O  "})
        assert cfg.display_name == "D365 F&O"


@pytest.mark.unit
class TestProductConfigInvalid:
    def test_missing_product_id_raises(self) -> None:
        kwargs = {k: v for k, v in VALID_KWARGS.items() if k != "product_id"}
        with pytest.raises(ValidationError):
            ProductConfig(**kwargs)

    def test_missing_llm_model_raises(self) -> None:
        kwargs = {k: v for k, v in VALID_KWARGS.items() if k != "llm_model"}
        with pytest.raises(ValidationError):
            ProductConfig(**kwargs)

    def test_invalid_code_language_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProductConfig(**{**VALID_KWARGS, "code_language": "java"})

    def test_fit_threshold_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProductConfig(**{**VALID_KWARGS, "fit_confidence_threshold": 1.5})

    def test_review_threshold_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProductConfig(**{**VALID_KWARGS, "review_confidence_threshold": -0.1})

    def test_review_threshold_equal_to_fit_raises(self) -> None:
        # review must be strictly less than fit
        with pytest.raises(ValidationError):
            ProductConfig(
                **{
                    **VALID_KWARGS,
                    "fit_confidence_threshold": 0.75,
                    "review_confidence_threshold": 0.75,
                }
            )

    def test_review_threshold_above_fit_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProductConfig(
                **{
                    **VALID_KWARGS,
                    "fit_confidence_threshold": 0.70,
                    "review_confidence_threshold": 0.80,
                }
            )


@pytest.mark.unit
class TestProductConfigFrozen:
    def test_assignment_raises(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        with pytest.raises(ValidationError):
            cfg.product_id = "other"  # type: ignore[misc]

    def test_is_hashable(self) -> None:
        cfg = ProductConfig(**VALID_KWARGS)
        assert isinstance(hash(cfg), int)
