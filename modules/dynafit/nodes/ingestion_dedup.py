"""Cosine-similarity deduplication for Phase 1 ingestion.

Uses numpy for vector math (FAISS deferred for batches > 5K atoms).
"""

from __future__ import annotations

from typing import Any

from .ingestion_atomiser import _ClassifiedRequirement


def _deduplicate_requirements(
    requirements: list[_ClassifiedRequirement],
    embedder: Any,
) -> tuple[list[_ClassifiedRequirement], list[_ClassifiedRequirement]]:
    """Cosine-similarity deduplication.

    Returns (unique_requirements, potential_duplicates).

    - cosine > 0.92  → hard merge: remove j, append j.atom_id to i's source_ref
    - cosine 0.80–0.92 → soft flag: j stays in unique, also returned in duplicates
    """
    if len(requirements) <= 1:
        return requirements, []

    import numpy as np  # noqa: PLC0415

    texts = [r.atom.requirement_text for r in requirements]
    matrix = embedder.embed_batch(texts)
    vecs = np.array(matrix, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs = vecs / norms
    sim: Any = vecs @ vecs.T

    hard_merged: set[int] = set()
    soft_flagged: set[int] = set()

    for i in range(len(requirements)):
        if i in hard_merged:
            continue
        for j in range(i + 1, len(requirements)):
            if j in hard_merged:
                continue
            s = float(sim[i, j])
            if s > 0.92:
                hard_merged.add(j)
                existing_ref = requirements[i].atom.source_ref or requirements[i].atom.atom_id
                requirements[i] = _ClassifiedRequirement(
                    atom=requirements[i].atom.model_copy(
                        update={"source_ref": (f"{existing_ref},{requirements[j].atom.atom_id}")}
                    ),
                    intent=requirements[i].intent,
                    module=requirements[i].module,
                )
            elif s > 0.80:
                soft_flagged.add(j)

    unique = [r for idx, r in enumerate(requirements) if idx not in hard_merged]
    duplicates = [r for idx, r in enumerate(requirements) if idx in soft_flagged]
    return unique, duplicates
