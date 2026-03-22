"""Single source of truth for the D365 F&O ProductConfig.

All DYNAFIT nodes import from here instead of duplicating the constant.
"""

from __future__ import annotations

from platform.schemas.product import ProductConfig

_D365_FO_CONFIG: ProductConfig = ProductConfig(
    product_id="d365_fo",
    display_name="Dynamics 365 Finance & Operations",
    llm_model="claude-sonnet-4-6",
    embedding_model="BAAI/bge-small-en-v1.5",
    capability_kb_namespace="d365_fo_capabilities",
    doc_corpus_namespace="d365_fo_docs",
    historical_fitments_table="d365_fo_fitments",
    fit_confidence_threshold=0.85,
    review_confidence_threshold=0.60,
    auto_approve_with_history=True,
    country_rules_path="knowledge_bases/d365_fo/country_rules/",
    fdd_template_path="knowledge_bases/d365_fo/fdd_templates/fit_template.j2",
    code_language="xpp",
)


def get_product_config(product_id: str) -> ProductConfig:
    """Return ProductConfig for the given product_id. MVP: d365_fo only."""
    if product_id == "d365_fo":
        return _D365_FO_CONFIG
    return _D365_FO_CONFIG.model_copy(update={"product_id": product_id})
