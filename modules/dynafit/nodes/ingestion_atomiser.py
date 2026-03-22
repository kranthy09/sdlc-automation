"""LLM atomisation + classification for Phase 1 ingestion.

Contains the D365 module vocabulary, LLM response schemas,
the internal _ClassifiedRequirement record, and the combined
atomise-and-classify call (single and batch variants).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from platform.llm.client import LLMClient
from platform.observability.logger import get_logger
from platform.schemas.product import ProductConfig

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# D365 module constrained vocabulary
# ---------------------------------------------------------------------------

_D365_MODULES: list[str] = [
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
_MODULE_SET: frozenset[str] = frozenset(_D365_MODULES)
_MODULE_LIST_STR: str = ", ".join(_D365_MODULES)

# ---------------------------------------------------------------------------
# LLM response schemas (private — not part of module public API)
# ---------------------------------------------------------------------------

_IntentLiteral = Literal["FUNCTIONAL", "NON_FUNCTIONAL", "INTEGRATION", "REPORTING"]


class _ClassifiedAtom(BaseModel):
    """One atom with intent and module as produced by the LLM."""

    text: str
    intent: _IntentLiteral
    module: str  # validated against _MODULE_SET after parsing


class _AtomizationResult(BaseModel):
    """LLM tool-use output schema for the combined atomise + classify call."""

    atoms: list[_ClassifiedAtom]


# ---------------------------------------------------------------------------
# Internal pipeline record — carries LLM classification through deduplication
# ---------------------------------------------------------------------------


@dataclass
class _ClassifiedRequirement:
    """RequirementAtom plus its LLM-assigned intent and module.

    Exists only inside the ingestion pipeline.  Converted to
    ValidatedAtom / FlaggedAtom at the final quality-gate step.
    """

    atom: RequirementAtom  # noqa: F821 — forward ref resolved at runtime
    intent: _IntentLiteral
    module: str  # validated D365 module string


# Resolve forward reference
from platform.schemas.requirement import RequirementAtom  # noqa: E402, PLC0415

_ClassifiedRequirement.__annotations__["atom"] = RequirementAtom

# ---------------------------------------------------------------------------
# LLM call: atomise + classify intent + tag module (one call per raw text)
# ---------------------------------------------------------------------------

_ATOMISATION_PROMPT = """\
You are a D365 F&O requirements analyst.

TASK 1 — SPLIT:
Decompose the requirement text below into atomic requirements.
Each atom describes exactly ONE functional need.
- Start each atom with "The system shall..." or "The system must..."
- Preserve all specific details (thresholds, field names, frequencies)
- If the text is already a single requirement, return it as a single atom

TASK 2 — CLASSIFY each atom:
  intent: exactly one of FUNCTIONAL, NON_FUNCTIONAL, INTEGRATION, REPORTING
  module: exactly one of: {module_list}

Requirement text:
{text}
"""


def _atomise_and_classify(
    text: str,
    llm: LLMClient,
    config: ProductConfig,
) -> list[_ClassifiedAtom]:
    """Split and classify one raw text via LLM. Fails safe to a single atom."""
    prompt = _ATOMISATION_PROMPT.format(
        module_list=_MODULE_LIST_STR,
        text=text[:3000],
    )
    _fallback = _ClassifiedAtom(
        text=text.strip(),
        intent="FUNCTIONAL",
        module="OrganizationAdministration",
    )
    try:
        result: _AtomizationResult = llm.complete(
            prompt, _AtomizationResult, config, temperature=0.0
        )
        items: list[_ClassifiedAtom] = []
        for item in result.atoms:
            module = item.module if item.module in _MODULE_SET else "OrganizationAdministration"
            trimmed = item.text.strip()
            if trimmed:
                items.append(_ClassifiedAtom(text=trimmed, intent=item.intent, module=module))
        return items or [_fallback]
    except Exception as exc:
        log.warning("atomise_llm_failed", error=str(exc), preview=text[:80])
        return [_fallback]


# ---------------------------------------------------------------------------
# Batch LLM call: atomise + classify multiple chunks in one call
# ---------------------------------------------------------------------------


class _BatchAtomizationResult(BaseModel):
    """LLM tool-use output for batch atomization.

    results must contain exactly as many entries as the input chunks.
    One _AtomizationResult per chunk, in the same order.
    """

    results: list[_AtomizationResult]


_BATCH_ATOMISATION_PROMPT = """\
You are a D365 F&O requirements analyst.

For EACH numbered chunk below, independently:
  SPLIT into atomic requirements (each atom describes exactly ONE functional need)
  - Start each atom with "The system shall..." or "The system must..."
  - Preserve all specific details (thresholds, field names, frequencies)
  - If already a single requirement, return it as one atom
  CLASSIFY each atom:
    intent: exactly one of FUNCTIONAL, NON_FUNCTIONAL, INTEGRATION, REPORTING
    module: exactly one of: {module_list}

Return `results` with exactly {n_chunks} entries, one per input chunk in the same order.

CHUNKS:
{chunks}
"""


def _try_batch_call(
    texts: list[str],
    llm: LLMClient,
    config: ProductConfig,
) -> list[list[_ClassifiedAtom]] | None:
    """Atomize a batch of texts in one LLM call.

    Returns a list-of-lists (one inner list per input text) on success,
    or None when the call fails or the response count mismatches input.
    Callers must fall back to individual _atomise_and_classify calls on None.
    """
    chunks_str = "\n\n".join(f"[{i + 1}] {text[:2000]}" for i, text in enumerate(texts))
    prompt = _BATCH_ATOMISATION_PROMPT.format(
        module_list=_MODULE_LIST_STR,
        n_chunks=len(texts),
        chunks=chunks_str,
    )
    try:
        result: _BatchAtomizationResult = llm.complete(
            prompt, _BatchAtomizationResult, config, temperature=0.0
        )
        if len(result.results) != len(texts):
            log.warning(
                "batch_atomise_count_mismatch",
                expected=len(texts),
                got=len(result.results),
            )
            return None
        out: list[list[_ClassifiedAtom]] = []
        for chunk_result in result.results:
            items: list[_ClassifiedAtom] = []
            for item in chunk_result.atoms:
                trimmed = item.text.strip()
                if trimmed:
                    module = (
                        item.module if item.module in _MODULE_SET else "OrganizationAdministration"
                    )
                    items.append(_ClassifiedAtom(text=trimmed, intent=item.intent, module=module))
            out.append(items)
        return out
    except Exception as exc:
        log.warning("batch_atomise_failed", error=str(exc))
        return None


def _atomise_and_classify_batch(
    texts: list[str],
    llm: LLMClient,
    config: ProductConfig,
    batch_size: int = 10,
) -> list[list[_ClassifiedAtom]]:
    """Atomize and classify all texts, sending `batch_size` chunks per LLM call.

    Reduces N sequential LLM calls to ceil(N / batch_size) calls.
    Falls back to individual _atomise_and_classify calls for any batch
    where the batch call fails or returns a count mismatch.
    """
    all_results: list[list[_ClassifiedAtom]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        chunk_atoms = _try_batch_call(batch, llm, config)
        if chunk_atoms is None:
            # Batch call failed — fall back to per-text calls for this group
            chunk_atoms = [_atomise_and_classify(t, llm, config) for t in batch]
        all_results.extend(chunk_atoms)
    return all_results
