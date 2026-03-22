"""
Embedding utility — wraps fastembed for dense vector generation.

Produces float vectors using any fastembed-compatible model
(default: BAAI/bge-small-en-v1.5, 384-dim per the retrieval schema).

fastembed uses ONNX Runtime instead of PyTorch — ~50 MB install vs ~500 MB.
Model weights are downloaded on first use to fastembed's cache directory.

Usage:

    from platform.retrieval.embedder import Embedder

    embedder = Embedder(config.embedding_model)
    vec = embedder.embed(text)
"""

from __future__ import annotations

from typing import Any

from platform.observability.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class EmbedderError(Exception):
    """Raised when embedding fails — model load error or encode failure."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


class Embedder:
    """Dense vector embedder backed by fastembed (ONNX Runtime).

    The underlying model is loaded lazily on the first encode call so that
    importing this module never triggers the ~500 MB model download.

    Args:
        model_name: HuggingFace model ID (e.g. "BAAI/bge-small-en-v1.5").
        _model:     Pre-loaded model instance — for testing only; skips lazy load.
    """

    def __init__(
        self,
        model_name: str,
        *,
        _model: Any = None,
    ) -> None:
        self._model_name = model_name
        self._model: Any = _model

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding  # noqa: PLC0415

            log.info("embedder_load_model", model=self._model_name)
            self._model = TextEmbedding(self._model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        """Embed a single text string into a dense float vector.

        Args:
            text: The text to embed.

        Returns:
            Float vector as list[float].

        Raises:
            EmbedderError: If the model fails to load or encode.
        """
        try:
            vec: Any = next(iter(self._get_model().embed([text])))
            log.debug("embedder_encode", model=self._model_name, dim=len(vec))
            result: list[float] = vec.tolist()
            return result
        except EmbedderError:
            raise
        except Exception as exc:
            raise EmbedderError(
                f"embed failed (model={self._model_name!r}): {exc}", cause=exc
            ) from exc

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into dense float vectors.

        Args:
            texts: Texts to embed.

        Returns:
            List of float vectors, one per input text.

        Raises:
            EmbedderError: If the model fails to load or encode.
        """
        try:
            vecs: list[Any] = list(self._get_model().embed(texts))
            log.debug("embedder_encode_batch", model=self._model_name, n=len(texts))
            result: list[list[float]] = [v.tolist() for v in vecs]
            return result
        except EmbedderError:
            raise
        except Exception as exc:
            raise EmbedderError(
                f"embed_batch failed (model={self._model_name!r}): {exc}", cause=exc
            ) from exc

