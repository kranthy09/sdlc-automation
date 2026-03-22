"""
Root conftest.py — loaded by pytest before any test collection.

This file ensures the project root is at the FRONT of sys.path so that
our `platform/` package takes precedence over Python's stdlib `platform`
module (which is a single-file module and would otherwise shadow our package).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Prepend the project root so `platform/` (our package) beats stdlib `platform.py`
_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
elif sys.path[0] != _root:
    sys.path.remove(_root)
    sys.path.insert(0, _root)

# Pre-load packages that import from stdlib `platform` while it is still in
# sys.modules so they stay cached and never re-import it after the clear below.
import wsgiref.simple_server  # noqa: F401, E402

# Python caches the stdlib `platform` module in sys.modules at startup before
# conftest.py runs. Clear it so subsequent imports resolve to our platform/
# package (a proper directory package with __init__.py) instead of the stdlib
# single-file module.
for _key in list(sys.modules.keys()):
    if _key == "platform" or _key.startswith("platform."):
        del sys.modules[_key]
