#!/usr/bin/env python3
"""
Business Card Generator — tiled on A4 with dashed cut lines.

Card size:  85 mm × 55 mm  (standard European / ISO 7810 ID-1 derivative)
Grid:       2 columns × 5 rows = 10 cards per A4 sheet
Font:       Helvetica family (built-in to every PDF reader)

Layout per card (top to bottom):
  - Blank name line (owner fills in by hand)
  - Title
  - Company name (bold)
  - Tagline (italic)
  - Separator rule
  - Web + Address block
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import Color, black, white
from reportlab.pdfgen import canvas

# ── Dimensions ────────────────────────────────────────────────
PAGE_W, PAGE_H = A4  # 210 × 297 mm in points
CARD_W = 85 * mm
CARD_H = 55 * mm

COLS = 2
ROWS = 5

# Center the grid on the page
MARGIN_X = (PAGE_W - COLS * CARD_W) / 2
MARGIN_Y = (PAGE_H - ROWS * CARD_H) / 2

# Inner padding inside each card
PAD = 5 * mm

# Colors
DARK = Color(0.15, 0.15, 0.15)        # near-black for main text
MID  = Color(0.40, 0.40, 0.40)        # medium grey for secondary
LIGHT_RULE = Color(0.70, 0.70, 0.70)  # light grey for separator line
CUT_COLOR  = Color(0.75, 0.75, 0.75)  # very light grey dashed lines

# ── Card content ──────────────────────────────────────────────
TITLE    = "Senior Waste Management Consultant"
COMPANY  = "Fuhgeddaboudit Waste Co."
TAGLINE  = '"You Got Trash? We Got Solutions."'
WEB      = "midnight-haul.com"
ADDR_L1  = "404 Industrial Way, Unit 13"
ADDR_L2  = "Jersey City, NJ 07302"


def draw_cut_lines(c):
    """Draw discreet dashed lines along the card grid edges for cutting."""
    c.saveState()
    c.setStrokeColor(CUT_COLOR)
    c.setLineWidth(0.4)
    c.setDash(4, 4)  # 4pt dash, 4pt gap

    # Vertical lines (COLS + 1)
    for col in range(COLS + 1):
        x = MARGIN_X + col * CARD_W
        c.line(x, MARGIN_Y - 3 * mm, x, MARGIN_Y + ROWS * CARD_H + 3 * mm)

    # Horizontal lines (ROWS + 1)
    for row in range(ROWS + 1):
        y = MARGIN_Y + row * CARD_H
        c.line(MARGIN_X - 3 * mm, y, MARGIN_X + COLS * CARD_W + 3 * mm, y)

    c.restoreState()


def draw_card(c, x, y):
    """
    Draw one business card with bottom-left corner at (x, y).

    Layout (measured from card top):
      6mm   — blank underline for handwritten name
      15mm  — title
      21mm  — company (bold)
      27mm  — tagline (italic)
      33mm  — thin separator rule
      37mm  — web
      42mm  — address line 1
      47mm  — address line 2
    """
    c.saveState()

    # ── Name blank line (top area) ────────────────────────────
    name_y = y + CARD_H - 10 * mm
    # Draw a light underline where the name goes
    c.setStrokeColor(LIGHT_RULE)
    c.setLineWidth(0.5)
    line_start = x + PAD
    line_end = x + CARD_W - PAD
    c.line(line_start, name_y - 1 * mm, line_end, name_y - 1 * mm)
    # Small label above the line
    c.setFont("Helvetica", 9)
    c.setFillColor(DARK)
    c.drawString(line_start, name_y + 1.5 * mm, 'Name')
    # --- Name
    # c.setFont("Helvetica", 7)
    # c.setFillColor(MID)
    # c.drawString(line_start + 10 * mm, name_y + 1.5 * mm, )

    # ── Title ─────────────────────────────────────────────────
    title_y = name_y - 8 * mm
    c.setFont("Helvetica", 7.5)
    c.setFillColor(DARK)
    c.drawString(x + PAD, title_y, TITLE)

    # ── Company ───────────────────────────────────────────────
    comp_y = title_y - 7 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(DARK)
    c.drawString(x + PAD, comp_y, COMPANY)

    # ── Tagline ───────────────────────────────────────────────
    tag_y = comp_y - 6 * mm
    c.setFont("Helvetica-Oblique", 6.5)
    c.setFillColor(MID)
    c.drawString(x + PAD, tag_y, TAGLINE)

    # ── Separator rule ────────────────────────────────────────
    sep_y = tag_y - 4 * mm
    c.setStrokeColor(LIGHT_RULE)
    c.setLineWidth(0.3)
    c.setDash([])  # solid
    c.line(x + PAD, sep_y, x + CARD_W - PAD, sep_y)

    # ── Contact block ─────────────────────────────────────────
    contact_y = sep_y - 5 * mm
    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(DARK)
    c.drawString(x + PAD, contact_y, WEB)

    c.setFont("Helvetica", 6)
    c.setFillColor(MID)
    c.drawString(x + PAD, contact_y - 4.5 * mm, ADDR_L1)
    c.drawString(x + PAD, contact_y - 9 * mm, ADDR_L2)

    c.restoreState()


def generate_pdf(output_path, num_pages=1):
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle("Business Cards — Fuhgeddaboudit Waste Co.")

    for _ in range(num_pages):
        # White background (default)
        draw_cut_lines(c)

        for row in range(ROWS):
            for col in range(COLS):
                card_x = MARGIN_X + col * CARD_W
                card_y = MARGIN_Y + (ROWS - 1 - row) * CARD_H  # top row first
                draw_card(c, card_x, card_y)

        c.showPage()

    c.save()
    print(f"✓ Generated {output_path}  ({num_pages} page(s), {COLS * ROWS * num_pages} cards)")


if __name__ == "__main__":
    generate_pdf("./business_cards.pdf", num_pages=1)
