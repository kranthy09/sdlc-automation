"""
Import boundary and manifest schema validator.

Enforces architectural import rules on every PR:
  - platform/ cannot import from agents/, modules/, or api/
  - agents/ cannot import from modules/ or api/
  - modules/X/ cannot import from modules/Y/ (no cross-module imports)
  - api/ routes may only import from modules/ entry points and platform/schemas/

Also validates manifest.yaml files:
  - input_schema and output_schema fields must resolve to real classes in platform/schemas/

Run via: make validate-contracts
Exit code 0 = all contracts valid. Exit code 1 = violations found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import boundary rules
# ---------------------------------------------------------------------------

# Each rule: (layer_prefix, forbidden_prefixes, description)
LAYER_RULES: list[tuple[str, list[str], str]] = [
    (
        "platform",
        ["agents", "modules", "api"],
        "platform/ cannot import from agents/, modules/, or api/",
    ),
    (
        "agents",
        ["modules", "api"],
        "agents/ cannot import from modules/ or api/",
    ),
]

# api/ may import from modules/ only via specific entry-point patterns
API_ALLOWED_MODULE_IMPORTS = {
    "graph",  # build_*_graph() entry points
    "schemas",  # schema types for typed responses
    "manifest",  # module registration metadata
}


def _extract_imports(tree: ast.Module) -> list[str]:
    """Return list of top-level module names imported in an AST."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
    return modules


def check_layer_imports(root: Path) -> list[str]:
    """Enforce LAYER_RULES across all Python files."""
    violations: list[str] = []
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root)
        parts = rel.parts
        if not parts or parts[0] in ("tests", "infra", "docs", "ui", "knowledge_bases", ".venv"):
            continue
        layer = parts[0]
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            violations.append(f"SYNTAX ERROR: {rel}\n  {exc}")
            continue

        imported = _extract_imports(tree)
        for importer, forbidden_list, desc in LAYER_RULES:
            if layer == importer:
                for mod in imported:
                    for forbidden in forbidden_list:
                        if mod == forbidden or mod.startswith(f"{forbidden}."):
                            violations.append(
                                f"VIOLATION [{desc}]\n  File:   {rel}\n  Import: {mod}"
                            )
    return violations


def check_cross_module_imports(root: Path) -> list[str]:
    """No module may import from a sibling module."""
    violations: list[str] = []
    modules_dir = root / "modules"
    if not modules_dir.exists():
        return violations

    module_names = [
        d.name for d in modules_dir.iterdir() if d.is_dir() and not d.name.startswith("_")
    ]

    for py_file in modules_dir.rglob("*.py"):
        rel = py_file.relative_to(root)
        # rel.parts[0] = "modules", rel.parts[1] = module_name
        if len(rel.parts) < 2:
            continue
        owning_module = rel.parts[1]
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        imported = _extract_imports(tree)
        for mod in imported:
            for other in module_names:
                if other != owning_module and (
                    mod == f"modules.{other}" or mod.startswith(f"modules.{other}.")
                ):
                    violations.append(
                        f"VIOLATION [modules cannot import from sibling modules]\n"
                        f"  File:   {rel}\n"
                        f"  Import: {mod}"
                    )
    return violations


def check_api_module_imports(root: Path) -> list[str]:
    """api/ may only import module entry points (graph, schemas, manifest)."""
    violations: list[str] = []
    api_dir = root / "api"
    if not api_dir.exists():
        return violations

    for py_file in api_dir.rglob("*.py"):
        rel = py_file.relative_to(root)
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        imported = _extract_imports(tree)
        for mod in imported:
            if mod.startswith("modules."):
                parts = mod.split(".")
                # modules.<module_name>.<file> — check the file part
                if len(parts) >= 3:
                    file_part = parts[2]
                    if file_part not in API_ALLOWED_MODULE_IMPORTS:
                        violations.append(
                            f"VIOLATION [api/ may only import module entry points (graph/schemas/manifest)]\n"
                            f"  File:   {rel}\n"
                            f"  Import: {mod}\n"
                            f"  Allowed sub-modules: {sorted(API_ALLOWED_MODULE_IMPORTS)}"
                        )
    return violations


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


def check_manifests(root: Path) -> list[str]:
    """
    Validate all manifest.yaml files.
    - input_schema and output_schema must reference real classes in platform/schemas/.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return ["SKIPPED: PyYAML not installed — cannot validate manifests"]

    violations: list[str] = []

    # Collect all class names defined in platform/schemas/
    schema_classes: set[str] = set()
    schemas_dir = root / "platform" / "schemas"
    if schemas_dir.exists():
        for py_file in schemas_dir.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    schema_classes.add(node.name)

    # Check every manifest.yaml
    for manifest_path in root.rglob("manifest.yaml"):
        rel = manifest_path.relative_to(root)
        # Skip infra/ and docs/
        if rel.parts[0] in ("infra", "docs", ".venv"):
            continue
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            violations.append(f"MANIFEST PARSE ERROR: {rel}\n  {exc}")
            continue

        if not isinstance(manifest, dict):
            violations.append(f"MANIFEST INVALID: {rel}\n  Expected a YAML mapping at root")
            continue

        for field in ("input_schema", "output_schema"):
            class_ref = manifest.get(field)
            if class_ref is None:
                violations.append(
                    f"MANIFEST MISSING FIELD: {rel}\n  Required field '{field}' is absent"
                )
            elif schema_classes and class_ref not in schema_classes:
                violations.append(
                    f"MANIFEST UNRESOLVED SCHEMA: {rel}\n"
                    f"  Field '{field}' = '{class_ref}' not found in platform/schemas/\n"
                    f"  Available: {sorted(schema_classes)}"
                )

    return violations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    root = Path(__file__).resolve().parent.parent.parent

    all_violations: list[str] = []
    all_violations.extend(check_layer_imports(root))
    all_violations.extend(check_cross_module_imports(root))
    all_violations.extend(check_api_module_imports(root))
    all_violations.extend(check_manifests(root))

    if all_violations:
        sep = "=" * 60
        print(f"\n{sep}")
        print("CONTRACT VIOLATIONS FOUND")
        print(sep)
        for v in all_violations:
            print(f"\n{v}")
        print(f"\n{len(all_violations)} violation(s). Fix before merging.\n")
        return 1

    print("All import contracts valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
