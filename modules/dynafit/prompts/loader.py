"""G8 Prompt Firewall — Jinja2 template loader for Phase 4 classification prompts.

Enforces three structural rules per docs/specs/guardrails.md § G8:

  1. autoescape=True     All {{ variable }} outputs are HTML-escaped via MarkupSafe,
                         preventing prompt injection through XML/HTML tags embedded
                         in user-supplied requirement text.

  2. StrictUndefined     Any missing template variable raises jinja2.UndefinedError
                         at render time (not silently empty), catching wiring bugs
                         before they reach the LLM.

  3. Allowed-template    Only templates listed in ALLOWED_TEMPLATES may be rendered.
     whitelist           Unknown names raise ValueError immediately, before any
                         filesystem access.

Usage::

    from modules.dynafit.prompts.loader import render_prompt

    prompt = render_prompt(
        "classification_v1.j2",
        atom=validated_atom,
        capabilities=ranked_caps,
        prior_fitments=prior_list,
    )
"""

from __future__ import annotations

from pathlib import Path

import jinja2

# ---------------------------------------------------------------------------
# Allowed template whitelist (G8 rule 3)
# ---------------------------------------------------------------------------

ALLOWED_TEMPLATES: frozenset[str] = frozenset(
    {
        "classification_v1.j2",
        "rationale_v1.j2",
    }
)

# ---------------------------------------------------------------------------
# Jinja2 environment (G8 rules 1 + 2)
# ---------------------------------------------------------------------------

_PROMPTS_DIR: Path = Path(__file__).parent

_env: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_PROMPTS_DIR)),
    autoescape=True,  # G8 rule 1: all {{ }} outputs are HTML-escaped
    undefined=jinja2.StrictUndefined,  # G8 rule 2: missing vars → UndefinedError
    keep_trailing_newline=True,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_prompt(template_name: str, **context: object) -> str:
    """Render a Phase 4 prompt template through the G8 firewall.

    Args:
        template_name: Template filename.  Must be in ``ALLOWED_TEMPLATES``.
        **context:     Variables passed to the template.  Every required
                       variable must be supplied — missing ones raise
                       ``jinja2.UndefinedError`` (StrictUndefined).

    Returns:
        Rendered prompt string.  All ``{{ variable }}`` outputs are
        HTML-escaped; static template XML tags are preserved as-is.

    Raises:
        ValueError:             ``template_name`` is not in ``ALLOWED_TEMPLATES``.
        jinja2.UndefinedError:  A required template variable is missing.
        jinja2.TemplateNotFound: Template file is missing from the prompts dir.
    """
    if template_name not in ALLOWED_TEMPLATES:
        raise ValueError(
            f"Template {template_name!r} is not in ALLOWED_TEMPLATES. "
            f"Allowed: {sorted(ALLOWED_TEMPLATES)}"
        )
    template = _env.get_template(template_name)
    return template.render(**context)
