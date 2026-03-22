"""
ProductConfig — the multi-product key for the platform.

Every parameter that varies by product (model name, thresholds, KB namespaces,
table names, code language) lives here. Nodes receive a ProductConfig instance
and must never hardcode any of these values.

Invariant: review_confidence_threshold < fit_confidence_threshold
  — items above fit threshold are auto-approved
  — items between review and fit thresholds go to human review
  — items below review threshold are escalated immediately
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import PlatformModel


class ProductConfig(PlatformModel):
    # Identity
    product_id: str
    display_name: str

    # AI model configuration
    llm_model: str
    embedding_model: str
    reranker_model: str = (
        "Xenova/ms-marco-MiniLM-L-6-v2"
    )

    # Knowledge base namespaces (Qdrant collections)
    capability_kb_namespace: str
    doc_corpus_namespace: str

    # Historical fitments table (PostgreSQL)
    historical_fitments_table: str

    # Confidence thresholds — must satisfy review < fit
    fit_confidence_threshold: Annotated[float, Field(gt=0.0, lt=1.0)]
    review_confidence_threshold: Annotated[float, Field(gt=0.0, lt=1.0)]

    # Behaviour flags
    auto_approve_with_history: bool

    # File paths (relative to repo root)
    country_rules_path: str
    fdd_template_path: str

    # Target coding language for customisation work
    code_language: Literal["xpp", "abap", "apex"]

    @model_validator(mode="after")
    def review_threshold_below_fit(self) -> Self:
        if self.review_confidence_threshold >= self.fit_confidence_threshold:
            raise ValueError(
                f"review_confidence_threshold ({self.review_confidence_threshold}) "
                f"must be strictly less than fit_confidence_threshold "
                f"({self.fit_confidence_threshold})"
            )
        return self
