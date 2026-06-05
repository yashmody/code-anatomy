"""Certificate generator — DEPT®-branded PDF.

Uses reportlab Canvas for precise layout. Same colour palette and typography
spirit as the course (orange #FF4900 accent, serif title, mono details).

Phase 2c: non-production environments overlay a diagonal watermark and a
clarifying footer line so a DEV/STG certificate is visibly distinct from a
real credential. Production-environment certs are byte-stable — the watermark
branch is skipped entirely when `record["environment"] == "production"`.
"""
from datetime import datetime
from pathlib import Path
from typing import Dict

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.core import config


# Colours
OCHRE = HexColor("#FF4900")
INK = HexColor("#0a0a0a")
INK_SOFT = HexColor("#3f3f3f")
INK_FAINT = HexColor("#6f6f6f")
RULE = HexColor("#e6e3dc")


# Per-environment watermark + footer copy. Production is intentionally `None`
# so the production rendering path has zero visual change versus Phase 1.
_ENV_OVERLAY = {
    "development": {
        "watermark": "DEVELOPMENT — NOT VALID FOR CREDENTIALS",
        "footer": "Issued by DEPT® Academy — development environment. Not a credential.",
    },
    "staging": {
        "watermark": "STAGING — TEST CERTIFICATE",
        "footer": "Issued by DEPT® Academy — staging environment. Test certificate.",
    },
}


def _draw_dev_watermark(c: "canvas.Canvas", w: float, h: float, text: str) -> None:
    """Diagonal semi-transparent ochre watermark, drawn behind the main layout.

    Called immediately after `Canvas()` is constructed so subsequent strokes
    sit on top — the watermark reads as a tint rather than obscuring detail.
    Ochre #FF4900 at ~22% opacity keeps the cert readable while making the
    DEV/STG status unmistakable on screen and in print.
    """
    c.saveState()
    try:
        c.setFillColor(OCHRE)
        # ReportLab Canvas exposes alpha via setFillAlpha; 0.22 is the same
        # tint scrim the course HTML uses for blockquote backgrounds, which
        # keeps the brand language consistent across PDF + web.
        c.setFillAlpha(0.22)
        c.setFont("Helvetica-Bold", 64)
        c.translate(w / 2, h / 2)
        c.rotate(30)  # shallower than 45° — keeps the text horizontal-ish so it reads cleanly
        c.drawCentredString(0, 0, text)
    finally:
        c.restoreState()


def generate(record: Dict) -> Path:
    """Generate a PDF certificate for a passing attempt.

    record must contain: cert_id, user (name, email), score, difficulty,
    submitted_at.
    """
    cert_id = record["cert_id"]
    name = record["user"].get("name") or record["user"]["email"].split("@")[0]
    email = record["user"]["email"]
    score_pct = int(round(record["score"] * 100))
    difficulty = record["difficulty"].capitalize()
    date_str = datetime.utcnow().strftime("%d %B %Y")
    environment = record.get("environment") or "production"
    overlay = _ENV_OVERLAY.get(environment)

    fname = f"{cert_id}.pdf"
    path = config.CERTIFICATES_DIR / fname

    page_size = landscape(A4)
    w, h = page_size
    c = canvas.Canvas(str(path), pagesize=page_size)

    # Dev/staging watermark — drawn first so the rest of the layout sits on
    # top. Production skips this branch entirely; existing prod certs are
    # byte-stable relative to Phase 1.
    if overlay:
        _draw_dev_watermark(c, w, h, overlay["watermark"])

    # Outer border
    c.setStrokeColor(INK)
    c.setLineWidth(1)
    c.rect(15 * mm, 15 * mm, w - 30 * mm, h - 30 * mm)

    # Inner orange accent corner blocks (top-left and bottom-right)
    c.setFillColor(OCHRE)
    c.rect(15 * mm, h - 40 * mm, 60 * mm, 4 * mm, stroke=0, fill=1)
    c.rect(w - 75 * mm, 36 * mm, 60 * mm, 4 * mm, stroke=0, fill=1)

    # Top-left brand mark — ® placed right after "DEPT" using measured width
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(25 * mm, h - 32 * mm, "DEPT")
    dept_width = c.stringWidth("DEPT", "Helvetica-Bold", 22)
    c.setFillColor(OCHRE)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25 * mm + dept_width + 1, h - 32 * mm + 9, "®")

    # Tagline top-right
    c.setFillColor(INK_FAINT)
    c.setFont("Courier-Bold", 9)
    c.drawRightString(w - 25 * mm, h - 30 * mm, "ARCHITECT · CCA-F  |  CERTIFICATE OF COMPLETION")

    # Centerpiece — title
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w / 2, h - 70 * mm, "THIS IS TO CERTIFY THAT")

    c.setFillColor(INK)
    c.setFont("Times-Bold", 48)
    c.drawCentredString(w / 2, h - 95 * mm, name)

    # Underline beneath name
    c.setStrokeColor(OCHRE)
    c.setLineWidth(2)
    name_w = c.stringWidth(name, "Times-Bold", 48)
    c.line(
        (w - name_w) / 2 - 20,
        h - 100 * mm,
        (w + name_w) / 2 + 20,
        h - 100 * mm,
    )

    # Email under name (small, muted)
    c.setFillColor(INK_FAINT)
    c.setFont("Courier", 10)
    c.drawCentredString(w / 2, h - 108 * mm, email)

    # Body — has completed the course
    c.setFillColor(INK_SOFT)
    c.setFont("Helvetica", 14)
    c.drawCentredString(
        w / 2,
        h - 125 * mm,
        "has successfully completed",
    )

    c.setFillColor(INK)
    c.setFont("Times-Bold", 24)
    c.drawCentredString(
        w / 2,
        h - 140 * mm,
        "The Anatomy of Code — CCA-F",
    )

    c.setFillColor(INK_SOFT)
    c.setFont("Helvetica", 12)
    c.drawCentredString(
        w / 2,
        h - 152 * mm,
        f"with a score of {score_pct}% at the {difficulty} level.",
    )

    # Bottom row: cert id, date, signature line
    c.setFillColor(INK_FAINT)
    c.setFont("Courier-Bold", 9)

    # Cert ID box (left)
    c.drawString(30 * mm, 30 * mm, "CERTIFICATE ID")
    c.setFillColor(INK)
    c.setFont("Courier-Bold", 11)
    c.drawString(30 * mm, 24 * mm, cert_id)

    # Date (center)
    c.setFillColor(INK_FAINT)
    c.setFont("Courier-Bold", 9)
    c.drawCentredString(w / 2, 30 * mm, "ISSUED ON")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w / 2, 24 * mm, date_str)

    # Verify URL (right)
    c.setFillColor(INK_FAINT)
    c.setFont("Courier-Bold", 9)
    c.drawRightString(w - 30 * mm, 30 * mm, "VERIFY AT")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9)
    verify_url = f"dept.academy/verify/{cert_id}"
    c.drawRightString(w - 30 * mm, 24 * mm, verify_url)

    # Verify hint — non-prod environments swap in the explicit "not a credential"
    # line per 07 §8.2 so a casual reader cannot mistake a DEV/STG cert for the
    # real thing. Production copy is unchanged.
    if overlay:
        c.setFillColor(OCHRE)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(w / 2, 17 * mm, overlay["footer"])
    else:
        c.setFillColor(INK_FAINT)
        c.setFont("Helvetica-Oblique", 7)
        c.drawCentredString(
            w / 2,
            17 * mm,
            f"Authenticate this certificate by quoting the ID above. Issued by DEPT® Academy.",
        )

    c.showPage()
    c.save()
    return path
