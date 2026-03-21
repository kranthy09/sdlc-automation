"""Phase 4 prompt templates and G8 firewall loader.

Public API::

    from modules.dynafit.prompts import render_prompt, ALLOWED_TEMPLATES
"""

from modules.dynafit.prompts.loader import ALLOWED_TEMPLATES, render_prompt

__all__ = ["ALLOWED_TEMPLATES", "render_prompt"]
