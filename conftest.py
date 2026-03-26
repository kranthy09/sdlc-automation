"""
Root conftest.py — loaded by pytest before any test collection.

This file ensures the project root is at the FRONT of sys.path so that
our first-party packages take precedence over similarly named modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Prepend the project root so local packages can be imported consistently.
_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
elif sys.path[0] != _root:
    sys.path.remove(_root)
    sys.path.insert(0, _root)

# NOTE:
# We intentionally do NOT delete `platform` from sys.modules anymore.
# This repo uses `platforms/` to avoid shadowing Python's stdlib `platform`.
