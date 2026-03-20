"""
PlatformModel — base Pydantic model inherited by every schema in the platform.

Config rules (enforced platform-wide):
  frozen=True              — all models are immutable after construction
  str_strip_whitespace=True — leading/trailing whitespace stripped on all str fields
  validate_default=True    — default values are validated at construction time
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlatformModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )
