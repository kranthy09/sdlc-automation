"""
Requirement pipeline schemas — the data shapes for Phase 1 (Ingestion).

Pipeline progression:
  RawUpload → RequirementAtom → ValidatedAtom   (happy path)
                              ↘ FlaggedAtom      (quality gate rejection)

RawUpload       — raw file bytes + metadata before any processing
RequirementAtom — single atomic requirement extracted from the document
                  (after atomization, before validation)
ValidatedAtom   — atom that has passed all Phase 1 quality gates
                  (specificity, schema consistency, completeness)
FlaggedAtom     — atom rejected or held for human review, with typed reason
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from .base import PlatformModel

# ---------------------------------------------------------------------------
# Constrained vocabulary: D365 F&O module names
# The LLM Module Tagger forces selection from this list (Phase 1 Step 2C).
# ---------------------------------------------------------------------------

D365Module = Literal[
    "AccountsPayable",
    "AccountsReceivable",
    "GeneralLedger",
    "FixedAssets",
    "Budgeting",
    "CashAndBankManagement",
    "ProcurementAndSourcing",
    "InventoryManagement",
    "ProductionControl",
    "SalesAndMarketing",
    "ProjectManagement",
    "HumanResources",
    "Warehouse",
    "Transportation",
    "MasterPlanning",
    "OrganizationAdministration",
    "SystemAdministration",
]


# ---------------------------------------------------------------------------
# RawUpload
# ---------------------------------------------------------------------------


class RawUpload(PlatformModel):
    """A single uploaded document before any processing begins."""

    upload_id: str
    filename: Annotated[str, Field(min_length=1)]
    file_bytes: bytes
    product_id: str
    country: str = ""
    wave: Annotated[int, Field(ge=1)] = 1
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# RequirementAtom
# ---------------------------------------------------------------------------


class RequirementAtom(PlatformModel):
    """One atomic requirement extracted from a document.

    Created after Phase 1 Step 2 (Atomizer). Has not yet passed quality gates.
    content_type tracks how this atom was derived:
      'text'          — from a table row or prose paragraph
      'image_derived' — extracted from an embedded image via vision LLM
      'prose'         — from a prose chunk splitter
    """

    atom_id: str
    upload_id: str
    requirement_text: Annotated[str, Field(min_length=1)]

    # Source provenance
    source_row: int | None = None
    source_document: str = ""
    source_ref: str | None = None  # e.g. "page_3_image_1"

    # Raw module hint from the source document (not yet normalised to D365Module)
    raw_module_hint: str | None = None

    # Derivation type
    content_type: Literal["text", "image_derived", "prose"] = "text"

    # Image-derived enrichment (populated only when content_type="image_derived")
    image_components: list[str] = Field(default_factory=list)
    d365_modules_implied: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# ValidatedAtom
# ---------------------------------------------------------------------------


class ValidatedAtom(PlatformModel):
    """A RequirementAtom that has passed all Phase 1 quality gates.

    Guarantees:
      - requirement_text is 10–2000 chars
      - module is from the D365 constrained vocabulary
      - specificity_score >= 0.30 (ambiguity detector threshold)
      - intent is classified into one of four canonical types
    """

    atom_id: str
    upload_id: str

    # Validated, normalised requirement text
    requirement_text: Annotated[str, Field(min_length=10, max_length=2000)]

    # Normalised to D365 constrained vocabulary by the Module Tagger
    module: D365Module

    country: str
    wave: Annotated[int, Field(ge=1)]

    # MoSCoW priority (from source or keyword-inferred)
    priority: Literal["MUST", "SHOULD", "COULD"] = "SHOULD"

    # Intent classification from Phase 1 Step 2B
    intent: Literal["FUNCTIONAL", "NON_FUNCTIONAL", "INTEGRATION", "REPORTING"]

    # Derivation type (preserved from RequirementAtom)
    content_type: Literal["text", "image_derived", "prose"] = "text"

    # spaCy NER entity hints used by Phase 2 retrieval query builder
    entity_hints: list[str] = Field(default_factory=list)

    # Quality scores from Phase 1 Step 4
    specificity_score: Annotated[float, Field(ge=0.0, le=1.0)]
    completeness_score: Annotated[float, Field(ge=0.0, le=100.0)]

    # Audit trail: source references (merged from duplicates if deduped)
    source_refs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FlaggedAtom
# ---------------------------------------------------------------------------


class FlaggedAtom(PlatformModel):
    """A RequirementAtom rejected or held for human review by quality gates.

    flag_reason codes:
      TOO_VAGUE          — specificity_score < 0.30
      SCHEMA_MISMATCH    — module vs entity_hints inconsistency detected
      POTENTIAL_DUPLICATE — cosine similarity 0.80–0.92 with another atom
      INCOMPLETE         — completeness_score < 30 AND specificity borderline
    """

    atom_id: str
    upload_id: str
    requirement_text: Annotated[str, Field(min_length=1)]

    flag_reason: Literal["TOO_VAGUE", "SCHEMA_MISMATCH", "POTENTIAL_DUPLICATE", "INCOMPLETE"]
    flag_detail: str

    # May be None if the atom was flagged before scoring completed
    specificity_score: Annotated[float, Field(ge=0.0, le=1.0)] | None = None

    source_refs: list[str] = Field(default_factory=list)
