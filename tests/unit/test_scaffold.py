"""
Layer 0 scaffold smoke tests.

Single batch checks for package imports, directories, and critical files.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

EXPECTED_PACKAGES = [
    "platform", "platform.schemas", "platform.llm", "platform.retrieval",
    "platform.parsers", "platform.storage", "platform.observability",
    "platform.config", "platform.testing",
    "agents", "agents.ingestion", "agents.rag", "agents.classifier", "agents.validator",
    "modules", "modules.dynafit",
    "api", "api.routes", "api.workers", "api.websocket",
]

EXPECTED_DIRECTORIES = [
    "platform/schemas", "platform/llm", "platform/retrieval", "platform/parsers",
    "platform/storage", "platform/observability", "platform/config", "platform/testing",
    "agents/ingestion", "agents/rag", "agents/classifier", "agents/validator",
    "modules/dynafit/prompts", "modules/dynafit/tests",
    "api/routes", "api/workers", "api/websocket",
    "infra/docker", "infra/scripts", "tests/unit", "tests/integration",
    ".github/workflows",
]

EXPECTED_FILES = [
    "pyproject.toml", "Makefile", ".pre-commit-config.yaml",
    ".github/workflows/ci.yml", "infra/docker/docker-compose.yaml",
    "infra/docker/prometheus.yml", "infra/scripts/validate_contracts.py",
]


@pytest.mark.unit
def test_all_packages_importable() -> None:
    """Every platform package must be importable."""
    for package in EXPECTED_PACKAGES:
        mod = importlib.import_module(package)
        assert mod is not None, f"Failed to import {package}"


@pytest.mark.unit
def test_all_directories_exist() -> None:
    """All required monorepo directories must exist."""
    missing = [d for d in EXPECTED_DIRECTORIES if not (ROOT / d).is_dir()]
    assert missing == [], f"Missing directories: {missing}"


@pytest.mark.unit
def test_critical_files_exist() -> None:
    """All critical scaffold files must exist."""
    missing = [f for f in EXPECTED_FILES if not (ROOT / f).is_file()]
    assert missing == [], f"Missing files: {missing}"
