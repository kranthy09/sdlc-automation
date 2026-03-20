"""
Tests for platform/schemas/base.py — PlatformModel base config.

TDD Layer 1: these tests define the contract before implementation exists.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field, ValidationError

from platform.schemas.base import PlatformModel

# ---------------------------------------------------------------------------
# Subclass helpers used across tests
# ---------------------------------------------------------------------------


class _Name(PlatformModel):
    value: str


class _Score(PlatformModel):
    score: Annotated[float, Field(ge=0.0, le=1.0)]


class _WithDefault(PlatformModel):
    # validate_default=True means this invalid default should raise on instantiation
    count: Annotated[int, Field(ge=0)] = -1


class _Multi(PlatformModel):
    name: str
    tag: str


# ---------------------------------------------------------------------------
# frozen=True: mutation must be refused
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFrozen:
    def test_assignment_raises(self) -> None:
        m = _Name(value="hello")
        with pytest.raises(ValidationError):
            m.value = "other"  # type: ignore[misc]

    def test_deletion_raises(self) -> None:
        m = _Name(value="hello")
        with pytest.raises((ValidationError, TypeError)):
            del m.value  # type: ignore[misc]

    def test_model_is_hashable(self) -> None:
        m = _Name(value="hello")
        assert isinstance(hash(m), int)

    def test_equal_models_have_same_hash(self) -> None:
        a = _Name(value="x")
        b = _Name(value="x")
        assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# str_strip_whitespace=True: leading/trailing whitespace stripped
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStrStripWhitespace:
    def test_leading_whitespace_stripped(self) -> None:
        m = _Name(value="   hello")
        assert m.value == "hello"

    def test_trailing_whitespace_stripped(self) -> None:
        m = _Name(value="hello   ")
        assert m.value == "hello"

    def test_both_sides_stripped(self) -> None:
        m = _Name(value="  hello world  ")
        assert m.value == "hello world"

    def test_inner_whitespace_preserved(self) -> None:
        m = _Name(value="hello   world")
        assert m.value == "hello   world"

    def test_multiple_string_fields_all_stripped(self) -> None:
        m = _Multi(name="  alice  ", tag="  admin  ")
        assert m.name == "alice"
        assert m.tag == "admin"


# ---------------------------------------------------------------------------
# validate_default=True: defaults are validated at instantiation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateDefault:
    def test_invalid_default_raises_on_instantiation(self) -> None:
        with pytest.raises(ValidationError):
            _WithDefault()

    def test_valid_explicit_value_passes(self) -> None:
        m = _WithDefault(count=5)
        assert m.count == 5


# ---------------------------------------------------------------------------
# General model behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlatformModelGeneral:
    def test_valid_model_creates(self) -> None:
        m = _Name(value="test")
        assert m.value == "test"

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            _Score(score="not-a-float")  # type: ignore[arg-type]

    def test_field_constraint_violation_raises(self) -> None:
        with pytest.raises(ValidationError):
            _Score(score=1.5)  # gt 1.0

    def test_model_dump_round_trips(self) -> None:
        m = _Name(value="ping")
        assert _Name.model_validate(m.model_dump()) == m

    def test_subclass_is_platform_model(self) -> None:
        assert issubclass(_Name, PlatformModel)
