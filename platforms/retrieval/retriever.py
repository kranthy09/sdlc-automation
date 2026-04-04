from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, cast

from qdrant_client.http.models import ScoredPoint

from .qdrant_client import get_qdrant_client

QDRANT_COLLECTION_ENV = "QDRANT_COLLECTION"


def search(vector: Sequence[float], top_k: int) -> list[ScoredPoint]:
    """
    Search a Qdrant collection using a precomputed dense vector.

    Notes:
    - No embedding logic here (caller must pass the vector).
    - Collection name is taken from env var `QDRANT_COLLECTION`.
    """
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if not vector:
        raise ValueError("vector must be non-empty")

    collection_name = os.getenv(QDRANT_COLLECTION_ENV)
    if not collection_name:
        raise ValueError(
            f"Missing env var {QDRANT_COLLECTION_ENV}. "
            "Set it to the target Qdrant collection name (e.g. d365_fo_capabilities)."
        )

    client = get_qdrant_client()
    # 'raw results' as returned by the SDK: list[ScoredPoint]
    # NOTE: qdrant-client's type stubs are incomplete in some versions (mypy may not
    # see `.search()` or may treat its return type as Any). Keep Qdrant-specific
    # typing quirks contained in the platform layer.
    raw = cast(Any, client).search(
        collection_name=collection_name,
        query_vector=list(vector),
        limit=top_k,
        with_payload=True,
    )
    return cast(list[ScoredPoint], raw)
