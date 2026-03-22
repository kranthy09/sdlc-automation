"""
Tests for platform/schemas/base.py — PlatformModel base config.

Covers the three PlatformModel invariants: frozen, str_strip_whitespace, validate_default.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field, ValidationError

from platform.schemas.base import PlatformModel


class _Name(PlatformModel):
    value: str


class _Score(PlatformModel):
    score: Annotated[float, Field(ge=0.0, le=1.0)]


class _WithDefault(PlatformModel):
    count: Annotated[int, Field(ge=0)] = -1


@pytest.mark.unit
def test_frozen_rejects_mutation() -> None:
    """PlatformModel instances are immutable."""
    m = _Name(value="hello")
    with pytest.raises(ValidationError):
        m.value = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_str_strip_whitespace() -> None:
    """Leading/trailing whitespace is stripped from string fields."""
    m = _Name(value="  hello world  ")
    assert m.value == "hello world"


@pytest.mark.unit
def test_validate_default_rejects_invalid() -> None:
    """Invalid defaults are caught at instantiation time."""
    with pytest.raises(ValidationError):
        _WithDefault()


@pytest.mark.unit
def test_field_constraint_violation_raises() -> None:
    """Field constraints are enforced."""
    with pytest.raises(ValidationError):
        _Score(score=1.5)
