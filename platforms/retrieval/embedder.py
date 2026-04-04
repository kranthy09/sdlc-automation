from __future__ import annotations

import os
from functools import lru_cache
from typing import Final, cast

import numpy as np
import numpy.typing as npt
from sentence_transformers import SentenceTransformer

# Default matches your architecture docs; override via env for flexibility.
DEFAULT_MODEL_NAME: Final[str] = "BAAI/bge-large-en-v1.5"
MODEL_NAME_ENV: Final[str] = "EMBEDDING_MODEL_NAME"


@lru_cache(maxsize=1)
def _get_model(model_name: str) -> SentenceTransformer:
    """Load the embedding model once per process (singleton via lru_cache)."""
    return SentenceTransformer(model_name)


def embed(text: str) -> list[float]:
    """
    Embed a single text string into a dense vector.

    Returns:
        list[float]: L2-normalized embedding suitable for cosine similarity.
    """
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("embed(text) requires non-empty text")

    model_name = os.getenv(MODEL_NAME_ENV, DEFAULT_MODEL_NAME)
    model = _get_model(model_name)

    # sentence-transformers can normalize internally; we also normalize defensively.
    encoded = model.encode(
        cleaned,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    vec = cast(npt.NDArray[np.float32], np.asarray(encoded, dtype=np.float32))
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm

    # numpy.ndarray.tolist() is typed as Any; make the return type explicit.
    return [float(x) for x in vec.tolist()]
