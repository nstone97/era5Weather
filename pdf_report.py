"""Build a landscape PDF of monthly wave-or-wind exceedance tables."""

from __future__ import annotations

import io
import math
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE = landscape(letter)
NAVY = colors.HexColor("#07131d")
HEADER_BG = colors.HexColor("#1e4d7b")
GRID = colors.HexColor("#1b3b52")
MUTED = colors.HexColor("#8aa0b5")
ACCENT = colors.HexColor("#4eb3e0")

_STOPS = [
    (12, 40, 58),
    (30, 77, 123),
    (224, 164, 90),
    (213, 107, 78),
]


def format_lat(lat: float) -> str:
    hemi = "N" if lat >= 0 else "S"
    return f"{abs(lat):.3f}°{hemi}"


def format_lon(lon: float) -> str:
    hemi = "E" if lon >= 0 else "W"
    return f"{abs(lon):.3f}°{hemi}"


def location_line(status: dict[str, Any]) -> str:
    return (
        f"{format_lat(status['request_latitude'])}, "
        f"{format_lon(status['request_longitude'])}"
    )


def _mix_color(pct: float) -> tuple[colors.Color, colors.Color]:
    t = max(0.0, min(1.0, pct / 100.0))
    pos = t * (len(_STOPS) - 1)
    i = min(len(_STOPS) - 2, int(math.floor(pos)))
    f = pos - i
    rgb = tuple(round(a + (b - a) * f) for a, b in zip(_STOPS[i], _STOPS[i + 1]))
    bg = colors.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
    fg = colors.HexColor("#07131d") if luminance > 0.62 else colors.HexColor("#f4f8fb")
    return bg, fg


def _header(canvas, doc, status: dict[str, Any]) -> None:
    width, height = PAGE
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, height - 0.95 * inch, width, 0.95 * inch, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.6 * inch, height - 0.28 * inch, "ERA5  ·  WAVE & WIND EXCEEDANCE")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(0.6 * inch, height - 0.52 * inch, f"Location: {location_line(status)}")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    detail = (
        f"Requested point {location_line(status)}"
        f"    Wave grid {format_lat(status['wave_latitude'])}, {format_lon(status['wave_longitude'])}"
        f"    Wind grid {format_lat(status['surface_latitude'])}, {format_lon(status['surface_longitude'])}"
    )
    canvas.drawString(0.6 * inch, height - 0.72 * inch, detail)
    period = (
        f"{status['start'][:10]}  to  {status['end'][:10]}"
        f"    {status['hours']:,} hours"
        f"    Cell = % of hours with Hs or 10 m wind above thresholds"
    )
    canvas.drawString(0.6 * inch, height - 0.86 * inch, period)
    canvas.restoreState()


def _month_table(month: str, payload: dict[str, Any]) -> KeepTogether:
    waves = payload["wave_thresholds"]
    winds = payload["wind_thresholds"]
    grid = payload["months"][month]

    cell = ParagraphStyle(
        "cell",
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.white,
    )
    body = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#f4f8fb"),
    )
    title = ParagraphStyle(
        "month",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        textColor=NAVY,
        spaceAfter=4,
    )

    header = [Paragraph("<b>Hs (ft)</b>", cell)] + [
        Paragraph(f"<b>{wind} kt</b>", cell) for wind in winds
    ]
    rows = [header]
    commands: list = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("BACKGROUND", (0, 1), (0, -1), HEADER_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index, wave in enumerate(waves):
        line = [Paragraph(f"<b>{wave}</b>", cell)]
        for col_index, _wind in enumerate(winds):
            pct = grid[row_index][col_index]
            if pct is None or (isinstance(pct, float) and math.isnan(pct)):
                line.append(Paragraph("—", body))
                continue
            bg, fg = _mix_color(float(pct))
            hex_fg = f"#{int(fg.red * 255):02x}{int(fg.green * 255):02x}{int(fg.blue * 255):02x}"
            line.append(Paragraph(f'<font color="{hex_fg}">{float(pct):.2f}%</font>', body))
            commands.append(("BACKGROUND", (col_index + 1, row_index + 1), (col_index + 1, row_index + 1), bg))
        rows.append(line)

    usable = PAGE[0] - 1.2 * inch
    first = 0.85 * inch
    rest = (usable - first) / len(winds)
    table = Table(rows, colWidths=[first] + [rest] * len(winds), repeatRows=1)
    table.setStyle(TableStyle(commands))
    return KeepTogether([Paragraph(month, title), table, Spacer(1, 10)])


def build_pdf(payload: dict[str, Any], status: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    months = list(payload["months"])
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=1.1 * inch,
        bottomMargin=0.45 * inch,
        title=f"Wave and wind exceedance — {location_line(status)}",
        author="ERA5 climatology",
    )
    story = []
    for index, month in enumerate(months):
        story.append(_month_table(month, payload))
        if index < len(months) - 1 and (index + 1) % 2 == 0:
            story.append(PageBreak())

    def on_page(canvas, doc):
        _header(canvas, doc, status)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()


def filename(status: dict[str, Any]) -> str:
    lat = status["request_latitude"]
    lon = status["request_longitude"]
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"exceedance_{abs(lat):.3f}{ns}_{abs(lon):.3f}{ew}.pdf"
