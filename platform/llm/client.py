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

import random
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
    anthropic.APIStatusError,  # 5xx including 529 Overloaded
)


# ---------------------------------------------------------------------------
# Prompt size thresholds
# ---------------------------------------------------------------------------

# Anthropic's documented hard limit per request is 32 MB (bytes, not tokens).
# A Python str of N chars is at most 4×N bytes in UTF-8; we compare against
# raw char count using the same 4-byte-per-char approximation used by
# retrieval._trim_descriptions.
_ANTHROPIC_LIMIT_BYTES: int = 32 * 1024 * 1024           # 32 MB
_ANTHROPIC_LIMIT_CHARS: int = _ANTHROPIC_LIMIT_BYTES // 4  # 8,388,608 chars

# Warn threshold: 200,000 chars ≈ 50,000 tokens.
# Normal Phase 4 prompts top out at ~18,000 chars (~4,500 tokens).
# Phase 1 batch calls reach ~20,700 chars (~5,175 tokens).
# 200,000 chars is 10× the Phase 4 maximum — fires only on runaway input.
_PROMPT_WARN_CHARS: int = 200_000


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

    def _check_prompt_size(self, prompt: str, schema_name: str) -> None:
        """Log prompt size and guard against oversized requests.

        Called once per complete() invocation, before the retry loop.
        Raises LLMError only when the prompt would certainly be rejected
        by the API. The warning threshold fires well below that limit to
        surface runaway prompts early in logs.

        Args:
            prompt:      The fully rendered prompt string.
            schema_name: output_schema.__name__ for log context.

        Raises:
            LLMError: prompt_chars >= _ANTHROPIC_LIMIT_CHARS.
        """
        prompt_chars = len(prompt)
        estimated_tokens = prompt_chars // 4
        log.debug(
            "llm_prompt_size",
            schema=schema_name,
            prompt_chars=prompt_chars,
            estimated_tokens=estimated_tokens,
        )
        if prompt_chars >= _ANTHROPIC_LIMIT_CHARS:
            raise LLMError(
                f"Prompt too large: {prompt_chars:,} chars"
                f" (~{estimated_tokens:,} tokens)."
                f" schema={schema_name!r}"
            )
        if prompt_chars >= _PROMPT_WARN_CHARS:
            log.warning(
                "llm_prompt_large",
                schema=schema_name,
                prompt_chars=prompt_chars,
                estimated_tokens=estimated_tokens,
                warn_threshold=_PROMPT_WARN_CHARS,
            )

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

        self._check_prompt_size(prompt, output_schema.__name__)

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
                # AuthenticationError (401) is never retryable — fail immediately
                if isinstance(exc, anthropic.AuthenticationError):
                    log.error("llm_non_retryable_error", model=model, error=str(exc))
                    raise LLMError(
                        f"Non-retryable LLM error (model={model!r}): {exc}",
                        cause=exc,
                    ) from exc
                last_exc = exc
                if attempt < self._max_retries:
                    if isinstance(exc, anthropic.RateLimitError):
                        # Honor retry-after header; fall back to 60 s × attempt
                        retry_after: str | None = None
                        if hasattr(exc, "response") and exc.response is not None:
                            retry_after = exc.response.headers.get("retry-after")
                        wait = float(retry_after) if retry_after else 60.0 * attempt
                        wait += random.uniform(0, 5)  # jitter across concurrent workers
                    else:
                        wait = 2 ** (attempt - 1)  # 1 s, 2 s, 4 s for other transient errors
                    log.warning(
                        "llm_retry",
                        model=model,
                        attempt=attempt,
                        wait_s=round(wait, 1),
                        error=str(exc),
                    )
                    time.sleep(wait)
                else:
                    log.warning(
                        "llm_retry",
                        model=model,
                        attempt=attempt,
                        error=str(exc),
                    )
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
