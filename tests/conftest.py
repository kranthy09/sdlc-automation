"""
Shared pytest fixtures for all test suites.

Layer 0 scaffold: this file exists so pytest can discover tests from day 1.
Fixtures for mock infrastructure are defined in platform/testing/factories.py
and imported here once Layer 2 is implemented.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Environment guard
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: fast tests with no external dependencies")
    config.addinivalue_line("markers", "integration: tests that require Docker services")
    config.addinivalue_line("markers", "golden: tests using golden fixture files")
    config.addinivalue_line("markers", "llm: tests that require a live LLM (skip in CI)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip LLM tests unless ALLOW_LLM_TESTS env var is set."""
    if os.getenv("ALLOW_LLM_TESTS"):
        return
    skip_llm = pytest.mark.skip(
        reason="Live LLM tests disabled in CI. Set ALLOW_LLM_TESTS=1 to run."
    )
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)
