# VS Code + Claude Code Setup Guide

## 1. VS Code extensions (install these first)

```
# Essential
ms-python.python
ms-python.mypy-type-checker
charliermarsh.ruff
ms-python.debugpy

# Claude Code
anthropic.claude-code

# Docker + DB
ms-azuretools.vscode-docker
cweijan.vscode-postgresql-client2

# Quality of life
GitHub.copilot          # optional, Claude Code is primary
eamodio.gitlens
tamasfe.even-better-toml
redhat.vscode-yaml
```

## 2. VS Code settings (.vscode/settings.json)

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["-x", "-v", "--tb=short"],
  "ruff.lint.run": "onSave",
  "mypy-type-checker.args": ["--strict"],
  "editor.formatOnSave": true,
  "editor.rulers": [100],
  "files.exclude": {
    "**/__pycache__": true,
    "**/.pytest_cache": true,
    "**/.mypy_cache": true
  },
  "terminal.integrated.env.linux": {
    "PYTHONPATH": "${workspaceFolder}"
  }
}
```

## 3. Claude Code configuration

### .claude/settings.json (project-level)

```json
{
  "contextFiles": [
    "CLAUDE.md",
    "docs/architecture.md",
    "platform/schemas/requirement.py",
    "platform/schemas/fitment.py"
  ],
  "instructions": "Always read CLAUDE.md first. Follow TDD: write test before implementation. Use Pydantic v2 at every boundary."
}
```

### How to use Claude Code effectively for this project

**Session 1 — Bootstrap:**
```
@claude Read CLAUDE.md and TDD_IMPLEMENTATION_GUIDE.md. 
Set up the monorepo scaffold, write pyproject.toml, 
create base schemas with tests. Run `make test` at the end.
```

**Session 2 — Platform layer:**
```
@claude Context: CLAUDE.md + platform/ folder.
Implement platform/llm/client.py with TDD.
Write tests first in tests/unit/test_llm_client.py.
Must support Claude Sonnet as primary, with retry + fallback.
```

**Session 3 — Phase 1 ingestion:**
```
@claude Context: CLAUDE.md + modules/dynafit/
Implement Phase 1 Step 1: Format Detector.
TDD cycle: tests/unit/test_format_detector.py first.
Use Docling for PDF/DOCX, openpyxl for Excel.
Follow the sub-step pattern from our architecture.
```

### Key prompting patterns for Claude Code

1. **Always reference CLAUDE.md** — it contains architecture context
2. **Name the exact file** you want created or modified
3. **Specify TDD** — "write the test first, then implement"
4. **State the Pydantic boundary** — "input is X, output is Y"
5. **Reference the phase/step** — "Phase 1 · Step 2 · Atomizer"

## 4. Git workflow

```bash
# Branch naming
feature/platform-schemas
feature/dynafit-phase1-ingestion
feature/dynafit-phase2-rag
feature/api-routes
feature/ui-dashboard

# Commit convention
feat(schemas): add RequirementAtom and ClassificationResult
test(dynafit): add golden fixtures for phase 4 classification
fix(parsers): handle merged cells in openpyxl extraction
docs(architecture): update phase 2 RAG data flow

# PR checklist
- [ ] Tests pass: `make test`
- [ ] Lint clean: `make lint`
- [ ] Contracts valid: `make validate-contracts`
- [ ] CLAUDE.md updated if architecture changed
```

## 5. Debug configurations (.vscode/launch.json)

```json
{
  "configurations": [
    {
      "name": "pytest: current file",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v", "-x"],
      "env": {"PYTHONPATH": "${workspaceFolder}"}
    },
    {
      "name": "FastAPI dev",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["api.main:app", "--reload", "--port", "8000"],
      "env": {"PYTHONPATH": "${workspaceFolder}"}
    },
    {
      "name": "Seed KB",
      "type": "debugpy",
      "request": "launch",
      "module": "infra.scripts.seed_knowledge_base",
      "args": ["--product", "d365_fo"],
      "env": {"PYTHONPATH": "${workspaceFolder}"}
    }
  ]
}
```
