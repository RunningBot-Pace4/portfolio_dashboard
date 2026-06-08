from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _number(value: Any, decimals: int = 8) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.{decimals}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}%"
    except (TypeError, ValueError):
        return "-"


def _para(text: Any, style: ParagraphStyle) -> Paragraph:
    safe = "" if text is None else str(text)
    return Paragraph(safe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _make_table(data: list[list[Any]], widths: list[float], header_color=colors.HexColor("#172033")) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FC")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6DAE2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
            ]
        )
    )
    return table


def build_portfolio_pdf(summary: dict[str, Any], records: list[dict[str, Any]]) -> bytes:
    """Create a compact portfolio PDF report for download."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Market Share Live Portfolio Report",
        author="Market Share Live",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#111827"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCustom",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#667085"),
        spaceAfter=12,
    )
    h2_style = ParagraphStyle(
        "Heading2Custom",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#111827"),
        spaceBefore=10,
        spaceAfter=8,
    )
    cell_style = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#111827"),
    )
    right_style = ParagraphStyle(
        "RightCell",
        parent=cell_style,
        alignment=TA_RIGHT,
    )

    portfolio = summary.get("portfolio", {})
    holdings = summary.get("holdings", [])

    story = [
        Paragraph("Market Share Live Portfolio Report", title_style),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style),
    ]

    metrics_data = [
        ["Total Invested", "Current Market Value", "Total Earn / Loss", "Portfolio Return"],
        [
            _money(portfolio.get("total_invested")),
            _money(portfolio.get("market_value")),
            _money(portfolio.get("total_return")),
            _pct(portfolio.get("return_percent")),
        ],
    ]
    metrics = Table(metrics_data, colWidths=[65 * mm, 65 * mm, 65 * mm, 65 * mm])
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#EEF6FF")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#111827")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6DAE2")),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(metrics)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Summary by Share Code", h2_style))

    if holdings:
        holdings_data = [
            [
                _para("Share Code", cell_style),
                _para("Total Invested", right_style),
                _para("Total Units", right_style),
                _para("Avg Price", right_style),
                _para("Market Price", right_style),
                _para("Current Value", right_style),
                _para("Earn / Loss", right_style),
                _para("Return %", right_style),
                _para("Txns", right_style),
            ]
        ]
        for row in holdings:
            holdings_data.append(
                [
                    _para(row.get("share_code"), cell_style),
                    _para(_money(row.get("total_invested")), right_style),
                    _para(_number(row.get("total_units")), right_style),
                    _para(_money(row.get("average_price")), right_style),
                    _para(_money(row.get("current_price")), right_style),
                    _para(_money(row.get("market_value")), right_style),
                    _para(_money(row.get("total_return")), right_style),
                    _para(_pct(row.get("return_percent")), right_style),
                    _para(row.get("transaction_count"), right_style),
                ]
            )
        story.append(_make_table(holdings_data, [28 * mm, 31 * mm, 30 * mm, 25 * mm, 28 * mm, 31 * mm, 31 * mm, 24 * mm, 17 * mm]))
    else:
        story.append(Paragraph("No holdings yet.", subtitle_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Purchase Records", h2_style))

    if records:
        records_data = [
            [
                _para("Date", cell_style),
                _para("Share Code", cell_style),
                _para("Investment Amount", right_style),
                _para("Total Purchase Unit", right_style),
                _para("Average Price", right_style),
            ]
        ]
        for row in records:
            records_data.append(
                [
                    _para(row.get("purchase_date"), cell_style),
                    _para(row.get("share_code"), cell_style),
                    _para(_money(row.get("investment_amount")), right_style),
                    _para(_number(row.get("purchase_units")), right_style),
                    _para(_money(row.get("average_price")), right_style),
                ]
            )
        story.append(_make_table(records_data, [35 * mm, 35 * mm, 50 * mm, 50 * mm, 45 * mm], colors.HexColor("#243B53")))
    else:
        story.append(Paragraph("No purchase records yet.", subtitle_style))

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Note: Market prices are pulled from the configured live quote provider and may be delayed or unavailable for some symbols. This report is for personal portfolio tracking only.",
            subtitle_style,
        )
    )

    doc.build(story)
    return buffer.getvalue()
