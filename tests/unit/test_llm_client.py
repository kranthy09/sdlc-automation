"""
TDD — platform/llm/client.py

Tests cover the three behaviours called out in docs/specs/tdd.md:
  - Structured output: LLM tool-use response is parsed into the caller's Pydantic schema.
  - Retry behaviour:   Transient errors are retried; max-retries exhaustion raises LLMError.
All tests use:
  - monkeypatch to swap get_settings() and anthropic.Anthropic so no real HTTP calls are made.
  - time.sleep patched to a no-op so retry tests run instantly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest
from pydantic import BaseModel

from platform.schemas.product import ProductConfig

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class _ClassifyOutput(BaseModel):
    """Minimal Pydantic schema used as the structured output target."""

    label: str
    confidence: float


_PRODUCT = ProductConfig(
    product_id="test",
    display_name="Test Product",
    llm_model="claude-sonnet-4-6",
    embedding_model="BAAI/bge-small-en-v1.5",
    capability_kb_namespace="test_caps",
    doc_corpus_namespace="test_docs",
    historical_fitments_table="test_fitments",
    fit_confidence_threshold=0.85,
    review_confidence_threshold=0.60,
    auto_approve_with_history=True,
    country_rules_path="knowledge_bases/test/country_rules/",
    fdd_template_path="knowledge_bases/test/fdd_templates/template.j2",
    code_language="xpp",
)


def _make_tool_response(label: str, confidence: float) -> MagicMock:
    """Return a mock anthropic Message containing a single tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {"label": label, "confidence": confidence}

    response = MagicMock()
    response.content = [tool_block]
    response.usage.input_tokens = 100
    response.usage.output_tokens = 40
    return response


def _make_client(
    mock_anthropic_instance: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Instantiate LLMClient with mocked Anthropic."""
    import platform.llm.client as module

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
    mock_settings.langfuse_public_key = ""  # disable Langfuse in standard unit tests

    monkeypatch.setattr(module, "get_settings", lambda: mock_settings)

    # Replace anthropic.Anthropic constructor so self._client = mock_anthropic_instance
    with patch.object(module.anthropic, "Anthropic", return_value=mock_anthropic_instance):
        from platform.llm.client import LLMClient

        return LLMClient()


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_complete_returns_parsed_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful call parses the tool_use block into the target Pydantic schema."""
    mock_api = MagicMock()
    mock_api.messages.create.return_value = _make_tool_response("FIT", 0.92)

    client = _make_client(mock_api, monkeypatch)

    from platform.llm.client import LLMClient

    assert isinstance(client, LLMClient)
    result = client.complete("classify this", _ClassifyOutput, _PRODUCT)  # type: ignore[attr-defined]

    assert isinstance(result, _ClassifyOutput)
    assert result.label == "FIT"
    assert result.confidence == pytest.approx(0.92)
    mock_api.messages.create.assert_called_once()


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_retries_on_transient_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """RateLimitError on first two attempts; third attempt succeeds."""
    mock_api = MagicMock()
    mock_api.messages.create.side_effect = [
        anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body={},
        ),
        anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body={},
        ),
        _make_tool_response("GAP", 0.75),
    ]

    with patch("platform.llm.client.time.sleep"):  # skip back-off delays
        client = _make_client(mock_api, monkeypatch)
        result = client.complete("classify this", _ClassifyOutput, _PRODUCT)  # type: ignore[attr-defined]

    assert result.label == "GAP"
    assert mock_api.messages.create.call_count == 3


@pytest.mark.unit
def test_raises_llm_error_after_max_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMError is raised when all three retries fail with a transient error."""
    mock_api = MagicMock()
    mock_api.messages.create.side_effect = anthropic.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={},
    )

    with patch("platform.llm.client.time.sleep"):
        client = _make_client(mock_api, monkeypatch)
        from platform.llm.client import LLMError

        with pytest.raises(LLMError):
            client.complete("classify this", _ClassifyOutput, _PRODUCT)  # type: ignore[attr-defined]

    assert mock_api.messages.create.call_count == 3


@pytest.mark.unit
def test_non_retryable_error_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-retryable error (e.g. AuthenticationError) raises LLMError after 1 attempt."""
    mock_api = MagicMock()
    mock_api.messages.create.side_effect = anthropic.AuthenticationError(
        message="invalid key",
        response=MagicMock(status_code=401, headers={}),
        body={},
    )

    client = _make_client(mock_api, monkeypatch)

    from platform.llm.client import LLMError

    with pytest.raises(LLMError):
        client.complete("classify this", _ClassifyOutput, _PRODUCT)  # type: ignore[attr-defined]

    # Must not retry on auth errors
    assert mock_api.messages.create.call_count == 1
