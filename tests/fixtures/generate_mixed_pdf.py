"""
Generate a mixed-content test PDF (text + bordered table + prose) that
exercises the pdfplumber parser's table detection, prose extraction, and
chunk stitching paths.

Run (no permanent install needed):
    uv run --with reportlab python tests/fixtures/generate_mixed_pdf.py

Output:  tests/fixtures/mixed_content_sample.pdf
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(__file__).parent / "mixed_content_sample.pdf"

STYLES = getSampleStyleSheet()
H1 = STYLES["Heading1"]
BODY = STYLES["BodyText"]
BODY.leading = 14


def _table_style() -> TableStyle:
    """Bordered lattice table — pdfplumber finds these reliably."""
    return TableStyle(
        [
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            # Data rows
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EBF3FB")]),
            # Grid lines — these create a lattice table that pdfplumber detects
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2E75B6")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def build_story() -> list:
    story = []
    W = A4[0] - 4 * cm  # usable table width

    # ------------------------------------------------------------------
    # Page 1 — prose + AP requirements table
    # ------------------------------------------------------------------
    story.append(Paragraph("D365 F&O Requirement Specification", H1))
    story.append(Spacer(1, 0.4 * cm))

    story.append(
        Paragraph(
            "This document captures functional requirements for the Accounts Payable "
            "and General Ledger modules of the Microsoft Dynamics 365 Finance & Operations "
            "implementation. Requirements are classified by priority (MUST / SHOULD / NICE) "
            "and assigned to deployment waves.",
            BODY,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    story.append(
        Paragraph(
            "The fitment engine will ingest this document during Phase 1 (Ingestion) "
            "and extract structured requirements from both the prose sections and the "
            "tables below. Each table row maps to a candidate requirement atom.",
            BODY,
        )
    )
    story.append(Spacer(1, 0.5 * cm))

    # AP requirements table (lattice — bordered)
    story.append(Paragraph("Accounts Payable Requirements", H1))
    story.append(Spacer(1, 0.3 * cm))

    ap_data = [
        # Header row
        ["Requirement Description", "Priority", "Wave", "D365 Feature Area"],
        [
            "System shall post vendor invoices automatically\nupon three-way match approval",
            "MUST",
            "Wave 1",
            "AP > Invoice Posting",
        ],
        [
            "Support multi-currency invoice entry with\nautomatic exchange rate lookup",
            "MUST",
            "Wave 1",
            "AP > Currency",
        ],
        [
            "Enable vendor self-service portal for invoice\nsubmission and status tracking",
            "SHOULD",
            "Wave 2",
            "AP > Vendor Portal",
        ],
        [
            "Generate ageing report grouped by vendor\nand due date bucket (30/60/90/120+)",
            "MUST",
            "Wave 1",
            "AP > Reporting",
        ],
        [
            "Send automated payment remittance advice\nvia email after payment run completes",
            "NICE",
            "Wave 3",
            "AP > Payments",
        ],
    ]

    col_widths = [W * 0.48, W * 0.10, W * 0.12, W * 0.30]
    ap_table = Table(ap_data, colWidths=col_widths, repeatRows=1)
    ap_table.setStyle(_table_style())
    story.append(ap_table)
    story.append(Spacer(1, 0.5 * cm))

    story.append(
        Paragraph(
            "All MUST-priority requirements in Wave 1 are in scope for the initial "
            "go-live. SHOULD and NICE requirements will be re-evaluated at the end of "
            "Wave 1 based on budget and timeline. Any requirement not matched to a "
            "D365 standard feature area will be flagged for custom development review.",
            BODY,
        )
    )
    story.append(Spacer(1, 0.8 * cm))

    # ------------------------------------------------------------------
    # Page 2 — GL requirements table + closing prose
    # ------------------------------------------------------------------
    story.append(Paragraph("General Ledger Requirements", H1))
    story.append(Spacer(1, 0.3 * cm))

    story.append(
        Paragraph(
            "The General Ledger module requirements below cover chart of accounts "
            "configuration, intercompany settlements, and period-close automation.",
            BODY,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    gl_data = [
        ["Requirement Description", "Priority", "Wave", "D365 Feature Area"],
        [
            "Define shared chart of accounts across all\nlegal entities in the group",
            "MUST",
            "Wave 1",
            "GL > Chart of Accounts",
        ],
        [
            "Automate intercompany eliminations during\nmonth-end consolidation process",
            "MUST",
            "Wave 2",
            "GL > Intercompany",
        ],
        [
            "Configure financial dimensions for department,\ncost centre, and project",
            "MUST",
            "Wave 1",
            "GL > Dimensions",
        ],
        [
            "Enable automated period-close checklist\nwith role-based task assignment",
            "SHOULD",
            "Wave 2",
            "GL > Period Close",
        ],
        [
            "Produce IFRS-compliant financial statements\ndirectly from the GL module",
            "MUST",
            "Wave 1",
            "GL > Financial Reporting",
        ],
        [
            "Support budget vs actual variance reporting\nwith drill-through to transactions",
            "SHOULD",
            "Wave 2",
            "GL > Budgeting",
        ],
    ]

    gl_table = Table(gl_data, colWidths=col_widths, repeatRows=1)
    gl_table.setStyle(_table_style())
    story.append(gl_table)
    story.append(Spacer(1, 0.5 * cm))

    story.append(
        Paragraph(
            "Integration requirements between AP and GL include real-time subledger "
            "posting, automated journal voucher creation on invoice approval, and "
            "reconciliation reporting between the AP subledger and the GL control account. "
            "These cross-module requirements will be captured as separate integration "
            "requirement atoms during the fitment analysis.",
            BODY,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    story.append(
        Paragraph(
            "Out-of-scope items for this specification: tax engine configuration, "
            "banking integrations, fixed asset module, and project accounting. These "
            "will be documented in separate requirement packs submitted in Phase 2.",
            BODY,
        )
    )

    return story


def main() -> None:
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(build_story())
    print(f"Generated: {OUTPUT}")
    print(f"Size:      {OUTPUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
