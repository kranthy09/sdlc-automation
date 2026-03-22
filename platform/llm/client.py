"""
LLM client — the single gateway for all Anthropic API calls.

Design rules (enforced here, nowhere else):
  - Retry logic lives ONLY here; nodes must never duplicate it.
  - All output is parsed into a caller-provided Pydantic schema via tool use.
  - Retryable errors: RateLimitError, InternalServerError, APIConnectionError,
    APITimeoutError.  All others raise LLMError immediately (no retry).

Usage:
    from platform.llm.client import complete
    from platform.schemas.product import ProductConfig

    result: MySchema = complete(
        prompt="Classify this requirement...",
        output_schema=MySchema,
        config=product_config,
    )
"""

from __future__ import annotations

import time
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from platform.config.settings import get_settings
from platform.observability.logger import get_logger
from platform.schemas.product import ProductConfig

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Retryable error types
# ---------------------------------------------------------------------------

_RETRYABLE: tuple[type[Exception], ...] = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Raised when the LLM call fails — retries exhausted or non-retryable error."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Anthropic API client with retry and structured output.

    Args:
        max_retries: Number of retry attempts on transient errors (default 3).
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
    ) -> None:
        self._max_retries = max_retries
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())

    def complete(
        self,
        prompt: str,
        output_schema: type[T],
        config: ProductConfig,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> T:
        """Call the Anthropic LLM and parse the response into *output_schema*.

        Uses Anthropic tool use to enforce structured JSON output.  Retries up
        to *max_retries* times on transient errors with exponential back-off
        (1 s, 2 s, 4 s …).  Raises *LLMError* when all retries are exhausted
        or a non-retryable error is encountered.

        Args:
            prompt:        Rendered prompt string (use Jinja2 templates upstream).
            output_schema: Pydantic model class to parse the LLM response into.
            config:        ProductConfig — provides the LLM model name.
            temperature:   Sampling temperature (default 0.0 for determinism).
            max_tokens:    Maximum output tokens (default 2048).

        Returns:
            An instance of *output_schema* populated from the LLM tool call.

        Raises:
            LLMError: All retries exhausted or a non-retryable error occurred.
        """
        model = config.llm_model
        tool: dict[str, Any] = {
            "name": "output",
            "description": f"Return the result as a {output_schema.__name__} object.",
            "input_schema": output_schema.model_json_schema(),
        }

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            log.debug(
                "llm_attempt",
                model=model,
                attempt=attempt,
                max_retries=self._max_retries,
            )
            try:
                response = self._client.messages.create(  # type: ignore[call-overload]
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "output"},
                    messages=[{"role": "user", "content": prompt}],
                )
            except _RETRYABLE as exc:
                last_exc = exc
                log.warning(
                    "llm_retry",
                    model=model,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt - 1))  # 1 s, 2 s, 4 s …
                continue
            except Exception as exc:
                log.error("llm_non_retryable_error", model=model, error=str(exc))
                raise LLMError(
                    f"Non-retryable LLM error (model={model!r}): {exc}",
                    cause=exc,
                ) from exc

            # Success path — extract the tool_use block
            tool_block = next(
                (b for b in response.content if b.type == "tool_use"),
                None,
            )
            if tool_block is None:
                raise LLMError(f"LLM response contained no tool_use block (model={model!r})")

            result: T = output_schema.model_validate(tool_block.input)

            in_tokens: int = response.usage.input_tokens
            out_tokens: int = response.usage.output_tokens
            log.info(
                "llm_success",
                model=model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
            )

            return result

        raise LLMError(
            f"LLM call failed after {self._max_retries} retries (model={model!r})",
            cause=last_exc,
        )


# ---------------------------------------------------------------------------
# Module-level convenience (lazy default client)
# ---------------------------------------------------------------------------

_default_client: LLMClient | None = None


def _get_default_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def complete[T: BaseModel](
    prompt: str,
    output_schema: type[T],
    config: ProductConfig,
    *,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> T:
    """Module-level convenience — delegates to the default LLMClient."""
    return _get_default_client().complete(
        prompt,
        output_schema,
        config,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# Alias used in docs/rules.md
classify = complete
