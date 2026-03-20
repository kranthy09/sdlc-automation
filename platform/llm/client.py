"""
LLM client — the single gateway for all Anthropic API calls.

Design rules (enforced here, nowhere else):
  - Retry logic lives ONLY here; nodes must never duplicate it.
  - Every call is wrapped in record_call("llm", "invoke") for Prometheus.
  - Token cost is emitted as a Prometheus counter after every successful call.
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
from prometheus_client import REGISTRY as _DEFAULT_REGISTRY
from prometheus_client import CollectorRegistry, Counter
from pydantic import BaseModel

from platform.config.settings import get_settings
from platform.observability.logger import get_logger
from platform.observability.metrics import record_call
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
# Cost table — USD per million tokens
# ---------------------------------------------------------------------------

_INPUT_COST_PER_M: dict[str, float] = {
    "claude-sonnet-4-6": 3.0,
    "claude-opus-4-6": 15.0,
    "claude-haiku-4-5": 0.25,
}
_OUTPUT_COST_PER_M: dict[str, float] = {
    "claude-sonnet-4-6": 15.0,
    "claude-opus-4-6": 75.0,
    "claude-haiku-4-5": 1.25,
}
_DEFAULT_INPUT_COST = 3.0
_DEFAULT_OUTPUT_COST = 15.0


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
    """Anthropic API client with retry, structured output, and observability.

    Args:
        max_retries: Number of retry attempts on transient errors (default 3).
        registry:    Prometheus CollectorRegistry for the cost counter.
                     Inject a fresh CollectorRegistry() in tests for isolation.
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        registry: CollectorRegistry | None = None,
    ) -> None:
        _registry = registry if registry is not None else _DEFAULT_REGISTRY
        self._max_retries = max_retries
        self._cost_counter = Counter(
            "platform_llm_token_cost_usd_total",
            "Estimated LLM token cost in USD, labelled by model and token direction",
            ["model", "direction"],
            registry=_registry,
        )
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
                with record_call("llm", "invoke"):
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
                    f"Non-retryable LLM error (model={model!r}): {exc}", cause=exc
                ) from exc

            # Success path — extract the tool_use block
            tool_block = next(
                (b for b in response.content if b.type == "tool_use"),
                None,
            )
            if tool_block is None:
                raise LLMError(f"LLM response contained no tool_use block (model={model!r})")

            result: T = output_schema.model_validate(tool_block.input)

            # Emit cost metrics
            in_tokens: int = response.usage.input_tokens
            out_tokens: int = response.usage.output_tokens
            in_cost = in_tokens * _INPUT_COST_PER_M.get(model, _DEFAULT_INPUT_COST) / 1_000_000
            out_cost = out_tokens * _OUTPUT_COST_PER_M.get(model, _DEFAULT_OUTPUT_COST) / 1_000_000
            self._cost_counter.labels(model=model, direction="input").inc(in_cost)
            self._cost_counter.labels(model=model, direction="output").inc(out_cost)

            log.info(
                "llm_success",
                model=model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost_usd=round(in_cost + out_cost, 6),
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
