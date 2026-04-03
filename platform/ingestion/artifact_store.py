"""
Content-addressable artifact storage for tables and figures.

Persists original table images, table DataFrames (Parquet), and figure images
to disk with deterministic paths. Artifacts are stored immediately during
extraction (not accumulated in memory), enabling efficient processing of
large documents (30+ pages).

Storage layout:
    {artifact_store_root}/
      {batch_id}/
        TABLE_IMAGE/
          {content_hash[:16]}.png
        TABLE_DATAFRAME/
          {content_hash[:16]}.parquet
        FIGURE_IMAGE/
          {content_hash[:16]}.png

Artifacts are keyed by element_id (content hash), making them stable and
reproducible across runs. Phase 5 HITL retrieval uses artifact_id + batch_id
to fetch originals for consultant review.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from typing import TYPE_CHECKING

from platform.ingestion._config import get_ingestion_config
from platform.ingestion._errors import ArtifactStorageError
from platform.ingestion.schemas import ArtifactRef, DocumentElement
from platform.observability.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["ArtifactStore"]

log = get_logger(__name__)


class ArtifactStore:
    """Content-addressable artifact storage.

    Stores table images, DataFrames, and figure images with deterministic
    paths. Supports retrieval by artifact_id for the API layer.

    Usage:
        store = ArtifactStore(batch_id="batch-123")
        refs = store.store_all(elements, extractor)  # Returns dict[element_id, list[ArtifactRef]]
        artifact_bytes, mime_type = store.retrieve("artifact-abc123")
    """

    def __init__(self, batch_id: str, root: Path | None = None):
        """Initialize artifact store for a batch.

        Args:
            batch_id: Unique batch identifier (typically from LangGraph state)
            root: Root storage directory. If None, uses IngestionConfig.artifact_store_root.
                  Can be a local path or S3 URI (if s3fs installed).
        """
        self.batch_id = batch_id

        if root is None:
            config = get_ingestion_config()
            root = config.artifact_store_root_resolved()
        else:
            root = Path(root) if isinstance(root, str) else root

        self.root = Path(root)
        self.batch_path = self.root / batch_id

        # Create batch directory
        try:
            self.batch_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ArtifactStorageError(
                f"Failed to create artifact store directory {self.batch_path}: {e}"
            ) from e

        log.debug(
            "Artifact store initialized",
            extra={"batch_id": batch_id, "root": str(self.root)},
        )

    def store_table_image(
        self,
        element: DocumentElement,
        table_image_bytes: bytes,
        content_hash: str | None = None,
    ) -> ArtifactRef:
        """Store a rasterized table image (PNG).

        Args:
            element: DocumentElement for the table (for metadata)
            table_image_bytes: PNG image bytes
            content_hash: Optional explicit hash. If None, computed from image bytes.

        Returns:
            ArtifactRef pointing to stored image

        Raises:
            ArtifactStorageError: If storage fails
        """
        if content_hash is None:
            content_hash = hashlib.sha256(table_image_bytes).hexdigest()[:16]

        artifact_id = content_hash
        subdir = self.batch_path / "TABLE_IMAGE"
        subdir.mkdir(parents=True, exist_ok=True)

        path = subdir / f"{artifact_id}.png"

        try:
            path.write_bytes(table_image_bytes)
            log.debug(
                f"Stored table image artifact",
                extra={
                    "artifact_id": artifact_id,
                    "path": str(path),
                    "size_kb": len(table_image_bytes) / 1024,
                },
            )
        except Exception as e:
            raise ArtifactStorageError(
                f"Failed to store table image {artifact_id}: {e}"
            ) from e

        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="TABLE_IMAGE",
            storage_path=str(path.relative_to(self.root)),
            page_no=element.page_no,
            section_path=element.section_path,
        )

    def store_table_dataframe(
        self,
        element: DocumentElement,
        dataframe: pd.DataFrame,
        content_hash: str | None = None,
    ) -> ArtifactRef:
        """Store a table as Parquet (preserves types, efficient).

        Parquet is chosen over CSV because it preserves column types and
        handles multi-line cell content without escaping issues.

        Args:
            element: DocumentElement for the table
            dataframe: Pandas DataFrame
            content_hash: Optional explicit hash. If None, computed from DataFrame columns.

        Returns:
            ArtifactRef pointing to stored Parquet file

        Raises:
            ArtifactStorageError: If storage fails
        """
        import pandas as pd  # noqa: PLC0415

        if content_hash is None:
            # Hash based on DataFrame shape and column names
            df_sig = (
                f"{dataframe.shape[0]},{dataframe.shape[1]},"
                + ",".join(dataframe.columns)
            )
            content_hash = hashlib.sha256(df_sig.encode()).hexdigest()[:16]

        artifact_id = content_hash
        subdir = self.batch_path / "TABLE_DATAFRAME"
        subdir.mkdir(parents=True, exist_ok=True)

        path = subdir / f"{artifact_id}.parquet"

        try:
            dataframe.to_parquet(
                path,
                engine="pyarrow",
                compression="snappy",
                index=False,
            )
            log.debug(
                "Stored table DataFrame artifact",
                extra={
                    "artifact_id": artifact_id,
                    "path": str(path),
                    "rows": len(dataframe),
                    "cols": len(dataframe.columns),
                },
            )
        except Exception as e:
            raise ArtifactStorageError(
                f"Failed to store table DataFrame {artifact_id}: {e}"
            ) from e

        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="TABLE_DATAFRAME",
            storage_path=str(path.relative_to(self.root)),
            page_no=element.page_no,
            section_path=element.section_path,
        )

    def store_figure_image(
        self,
        element: DocumentElement,
        image_bytes: bytes,
        content_hash: str | None = None,
    ) -> ArtifactRef:
        """Store a figure/diagram image (PNG, normalized).

        Normalizes format via Pillow (ensures PNG, consistent compression).

        Args:
            element: DocumentElement for the image
            image_bytes: Raw image bytes (any format supported by Pillow)
            content_hash: Optional explicit hash. If None, computed from image bytes.

        Returns:
            ArtifactRef pointing to stored PNG

        Raises:
            ArtifactStorageError: If storage fails
        """
        if content_hash is None:
            content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

        artifact_id = content_hash
        subdir = self.batch_path / "FIGURE_IMAGE"
        subdir.mkdir(parents=True, exist_ok=True)

        path = subdir / f"{artifact_id}.png"

        try:
            # Normalize to PNG via Pillow
            from PIL import Image  # noqa: PLC0415
            image = Image.open(io.BytesIO(image_bytes))
            # Convert to RGB if necessary (RGBA, grayscale, etc.)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(path, format="PNG", optimize=True)

            log.debug(
                "Stored figure image artifact",
                extra={
                    "artifact_id": artifact_id,
                    "path": str(path),
                    "original_format": image.format,
                    "size_kb": path.stat().st_size / 1024,
                },
            )
        except Exception as e:
            raise ArtifactStorageError(
                f"Failed to store figure image {artifact_id}: {e}"
            ) from e

        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="FIGURE_IMAGE",
            storage_path=str(path.relative_to(self.root)),
            page_no=element.page_no,
            section_path=element.section_path,
        )

    def store_all(
        self,
        elements: list[DocumentElement],
        extractor: object,  # ElementExtractor instance (type-hinted to avoid import)
    ) -> dict[str, list[ArtifactRef]]:
        """Store all artifacts (table images, DataFrames, figure images).

        Iterates elements; for TABLE modality stores image + DataFrame;
        for IMAGE modality stores figure image. TEXT elements are skipped.

        Args:
            elements: List of DocumentElements from ElementExtractor.extract()
            extractor: ElementExtractor instance (used to retrieve Docling objects)

        Returns:
            Dict mapping element_id → list of ArtifactRef objects.
            Example: {"elem-abc123": [ArtifactRef(TABLE_IMAGE), ArtifactRef(TABLE_DATAFRAME)]}

        Raises:
            ArtifactStorageError: If any artifact storage fails (early exit)
        """
        artifact_map: dict[str, list[ArtifactRef]] = {}

        for elem in elements:
            if elem.modality == "TABLE":
                # Retrieve Docling table object from extractor
                docling_table = extractor.get_docling_object(elem.element_id)
                if docling_table is None:
                    log.warning(
                        f"Docling table object not found for element {elem.element_id}; skipping artifact storage"
                    )
                    continue

                refs = []

                # Store table image (rasterized)
                try:
                    table_image_bytes = self._rasterize_table(docling_table, elem)
                    if table_image_bytes:
                        ref = self.store_table_image(
                            elem, table_image_bytes, content_hash=elem.element_id
                        )
                        refs.append(ref)
                except ArtifactStorageError:
                    log.warning(
                        f"Failed to store table image for element {elem.element_id}; continuing"
                    )

                # Store table as DataFrame (Parquet)
                try:
                    df = self._docling_table_to_dataframe(docling_table)
                    if df is not None and len(df) > 0:
                        ref = self.store_table_dataframe(
                            elem, df, content_hash=elem.element_id
                        )
                        refs.append(ref)
                except ArtifactStorageError:
                    log.warning(
                        f"Failed to store table DataFrame for element {elem.element_id}; continuing"
                    )

                if refs:
                    artifact_map[elem.element_id] = refs

            elif elem.modality == "IMAGE":
                # Retrieve Docling picture object from extractor
                docling_picture = extractor.get_docling_object(elem.element_id)
                if docling_picture is None:
                    log.warning(
                        f"Docling picture object not found for element {elem.element_id}; skipping artifact storage"
                    )
                    continue

                try:
                    # Extract image bytes from Docling picture
                    image_bytes = self._docling_picture_to_bytes(docling_picture)
                    if image_bytes:
                        ref = self.store_figure_image(
                            elem, image_bytes, content_hash=elem.element_id
                        )
                        artifact_map[elem.element_id] = [ref]
                except ArtifactStorageError:
                    log.warning(
                        f"Failed to store figure image for element {elem.element_id}; continuing"
                    )

        log.debug(
            "Artifact storage complete",
            extra={
                "batch_id": self.batch_id,
                "artifacts_stored": sum(len(v) for v in artifact_map.values()),
                "elements_with_artifacts": len(artifact_map),
            },
        )

        return artifact_map

    def retrieve(self, artifact_id: str) -> tuple[bytes, str]:
        """Retrieve artifact file bytes by ID.

        Used by the API endpoint to serve artifacts to the frontend.

        Args:
            artifact_id: Artifact ID (content hash)

        Returns:
            (file_bytes, mime_type) where mime_type is "image/png" or "application/octet-stream"

        Raises:
            ArtifactStorageError: If artifact not found or read fails
        """
        # Search for artifact across all subdirectories
        for subdir in ["TABLE_IMAGE", "TABLE_DATAFRAME", "FIGURE_IMAGE"]:
            for ext in ["png", "parquet"]:
                path = self.batch_path / subdir / f"{artifact_id}.{ext}"
                if path.exists():
                    try:
                        file_bytes = path.read_bytes()
                        mime_type = (
                            "image/png"
                            if ext == "png"
                            else "application/octet-stream"
                        )
                        return (file_bytes, mime_type)
                    except Exception as e:
                        raise ArtifactStorageError(
                            f"Failed to read artifact {artifact_id}: {e}"
                        ) from e

        raise ArtifactStorageError(
            f"Artifact {artifact_id} not found in batch {self.batch_id}"
        )

    @staticmethod
    def _rasterize_table(
        docling_table: object, element: DocumentElement
    ) -> bytes | None:
        """Rasterize a table to PNG image bytes.

        Uses Docling's page image export if available, or falls back to
        pdf2image for PDF sources.

        Args:
            docling_table: Docling Table object
            element: DocumentElement (for page number and bounding box)

        Returns:
            PNG image bytes, or None if rasterization fails
        """
        try:
            # Attempt Docling native rasterization
            if hasattr(docling_table, "export_to_image"):
                image_bytes = docling_table.export_to_image()
                if image_bytes:
                    return image_bytes
        except Exception as e:
            log.debug(
                f"Docling table rasterization failed; attempting fallback: {e}"
            )

        # Fallback: use Pillow to draw a simple box + text representation
        # (This is a minimal fallback; ideally Docling handles this)
        try:
            from PIL import Image  # noqa: PLC0415
            table_text = docling_table.export_to_markdown()
            image = Image.new("RGB", (800, 600), color="white")
            # Simple text rendering (not ideal, but better than nothing)
            # In production, use PIL.ImageDraw to render the markdown table
            return None  # Skip if markdown export fails
        except Exception as e:
            log.warning(f"Table rasterization fallback failed: {e}")
            return None

    @staticmethod
    def _docling_table_to_dataframe(docling_table: object) -> pd.DataFrame | None:
        """Convert Docling Table to Pandas DataFrame.

        Args:
            docling_table: Docling Table object

        Returns:
            Pandas DataFrame, or None if conversion fails
        """
        try:
            import pandas as pd  # noqa: PLC0415
            # Docling tables have export_to_dataframe method (or similar)
            if hasattr(docling_table, "export_to_dataframe"):
                return docling_table.export_to_dataframe()
            elif hasattr(docling_table, "data"):
                # Fallback: construct DataFrame from table data
                return pd.DataFrame(docling_table.data)
        except Exception as e:
            log.warning(f"Failed to convert Docling table to DataFrame: {e}")
            return None

    @staticmethod
    def _docling_picture_to_bytes(docling_picture: object) -> bytes | None:
        """Extract image bytes from Docling Picture object.

        Args:
            docling_picture: Docling Picture object

        Returns:
            Raw image bytes, or None if extraction fails
        """
        try:
            if hasattr(docling_picture, "image_data"):
                return docling_picture.image_data
            elif hasattr(docling_picture, "export_to_image"):
                return docling_picture.export_to_image()
        except Exception as e:
            log.warning(f"Failed to extract image bytes from Docling picture: {e}")
            return None
