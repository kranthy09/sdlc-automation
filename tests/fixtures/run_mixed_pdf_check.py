"""
Parse mixed_content_sample.pdf with DoclingParser and print a human-readable
summary of what was extracted — tables, prose chunks, sections, and page refs.

Run AFTER generating the PDF:
    uv run python tests/fixtures/run_mixed_pdf_check.py

Expected output:
  - 10+ table rows (5 AP + 6 GL)
  - 4-6 prose chunks across 2 pages
  - Each table row shows column headers mapped to values
"""

import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from platform.parsers.docling_parser import DoclingParser  # noqa: E402

PDF = Path(__file__).parent / "mixed_content_sample.pdf"


def _hr(char: str = "─", width: int = 70) -> str:
    return char * width


def main() -> None:
    if not PDF.exists():
        print(f"ERROR: {PDF} not found.")
        print("Generate it first:")
        print("  uv run --with reportlab python tests/fixtures/generate_mixed_pdf.py")
        sys.exit(1)

    print(f"\nParsing: {PDF.name}  ({PDF.stat().st_size:,} bytes)")
    print(_hr("═"))

    result = DoclingParser().parse(PDF)

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    print(f"\n TABLE ROWS EXTRACTED: {len(result.tables)}")
    print(_hr())
    for i, row in enumerate(result.tables, 1):
        print(f"  Row {i:02d}:")
        for col, val in row.items():
            # Truncate long values for readability
            display = val.replace("\n", " ")
            if len(display) > 60:
                display = display[:57] + "..."
            print(f"    {col!r:35s} → {display!r}")
        print()

    # ------------------------------------------------------------------
    # Prose chunks
    # ------------------------------------------------------------------
    print(f"\n PROSE CHUNKS EXTRACTED: {len(result.prose)}")
    print(_hr())
    for i, chunk in enumerate(result.prose, 1):
        overlap_tag = " [overlap]" if chunk.has_overlap else ""
        section_tag = f" § {chunk.section}" if chunk.section else ""
        print(
            f"  Chunk {i:02d} | page={chunk.page}"
            f" | chars={len(chunk.text)}{overlap_tag}{section_tag}"
        )
        preview = chunk.text[:120].replace("\n", " ")
        if len(chunk.text) > 120:
            preview += "..."
        print(f"    {preview!r}")
        print()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(_hr("═"))
    print(f"  Total table rows : {len(result.tables)}")
    print(f"  Total prose chunks: {len(result.prose)}")
    pages_seen = {c.page for c in result.prose}
    print(f"  Pages with prose  : {sorted(pages_seen)}")
    columns_seen: set[str] = set()
    for row in result.tables:
        columns_seen.update(row.keys())
    print(f"  Unique table cols : {sorted(columns_seen)}")
    print()


if __name__ == "__main__":
    main()
