from __future__ import annotations

import os
from functools import lru_cache

from qdrant_client import QdrantClient

QDRANT_HOST_ENV = "QDRANT_HOST"
QDRANT_PORT_ENV = "QDRANT_PORT"
QDRANT_TIMEOUT_ENV = "QDRANT_TIMEOUT"

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 6333
DEFAULT_TIMEOUT_SEC = 30


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """
    Singleton Qdrant client initialization.

    Uses defaults:
      - host: localhost
      - port: 6333
    Override via env vars if needed.
    """
    host = os.getenv(QDRANT_HOST_ENV, DEFAULT_HOST)
    port = int(os.getenv(QDRANT_PORT_ENV, str(DEFAULT_PORT)))
    timeout = int(os.getenv(QDRANT_TIMEOUT_ENV, str(DEFAULT_TIMEOUT_SEC)))

    return QdrantClient(host=host, port=port, timeout=timeout)
