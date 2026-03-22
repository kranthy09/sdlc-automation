"""Pre-download fastembed models so they're cached in the Docker image.

Reads model names from each product's ProductConfig — no hardcoded strings.
Run during Docker build:  uv run python -m infra.scripts.download_models
"""

from __future__ import annotations

import importlib
import pkgutil

import modules  # noqa: F401 — ensure package is importable


def _discover_models() -> tuple[set[str], set[str]]:
    """Walk modules/*/product_config.py and collect embedding + reranker models."""
    embedding_models: set[str] = set()
    reranker_models: set[str] = set()

    for mod_info in pkgutil.iter_modules(modules.__path__, modules.__name__ + "."):
        try:
            cfg_mod = importlib.import_module(f"{mod_info.name}.product_config")
        except (ModuleNotFoundError, ImportError):
            continue

        for attr in vars(cfg_mod).values():
            if hasattr(attr, "embedding_model") and hasattr(attr, "reranker_model"):
                embedding_models.add(attr.embedding_model)
                reranker_models.add(attr.reranker_model)

    return embedding_models, reranker_models


def main() -> None:
    embedding_models, reranker_models = _discover_models()

    if not embedding_models and not reranker_models:
        print("WARNING: no ProductConfig instances found — nothing to download")
        return

    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder.text_cross_encoder import TextCrossEncoder

    for model in sorted(embedding_models):
        print(f"Downloading embedding model: {model}")
        TextEmbedding(model)

    for model in sorted(reranker_models):
        print(f"Downloading reranker model: {model}")
        TextCrossEncoder(model)

    print("All models downloaded.")


if __name__ == "__main__":
    main()
