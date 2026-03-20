"""
Tests for the import boundary validator itself.

Verifies that validate_contracts.py correctly catches violations
and correctly passes clean code.
"""

from __future__ import annotations

# Import directly from the script (not as a package import)
import importlib.util
import textwrap
from pathlib import Path

import pytest

_VALIDATOR_PATH = (
    Path(__file__).resolve().parent.parent.parent / "infra" / "scripts" / "validate_contracts.py"
)
_spec = importlib.util.spec_from_file_location("validate_contracts", _VALIDATOR_PATH)
assert _spec is not None and _spec.loader is not None
_vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vc)  # type: ignore[attr-defined]


@pytest.mark.unit
class TestLayerImportRules:
    def _write_py(self, tmp_path: Path, rel: str, code: str) -> None:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(code))

    def test_platform_importing_agents_is_violation(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "platform/llm/client.py",
            """
            from agents.ingestion import something  # forbidden
            """,
        )
        violations = _vc.check_layer_imports(tmp_path)
        assert any("platform/ cannot import" in v for v in violations)

    def test_platform_importing_modules_is_violation(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "platform/storage/postgres.py",
            """
            import modules.dynafit.graph  # forbidden
            """,
        )
        violations = _vc.check_layer_imports(tmp_path)
        assert any("platform/ cannot import" in v for v in violations)

    def test_agents_importing_modules_is_violation(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "agents/rag/agent.py",
            """
            from modules.dynafit import nodes  # forbidden
            """,
        )
        violations = _vc.check_layer_imports(tmp_path)
        assert any("agents/ cannot import" in v for v in violations)

    def test_clean_platform_file_passes(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "platform/schemas/base.py",
            """
            from pydantic import BaseModel  # external dep, fine
            from platform.schemas.errors import ParseError  # same layer, fine
            """,
        )
        violations = _vc.check_layer_imports(tmp_path)
        assert violations == []

    def test_agents_importing_platform_passes(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "agents/rag/agent.py",
            """
            from platform.retrieval.vector_store import VectorStore  # allowed
            """,
        )
        violations = _vc.check_layer_imports(tmp_path)
        assert violations == []


@pytest.mark.unit
class TestCrossModuleImports:
    def _write_py(self, tmp_path: Path, rel: str, code: str) -> None:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(code))

    def test_sibling_module_import_is_violation(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "modules/dynafit/graph.py",
            """
            from modules.fdd.graph import build_fdd_graph  # sibling, forbidden
            """,
        )
        # Create sibling module dir so validator sees it
        (tmp_path / "modules" / "fdd").mkdir(parents=True, exist_ok=True)
        violations = _vc.check_cross_module_imports(tmp_path)
        assert any("sibling" in v for v in violations)

    def test_module_importing_platform_passes(self, tmp_path: Path) -> None:
        self._write_py(
            tmp_path,
            "modules/dynafit/nodes.py",
            """
            from platform.llm.client import classify  # allowed (up-layer import)
            """,
        )
        violations = _vc.check_cross_module_imports(tmp_path)
        assert violations == []
