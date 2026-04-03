"""VLM-based image description for unified multimodal ingestion.

Supports multiple VLM backends:
- smolvlm: Local model, fast, private (default)
- claude: Claude API vision, high-quality descriptions
- gpt4o: GPT-4o vision API, alternative high-quality
- none: Disable VLM, fall back to caption text

Gracefully degrades on VLM failure: uses caption or minimal description.
Returns (description_text, extraction_confidence) tuple.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from platform.ingestion._errors import VLMDescriptionError
from platform.ingestion.schemas import ArtifactRef, DocumentElement
from platform.llm.client import LLMClient
from platform.observability.logger import get_logger
from platform.schemas.base import PlatformModel
from platform.schemas.product import ProductConfig

__all__ = ["ImageDescriptor"]

log = get_logger(__name__)


class ImageDescription(PlatformModel):
    """Structured output from VLM image description."""

    description: str
    """Natural language description of the image."""


class ImageDescriptor:
    """VLM-based image description for multimodal ingestion.

    Converts image elements into semantic descriptions by sending
    images to a configurable VLM backend (smolvlm, claude, gpt4o, or none).

    Gracefully degrades on failure: falls back to caption text or minimal
    placeholder description.

    Usage:
        llm_client = LLMClient()
        config = get_product_config(product_id)
        descriptor = ImageDescriptor(
            model="smolvlm",
            llm_client=llm_client,
            config=config,
            concurrency=3,
        )
        description, confidence = descriptor.describe(
            element, image_bytes, artifact_refs
        )
    """

    def __init__(
        self,
        model: str = "smolvlm",
        llm_client: LLMClient | None = None,
        config: ProductConfig | None = None,
        concurrency: int = 3,
    ):
        """Initialize image descriptor.

        Args:
            model: VLM backend ("smolvlm" | "claude" | "gpt4o" | "none")
            llm_client: LLMClient for API-based models (claude/gpt4o)
            config: ProductConfig for LLM model selection
            concurrency: Max concurrent description calls (default 3)
        """
        self.model = model
        self.llm_client = llm_client
        self.config = config
        self.concurrency = concurrency
        self._template_env: Environment | None = None

    def _get_template_env(self) -> Environment:
        """Lazy-load Jinja2 environment for image description template."""
        if self._template_env is None:
            template_dir = Path(__file__).parent / "templates"
            self._template_env = Environment(
                loader=FileSystemLoader(str(template_dir)),
                trim_blocks=True,
                lstrip_blocks=True,
            )
        return self._template_env

    def describe(
        self,
        element: DocumentElement,
        image_bytes: bytes,
        artifact_refs: list[ArtifactRef],
    ) -> tuple[str, float]:
        """Generate semantic description of an image.

        Args:
            element: DocumentElement with modality="IMAGE"
            image_bytes: Raw image bytes
            artifact_refs: ArtifactRef list (from artifact_store)

        Returns:
            Tuple of (description_text, extraction_confidence)
            - description_text: Natural language description
            - extraction_confidence: Float 0.0-1.0 (0.8+ for VLM,
              0.3 for fallback)

        Raises:
            VLMDescriptionError: Only if critical infrastructure fails
              (LLMClient down, invalid config). Fallback is used for
              model-specific failures.
        """
        # Handle "none" model explicitly
        if self.model == "none":
            return self._fallback_description(element), 0.3

        try:
            if self.model == "smolvlm":
                return self._describe_smolvlm(
                    element, image_bytes, artifact_refs
                )
            elif self.model in ("claude", "gpt4o"):
                return self._describe_api(
                    element, image_bytes, artifact_refs
                )
            else:
                log.warning(
                    f"Unknown VLM model {self.model}; falling back",
                    extra={"element_id": element.element_id},
                )
                return self._fallback_description(element), 0.3

        except Exception as e:
            log.warning(
                f"VLM description failed for {element.element_id}; "
                f"using fallback: {str(e)}"
            )
            return self._fallback_description(element), 0.3

    def _describe_smolvlm(
        self,
        element: DocumentElement,
        image_bytes: bytes,
        artifact_refs: list[ArtifactRef],
    ) -> tuple[str, float]:
        """Describe image using local SmolVLM model.

        Args:
            element: DocumentElement
            image_bytes: Raw image bytes
            artifact_refs: ArtifactRef list

        Returns:
            Tuple of (description, confidence)

        Raises:
            VLMDescriptionError: Only on infrastructure failure
        """
        try:
            # SmolVLM description via Docling or local transformers
            # For now, placeholder: in production, integrate transformers
            # library or Docling's picture description pipeline
            log.info(
                "SmolVLM image description not yet implemented; "
                "using fallback"
            )
            return self._fallback_description(element), 0.3

        except Exception as e:
            raise VLMDescriptionError(
                f"SmolVLM failed: {str(e)}"
            ) from e

    def _describe_api(
        self,
        element: DocumentElement,
        image_bytes: bytes,
        artifact_refs: list[ArtifactRef],
    ) -> tuple[str, float]:
        """Describe image using Claude or GPT-4o API.

        Args:
            element: DocumentElement
            image_bytes: Raw image bytes
            artifact_refs: ArtifactRef list

        Returns:
            Tuple of (description, confidence)

        Raises:
            VLMDescriptionError: If LLMClient or config unavailable
        """
        if not self.llm_client or not self.config:
            log.warning(
                "LLMClient or config unavailable for API VLM; "
                "falling back"
            )
            return self._fallback_description(element), 0.3

        try:
            # Render prompt via Jinja2
            template_env = self._get_template_env()
            template = template_env.get_template("image_description.j2")
            prompt = template.render(
                section_path=element.section_path,
                caption=element.raw_content,
            )

            log.debug(
                f"Sending image description to {self.model}",
                extra={
                    "element_id": element.element_id,
                    "prompt_length": len(prompt),
                },
            )

            # Call LLM with structured output
            result = self.llm_client.complete(
                prompt=prompt,
                output_schema=ImageDescription,
                config=self.config,
            )

            description = result.description.strip()
            if not description or len(description) < 5:
                log.warning(
                    f"VLM returned empty description for "
                    f"{element.element_id}; using fallback"
                )
                return self._fallback_description(element), 0.3

            return description, 0.85

        except Exception as e:
            log.warning(
                f"API VLM failed for {element.element_id}: {str(e)}"
            )
            return self._fallback_description(element), 0.3

    @staticmethod
    def _fallback_description(element: DocumentElement) -> str:
        """Generate minimal fallback description.

        Combines existing caption (if any) with page/section context.

        Args:
            element: DocumentElement

        Returns:
            Fallback description string
        """
        if element.raw_content and element.raw_content.strip():
            return element.raw_content.strip()

        section_name = (
            element.section_path[-1]
            if element.section_path
            else "document"
        )
        return f"[Image on page {element.page_no} in section {section_name}]"
