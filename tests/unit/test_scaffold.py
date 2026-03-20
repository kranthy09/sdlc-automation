"""
Layer 0 scaffold smoke tests.

These tests verify the monorepo structure is correct and all package
directories are importable. They are intentionally minimal — the goal
is `make ci` green on an empty codebase before any logic exists.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Package importability
# ---------------------------------------------------------------------------

EXPECTED_PACKAGES = [
    "platform",
    "platform.schemas",
    "platform.llm",
    "platform.retrieval",
    "platform.parsers",
    "platform.storage",
    "platform.observability",
    "platform.config",
    "platform.testing",
    "agents",
    "agents.ingestion",
    "agents.rag",
    "agents.classifier",
    "agents.validator",
    "modules",
    "modules.dynafit",
    "api",
    "api.routes",
    "api.workers",
    "api.websocket",
]


@pytest.mark.unit
@pytest.mark.parametrize("package", EXPECTED_PACKAGES)
def test_package_is_importable(package: str) -> None:
    """Every platform package must be importable from day 1."""
    mod = importlib.import_module(package)
    assert mod is not None


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent.parent

EXPECTED_DIRECTORIES = [
    # Layer 0: platform packages
    "platform/schemas",
    "platform/llm",
    "platform/retrieval",
    "platform/parsers",
    "platform/storage",
    "platform/observability",
    "platform/config",
    "platform/testing",
    # Layer 0: agent stubs
    "agents/ingestion",
    "agents/rag",
    "agents/classifier",
    "agents/validator",
    # Layer 0: module stubs
    "modules/dynafit/prompts",
    "modules/dynafit/tests",
    # Layer 0: API stubs
    "api/routes",
    "api/workers",
    "api/websocket",
    # Layer 0: infra and CI
    "infra/docker",
    "infra/scripts",
    "tests/unit",
    "tests/integration",
    ".github/workflows",
    # knowledge_bases/,
    #  tests/fixtures/golden, docs/ — added in Layer 3
]


@pytest.mark.unit
@pytest.mark.parametrize("directory", EXPECTED_DIRECTORIES)
def test_directory_exists(directory: str) -> None:
    """All required monorepo directories must exist."""
    assert (ROOT / directory).is_dir(), f"Missing directory: {directory}"


# ---------------------------------------------------------------------------
# Critical files
# ---------------------------------------------------------------------------

EXPECTED_FILES = [
    "pyproject.toml",
    "Makefile",
    ".pre-commit-config.yaml",
    ".github/workflows/ci.yml",
    "infra/docker/docker-compose.yaml",
    "infra/docker/prometheus.yml",
    "infra/scripts/validate_contracts.py",
]


@pytest.mark.unit
@pytest.mark.parametrize("filepath", EXPECTED_FILES)
def test_critical_file_exists(filepath: str) -> None:
    """All critical scaffold files must exist."""
    assert (ROOT / filepath).is_file(), f"Missing file: {filepath}"
