"""Orchestrates multimodal narration and description into unified elements.

Combines the outputs of TableNarrator and ImageDescriptor into a single
stream of UnifiedElement objects where all modalities are represented as
natural language text.

Preserves reading order, section hierarchy, and artifact references.
"""

from __future__ import annotations

from platform.ingestion.description import ImageDescriptor
from platform.ingestion.narration import TableNarrator
from platform.ingestion.schemas import ArtifactRef, DocumentElement, UnifiedElement
from platform.observability.logger import get_logger

__all__ = ["Unifier"]

log = get_logger(__name__)


class Unifier:
    """Orchestrates narration + description to produce unified elements.

    Accepts raw DocumentElements (from element_extractor) with artifact
    references (from artifact_store), narrates tables, describes images,
    and emits UnifiedElements where all content is text.

    Usage:
        narrator = TableNarrator(llm_client, config, concurrency=5)
        descriptor = ImageDescriptor(model="smolvlm", ...)
        unifier = Unifier(narrator, descriptor)

        elements = extractor.extract(docling_doc, source_doc)
        artifacts = store.store_all(elements, extractor)

        unified = unifier.unify(elements, artifacts)
    """

    def __init__(
        self,
        narrator: TableNarrator,
        descriptor: ImageDescriptor,
    ):
        """Initialize unifier.

        Args:
            narrator: TableNarrator instance for table narration
            descriptor: ImageDescriptor instance for image description
        """
        self.narrator = narrator
        self.descriptor = descriptor

    def unify(
        self,
        elements: list[DocumentElement],
        artifact_map: dict[str, list[ArtifactRef]],
    ) -> list[UnifiedElement]:
        """Unify document elements by converting modalities to text.

        Processes elements in reading order:
        - TEXT elements: pass through unchanged
        - TABLE elements: replace raw_content with narrated text
        - IMAGE elements: replace raw_content with VLM description

        Args:
            elements: List of DocumentElements from element_extractor
            artifact_map: Dict mapping element_id to ArtifactRef list

        Returns:
            List of UnifiedElement objects in reading order, with all
            content unified to text format
        """
        unified = []
        batch_id = "unify"  # Could be passed in from caller context

        log.debug(
            "Starting multimodal unification",
            extra={
                "input_elements": len(elements),
                "artifact_count": sum(
                    len(refs) for refs in artifact_map.values()
                ),
            },
        )

        for element in elements:
            try:
                if element.modality == "TEXT":
                    # TEXT elements pass through unchanged
                    unified_elem = UnifiedElement(
                        element_id=element.element_id,
                        text=element.raw_content,
                        modality="TEXT",
                        section_path=element.section_path,
                        page_no=element.page_no,
                        position_index=element.position_index,
                        artifact_refs=[],
                        source_doc=element.source_doc,
                        extraction_confidence=1.0,
                    )
                    unified.append(unified_elem)

                elif element.modality == "TABLE":
                    # TABLE elements: narrate and keep artifact refs
                    narrated_text = self.narrator.narrate(
                        element, batch_id=batch_id
                    )
                    artifact_refs = artifact_map.get(
                        element.element_id, []
                    )

                    if narrated_text.strip():
                        unified_elem = UnifiedElement(
                            element_id=element.element_id,
                            text=narrated_text,
                            modality="TABLE",
                            section_path=element.section_path,
                            page_no=element.page_no,
                            position_index=element.position_index,
                            artifact_refs=artifact_refs,
                            source_doc=element.source_doc,
                            extraction_confidence=0.9,
                        )
                        unified.append(unified_elem)
                    else:
                        log.warning(
                            f"TABLE narration produced empty text for "
                            f"{element.element_id}; skipping"
                        )

                elif element.modality == "IMAGE":
                    # IMAGE elements: describe and keep artifact ref
                    artifact_refs = artifact_map.get(
                        element.element_id, []
                    )

                    # Extract image bytes from artifact if available
                    image_bytes = None
                    if artifact_refs:
                        try:
                            # In actual implementation, retrieve bytes
                            # from artifact_store via artifact_refs
                            # For now, placeholder
                            pass
                        except Exception as e:
                            log.warning(
                                f"Could not retrieve artifact for "
                                f"{element.element_id}: {str(e)}"
                            )

                    description, confidence = (
                        self.descriptor.describe(
                            element,
                            image_bytes or b"",
                            artifact_refs,
                        )
                    )

                    if description.strip():
                        unified_elem = UnifiedElement(
                            element_id=element.element_id,
                            text=description,
                            modality="IMAGE",
                            section_path=element.section_path,
                            page_no=element.page_no,
                            position_index=element.position_index,
                            artifact_refs=artifact_refs,
                            source_doc=element.source_doc,
                            extraction_confidence=confidence,
                        )
                        unified.append(unified_elem)

                else:
                    log.warning(
                        f"Unknown modality {element.modality} for "
                        f"{element.element_id}; skipping"
                    )

            except Exception as e:
                log.error(
                    f"Failed to unify element {element.element_id}: "
                    f"{str(e)}"
                )
                # Graceful degradation: continue with next element
                continue

        log.debug(
            "Multimodal unification complete",
            extra={
                "unified_elements": len(unified),
                "modality_breakdown": {
                    "TEXT": sum(1 for e in unified if e.modality == "TEXT"),
                    "TABLE": sum(1 for e in unified if e.modality == "TABLE"),
                    "IMAGE": sum(1 for e in unified if e.modality == "IMAGE"),
                },
            },
        )

        return unified
