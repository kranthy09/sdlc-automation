"""LLM-based table row narration for unified multimodal ingestion.

Converts table elements into natural language narrations by:
1. Splitting large tables (>15 rows) into batches
2. Sending each batch to the LLM with structured output enforcement
3. Stitching row narrations back into unified text

Parallelizes across multiple tables using asyncio.Semaphore for concurrency control.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from platform.ingestion._errors import LLMNarrationError
from platform.ingestion.schemas import DocumentElement
from platform.llm.client import LLMClient
from platform.observability.logger import get_logger
from platform.schemas.base import PlatformModel
from platform.schemas.product import ProductConfig

__all__ = ["TableNarrator", "NarratedRow", "NarratedTable"]

log = get_logger(__name__)


class NarratedRow(PlatformModel):
    """Single row narration from LLM output."""

    row_index: int
    """0-indexed row position in the table."""
    narration: str
    """Natural language description of the row."""


class NarratedTable(PlatformModel):
    """Structured LLM output for table narration."""

    rows: list[NarratedRow]
    """List of narrated rows, in order."""


class TableNarrator:
    """LLM-based table narration for multimodal ingestion.

    Converts markdown-serialized tables into natural language narrations
    by sending batches of rows to Claude with a structured prompt.

    For tables ≤15 rows: single LLM call.
    For tables >15 rows: batch into groups of 15, parallelize with asyncio.

    Usage:
        llm_client = LLMClient()
        config = get_product_config(product_id)
        narrator = TableNarrator(llm_client, config, concurrency=5)
        narrated_text = narrator.narrate(element, batch_id="batch-123")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        config: ProductConfig,
        concurrency: int = 5,
    ):
        """Initialize table narrator.

        Args:
            llm_client: LLMClient instance for API calls
            config: ProductConfig for LLM model selection
            concurrency: Max concurrent table narration calls (default 5)
        """
        self.llm_client = llm_client
        self.config = config
        self.concurrency = concurrency
        self._semaphore: asyncio.Semaphore | None = None
        self._template_env: Environment | None = None

    def _get_template_env(self) -> Environment:
        """Lazy-load Jinja2 environment for table narration template."""
        if self._template_env is None:
            template_dir = Path(__file__).parent / "templates"
            self._template_env = Environment(
                loader=FileSystemLoader(str(template_dir)),
                trim_blocks=True,
                lstrip_blocks=True,
            )
        return self._template_env

    def narrate(self, element: DocumentElement, batch_id: str) -> str:
        """Narrate a table element using LLM with row-level granularity.

        Args:
            element: DocumentElement with modality="TABLE", raw_content=markdown
            batch_id: Batch identifier for logging

        Returns:
            Narrated text (one paragraph per row, joined with newlines)

        Raises:
            LLMNarrationError: If LLM call fails or table parsing fails
        """
        try:
            # Parse table from markdown
            lines = element.raw_content.strip().split("\n")
            if not lines or len(lines) < 2:
                log.warning(
                    f"Table element {element.element_id} is empty or malformed; "
                    "returning empty narration"
                )
                return ""

            # Count rows (skip header and separator lines)
            # Markdown tables have format:
            # | col1 | col2 |
            # |------|------|
            # | val1 | val2 |
            row_count = sum(1 for line in lines[2:] if line.strip().startswith("|"))

            log.debug(
                f"Narrating table with {row_count} rows",
                extra={
                    "batch_id": batch_id,
                    "element_id": element.element_id,
                    "section_path": ".".join(element.section_path),
                },
            )

            # For small tables, single LLM call
            if row_count <= 15:
                return self._narrate_single_batch(
                    element.raw_content,
                    element.section_path,
                    batch_id=batch_id,
                    element_id=element.element_id,
                )

            # For large tables, batch and parallelize
            return self._narrate_batched(
                element.raw_content,
                element.section_path,
                batch_id=batch_id,
                element_id=element.element_id,
            )

        except LLMNarrationError:
            raise
        except Exception as e:
            raise LLMNarrationError(
                f"Failed to narrate table {element.element_id}: {str(e)}"
            ) from e

    def _narrate_single_batch(
        self,
        table_markdown: str,
        section_path: list[str],
        batch_id: str,
        element_id: str,
    ) -> str:
        """Narrate table with single LLM call (≤15 rows).

        Args:
            table_markdown: Full table in markdown format
            section_path: Hierarchical section headings
            batch_id: Batch identifier for logging
            element_id: Element identifier for logging

        Returns:
            Narrated text (one paragraph per row)

        Raises:
            LLMNarrationError: If LLM call fails
        """
        try:
            # Render prompt via Jinja2
            template_env = self._get_template_env()
            template = template_env.get_template("table_narration.j2")
            prompt = template.render(
                table_markdown=table_markdown,
                section_path=section_path,
            )

            log.debug(
                "Sending table narration to LLM",
                extra={
                    "batch_id": batch_id,
                    "element_id": element_id,
                    "prompt_length": len(prompt),
                },
            )

            # Call LLM with structured output
            result = self.llm_client.complete(
                prompt=prompt,
                output_schema=NarratedTable,
                config=self.config,
            )

            # Stitch narrations
            narrations = [row.narration for row in result.rows]
            return "\n".join(narrations)

        except Exception as e:
            raise LLMNarrationError(
                f"LLM narration failed for element {element_id}: "
                f"{str(e)}"
            ) from e

    def _narrate_batched(
        self,
        table_markdown: str,
        section_path: list[str],
        batch_id: str,
        element_id: str,
    ) -> str:
        """Narrate large table in parallel batches (>15 rows).

        Splits table into 15-row groups, calls LLM for each group,
        stitches results back in order.

        Args:
            table_markdown: Full table in markdown format
            section_path: Hierarchical section headings
            batch_id: Batch identifier for logging
            element_id: Element identifier for logging

        Returns:
            Narrated text (one paragraph per row, in original order)

        Raises:
            LLMNarrationError: If any LLM call fails
        """
        try:
            # Split table into batches of 15 rows
            # Format: keep headers + separator, then 15-row chunks
            lines = table_markdown.strip().split("\n")
            if len(lines) < 3:
                return ""

            header_lines = lines[:2]  # Header + separator
            data_lines = [line for line in lines[2:] if line.strip().startswith("|")]

            # Batch data lines
            batches = []
            for i in range(0, len(data_lines), 15):
                batch_rows = data_lines[i : i + 15]
                batch_markdown = "\n".join(header_lines + batch_rows)
                batches.append((i // 15, batch_markdown))

            log.debug(
                f"Batching large table into {len(batches)} calls",
                extra={
                    "batch_id": batch_id,
                    "element_id": element_id,
                    "rows": len(data_lines),
                },
            )

            # Parallelize batch narration
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                narrations = loop.run_until_complete(
                    self._narrate_batches_async(
                        batches, section_path, batch_id, element_id
                    )
                )
                return "\n".join(narrations)
            finally:
                loop.close()

        except LLMNarrationError:
            raise
        except Exception as e:
            raise LLMNarrationError(
                f"Batch narration failed for element {element_id}: {str(e)}"
            ) from e

    async def _narrate_batches_async(
        self,
        batches: list[tuple[int, str]],
        section_path: list[str],
        batch_id: str,
        element_id: str,
    ) -> list[str]:
        """Async worker for parallel table batch narration.

        Args:
            batches: List of (batch_index, batch_markdown) tuples
            section_path: Hierarchical section headings
            batch_id: Batch identifier for logging
            element_id: Element identifier for logging

        Returns:
            List of narration strings, in batch order
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)

        async def narrate_batch(batch_idx: int, batch_markdown: str) -> str:
            async with self._semaphore:
                try:
                    template_env = self._get_template_env()
                    template = template_env.get_template(
                        "table_narration.j2"
                    )
                    prompt = template.render(
                        table_markdown=batch_markdown,
                        section_path=section_path,
                    )

                    result = self.llm_client.complete(
                        prompt=prompt,
                        output_schema=NarratedTable,
                        config=self.config,
                    )

                    narrations = [row.narration for row in result.rows]
                    return "\n".join(narrations)

                except Exception as e:
                    raise LLMNarrationError(
                        f"Batch {batch_idx} narration failed: {str(e)}"
                    ) from e

        tasks = [
            narrate_batch(idx, markdown) for idx, markdown in batches
        ]
        return await asyncio.gather(*tasks)
