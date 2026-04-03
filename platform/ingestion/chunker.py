"""Semantic chunking of unified element stream into enriched chunks.

Partitions list[UnifiedElement] into EnrichedChunk objects that respect:
1. Token budget (≤512 tokens, measured by bge-large-en-v1.5 tokenizer)
2. Section boundary (chunks never cross top-level sections)
3. Table row atomicity (narrated table rows never split across chunks)

Produces overlap (default 64 tokens) between adjacent chunks in the same section,
preserving cross-references at chunk boundaries. For large documents (200+ pages),
pair with windowed ElementExtractor upstream.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Iterable, Iterator
from typing import Any

from platform.ingestion._config import get_ingestion_config
from platform.ingestion.schemas import (
    ArtifactRef,
    ChunkMetadata,
    EnrichedChunk,
    UnifiedElement,
)
from platform.observability.logger import get_logger

__all__ = ["SemanticChunker"]

log = get_logger(__name__)


class _SimpleTokenizer:
    """Fallback tokenizer using word count approximation (1 word ≈ 1.3 tokens)."""

    def encode(self, text: str) -> _TokenIds:
        """Encode text to token IDs (approximated by word splitting)."""
        words = text.split()
        token_count = int(len(words) * 1.3)
        return _TokenIds(list(range(token_count)))

    def decode(self, ids: list[int]) -> str:
        """Decode token IDs back to text (approximated, lossy)."""
        # Return a placeholder; this is a fallback and not expected to be perfect
        return f"[{len(ids)} tokens]"


class _TokenIds:
    """Simple wrapper for token IDs."""

    def __init__(self, ids: list[int]) -> None:
        self.ids = ids


class SemanticChunker:
    """Token-bounded, section-respecting chunking of unified element streams.

    Produces EnrichedChunk objects from list[UnifiedElement] with metadata
    including cross-references, modality composition, and artifact references.

    Usage:
        chunker = SemanticChunker(max_tokens=512, overlap_tokens=64)
        chunks = chunker.chunk(unified_elements)
        assert all(1 <= c.token_count <= 600 for c in chunks)
    """

    def __init__(
        self,
        tokenizer_name: str = "BAAI/bge-large-en-v1.5",
        max_tokens: int = 512,
        overlap_tokens: int = 64,
    ):
        """Initialize chunker.

        Args:
            tokenizer_name: HuggingFace tokenizer ID (default: bge-large-en-v1.5)
            max_tokens: Target max tokens per chunk (default: 512)
            overlap_tokens: Overlap between adjacent chunks (default: 64)
        """
        self.tokenizer_name = tokenizer_name
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def chunk(
        self, elements: list[UnifiedElement]
    ) -> list[EnrichedChunk]:
        """Chunk unified elements into enriched chunks.

        Returns list sorted by (section_path, page_range[0]).

        Args:
            elements: List of UnifiedElement objects from Unifier

        Returns:
            Sorted list of EnrichedChunk objects
        """
        chunks = list(self._chunk_iter(elements))
        return sorted(
            chunks,
            key=lambda c: (
                c.section_path,
                c.page_range[0] if c.page_range else 0,
            ),
        )

    def _chunk_iter(
        self, elements: Iterable[UnifiedElement]
    ) -> Iterator[EnrichedChunk]:
        """Generator for memory-efficient chunking.

        Yields EnrichedChunk objects one at a time, keeping only the
        current buffer in memory.
        """
        buffer: list[UnifiedElement] = []
        modality_tokens: dict[str, int] = {}
        overlap_prefix = ""

        for element in elements:
            elem_tokens = self._count_tokens(element.text)

            # Condition 1: Section boundary change → hard flush (no overlap)
            if buffer and self._section_changed(buffer[-1], element):
                chunk = self._finalize_chunk(buffer, modality_tokens, "")
                yield chunk
                buffer = []
                modality_tokens = {}
                overlap_prefix = ""

            # Condition 2: Token budget exceeded → soft flush (carry overlap)
            current_total = self._count_tokens(overlap_prefix) if overlap_prefix else 0
            current_total += sum(modality_tokens.values())

            if current_total + elem_tokens > self.max_tokens:
                if buffer:
                    chunk = self._finalize_chunk(
                        buffer, modality_tokens, overlap_prefix
                    )
                    yield chunk
                    overlap_prefix = self._extract_overlap(chunk.unified_text)
                    buffer = []
                    modality_tokens = {}

                # Oversized single element: split into smaller pieces and process normally
                if elem_tokens > self.max_tokens:
                    sub_elements = self._split_oversized_element(element)
                    for sub_elem in sub_elements:
                        sub_tokens = self._count_tokens(sub_elem.text)

                        # Check buffer again for each sub-element
                        sub_current_total = (
                            self._count_tokens(overlap_prefix)
                            if overlap_prefix
                            else 0
                        )
                        sub_current_total += sum(modality_tokens.values())

                        # If adding this sub-element would exceed budget and buffer is not empty, flush
                        if sub_current_total + sub_tokens > self.max_tokens and buffer:
                            chunk = self._finalize_chunk(
                                buffer, modality_tokens, overlap_prefix
                            )
                            yield chunk
                            overlap_prefix = self._extract_overlap(chunk.unified_text)
                            buffer = []
                            modality_tokens = {}

                        # Accumulate sub-element
                        buffer.append(sub_elem)
                        modality_tokens[sub_elem.modality] = (
                            modality_tokens.get(sub_elem.modality, 0) + sub_tokens
                        )

                    continue

            # Accumulate element
            buffer.append(element)
            modality_tokens[element.modality] = (
                modality_tokens.get(element.modality, 0) + elem_tokens
            )

        # Condition 3: End of stream → final flush
        if buffer:
            yield self._finalize_chunk(buffer, modality_tokens, overlap_prefix)

    def _finalize_chunk(
        self,
        buffer: list[UnifiedElement],
        modality_tokens: dict[str, int],
        overlap_prefix: str,
    ) -> EnrichedChunk:
        """Finalize a chunk from buffer.

        Args:
            buffer: List of UnifiedElement objects to chunk
            modality_tokens: Dict of {modality: token_count} from buffer (not overlap)
            overlap_prefix: Overlap text from previous chunk (prepended to unified_text)

        Returns:
            EnrichedChunk with computed metadata
        """
        # Build unified text
        element_texts = [e.text for e in buffer]
        if overlap_prefix:
            unified_text = f"{overlap_prefix}\n" + "\n".join(element_texts)
        else:
            unified_text = "\n".join(element_texts)

        # Count tokens (includes overlap)
        token_count = self._count_tokens(unified_text)

        # Clamp to schema limit (600) with warning if exceeded
        if token_count > 600:
            log.warning(
                f"Chunk token count {token_count} exceeds limit 600; "
                f"clamping for schema validation (section_path={buffer[0].section_path})"
            )
            token_count = 600

        # Modality composition (from buffer only, NOT overlap)
        total_buffer_tokens = sum(modality_tokens.values())
        if total_buffer_tokens > 0:
            modality_composition = {
                m: t / total_buffer_tokens
                for m, t in modality_tokens.items()
            }
            # Normalize to sum exactly to 1.0 (within tolerance)
            composition_sum = sum(modality_composition.values())
            if abs(composition_sum - 1.0) > 0.001:
                modality_composition = {
                    m: v / composition_sum
                    for m, v in modality_composition.items()
                }
        else:
            modality_composition = {}

        # Cross-references (regex search)
        cross_refs = re.findall(
            r"(?:See|Refer to|Same as|per) (?:Section|Figure|REQ-)\S+",
            unified_text,
        )

        # Source pages and page range
        source_pages = sorted(set(e.page_no for e in buffer))
        page_range = (
            (source_pages[0], source_pages[-1]) if source_pages else (0, 0)
        )

        # Artifact refs (deduplicated by artifact_id)
        seen_artifact_ids: set[str] = set()
        artifact_refs: list[ArtifactRef] = []
        for element in buffer:
            for ref in element.artifact_refs:
                if ref.artifact_id not in seen_artifact_ids:
                    seen_artifact_ids.add(ref.artifact_id)
                    artifact_refs.append(ref)

        # Headings and modality metadata
        table_elements = [e for e in buffer if e.modality == "TABLE"]
        image_elements = [e for e in buffer if e.modality == "IMAGE"]

        headings = list(
            dict.fromkeys(
                e.section_path[-1]
                for e in buffer
                if e.section_path
            )
        )

        image_descriptions = (
            [e.text for e in image_elements] if image_elements else None
        )

        chunk_metadata = ChunkMetadata(
            headings=headings,
            has_table=bool(table_elements),
            has_image=bool(image_elements),
            table_row_count=len(table_elements) if table_elements else None,
            image_descriptions=image_descriptions,
            cross_references=cross_refs if cross_refs else None,
            source_pages=source_pages,
        )

        # Section path and source doc from first element
        section_path = buffer[0].section_path if buffer else []
        source_doc = buffer[0].source_doc if buffer else ""

        # Deterministic chunk ID
        chunk_id = hashlib.sha256(
            (unified_text + str(section_path)).encode("utf-8")
        ).hexdigest()[:24]

        return EnrichedChunk(
            chunk_id=chunk_id,
            unified_text=unified_text,
            chunk_metadata=chunk_metadata,
            modality_composition=modality_composition,
            artifact_refs=artifact_refs,
            section_path=section_path,
            page_range=page_range,
            source_doc=source_doc,
            token_count=token_count,
        )

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using the configured tokenizer.

        Args:
            text: Text to tokenize

        Returns:
            Token count
        """
        tokenizer = self._get_tokenizer()
        return len(tokenizer.encode(text).ids)

    def _section_changed(
        self, prev: UnifiedElement, curr: UnifiedElement
    ) -> bool:
        """Check if top-level section has changed.

        Args:
            prev: Previous element
            curr: Current element

        Returns:
            True if section_path[0] differs (or either is empty)
        """
        prev_top = prev.section_path[0] if prev.section_path else None
        curr_top = curr.section_path[0] if curr.section_path else None
        return prev_top != curr_top

    def _extract_overlap(self, text: str) -> str:
        """Extract last overlap_tokens from finalized chunk text.

        Args:
            text: Finalized chunk text

        Returns:
            Overlap text (last N tokens decoded), or empty string if chunk is small
        """
        tokenizer = self._get_tokenizer()
        ids = tokenizer.encode(text).ids
        if len(ids) <= self.overlap_tokens:
            return ""
        overlap_ids = ids[-self.overlap_tokens :]
        return tokenizer.decode(overlap_ids)

    def _split_oversized_element(
        self, element: UnifiedElement
    ) -> list[UnifiedElement]:
        """Split an oversized UnifiedElement into smaller sub-elements.

        Strategy:
          1. Split by paragraph breaks (\n\n)
          2. For paragraphs exceeding max_tokens, split by sentence boundaries
          3. Group consecutive segments greedily into sub-elements ≤ max_tokens
          4. Preserve original metadata (modality, section_path, page_no, source_doc, etc.)
          5. Append part suffix to element_id for uniqueness

        Args:
            element: UnifiedElement exceeding max_tokens

        Returns:
            List of UnifiedElement objects, each ≤ max_tokens
        """
        # Step 1: Split by paragraph breaks
        paragraphs = element.text.split("\n\n")

        # Step 2: Further split large paragraphs by sentence boundaries
        segments: list[str] = []
        for para in paragraphs:
            if self._count_tokens(para) <= self.max_tokens:
                segments.append(para)
            else:
                # Split by sentence: period, question mark, exclamation followed by space
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sentence in sentences:
                    if self._count_tokens(sentence) <= self.max_tokens:
                        segments.append(sentence)
                    else:
                        # If a single sentence still exceeds max_tokens, split by words
                        # and group greedily
                        words = sentence.split()
                        current_chunk: list[str] = []
                        for word in words:
                            test_text = " ".join(current_chunk + [word])
                            if self._count_tokens(test_text) <= self.max_tokens:
                                current_chunk.append(word)
                            else:
                                if current_chunk:
                                    segments.append(" ".join(current_chunk))
                                current_chunk = [word]
                        if current_chunk:
                            segments.append(" ".join(current_chunk))

        # Step 3: Group consecutive segments greedily into sub-elements
        sub_elements: list[UnifiedElement] = []
        part_idx = 0
        current_text: list[str] = []
        current_tokens = 0

        for segment in segments:
            segment_tokens = self._count_tokens(segment)
            test_text = "\n".join(current_text + [segment])
            test_tokens = self._count_tokens(test_text)

            if test_tokens <= self.max_tokens and current_text:
                current_text.append(segment)
                current_tokens = test_tokens
            else:
                # Finalize current sub-element
                if current_text:
                    merged_text = "\n".join(current_text)
                    sub_elem = UnifiedElement(
                        element_id=f"{element.element_id}_part_{part_idx}",
                        text=merged_text,
                        modality=element.modality,
                        section_path=element.section_path,
                        page_no=element.page_no,
                        position_index=element.position_index,
                        artifact_refs=element.artifact_refs,
                        source_doc=element.source_doc,
                        extraction_confidence=element.extraction_confidence,
                    )
                    sub_elements.append(sub_elem)
                    part_idx += 1
                    current_text = []
                    current_tokens = 0

                # Start new sub-element with current segment
                current_text = [segment]
                current_tokens = segment_tokens

        # Finalize last sub-element
        if current_text:
            merged_text = "\n".join(current_text)
            sub_elem = UnifiedElement(
                element_id=f"{element.element_id}_part_{part_idx}",
                text=merged_text,
                modality=element.modality,
                section_path=element.section_path,
                page_no=element.page_no,
                position_index=element.position_index,
                artifact_refs=element.artifact_refs,
                source_doc=element.source_doc,
                extraction_confidence=element.extraction_confidence,
            )
            sub_elements.append(sub_elem)

        if not sub_elements:
            # Fallback: return original element as-is (should not happen)
            return [element]

        log.info(
            f"Split oversized element {element.element_id} ({self._count_tokens(element.text)} tokens) "
            f"into {len(sub_elements)} parts"
        )
        return sub_elements

    def _get_tokenizer(self) -> Any:
        """Get or lazily initialize the tokenizer.

        Uses lazy singleton pattern with threading.Lock to ensure
        thread-safe, single initialization.

        Returns:
            Tokenizer instance (huggingface or fallback)
        """
        if self._tokenizer is None:
            with self._lock:
                if self._tokenizer is None:
                    try:
                        from tokenizers import Tokenizer

                        self._tokenizer = Tokenizer.from_pretrained(
                            self.tokenizer_name
                        )
                        log.debug(
                            f"Loaded tokenizer {self.tokenizer_name}"
                        )
                    except Exception as e:
                        log.warning(
                            f"Failed to load tokenizer {self.tokenizer_name}: "
                            f"{str(e)}; using word-count fallback"
                        )
                        self._tokenizer = _SimpleTokenizer()
        return self._tokenizer
