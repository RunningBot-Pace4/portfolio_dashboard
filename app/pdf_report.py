from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


DARK_HEADER = colors.HexColor("#172033")
BLUE_HEADER = colors.HexColor("#243B53")
TEXT_DARK = colors.HexColor("#111827")
TEXT_MUTED = colors.HexColor("#667085")
GRID_LINE = colors.HexColor("#D6DAE2")
ALT_ROW = colors.HexColor("#F7F9FC")
METRIC_ROW = colors.HexColor("#EEF6FF")
BUY_BG = colors.HexColor("#E8F8F1")
SELL_BG = colors.HexColor("#FFF1F2")


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


def _header_para(text: Any, style: ParagraphStyle) -> Paragraph:
    return _para(text, style)


def _make_table(data: list[list[Any]], widths: list[float], header_color=DARK_HEADER) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BACKGROUND", (0, 1), (-1, -1), ALT_ROW),
                ("GRID", (0, 0), (-1, -1), 0.25, GRID_LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
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
        rightMargin=9 * mm,
        leftMargin=9 * mm,
        topMargin=11 * mm,
        bottomMargin=10 * mm,
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
        textColor=TEXT_DARK,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCustom",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=TEXT_MUTED,
        spaceAfter=10,
    )
    h2_style = ParagraphStyle(
        "Heading2Custom",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=TEXT_DARK,
        spaceBefore=9,
        spaceAfter=7,
    )
    cell_style = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9,
        textColor=TEXT_DARK,
    )
    right_style = ParagraphStyle(
        "RightCell",
        parent=cell_style,
        alignment=TA_RIGHT,
    )
    center_style = ParagraphStyle(
        "CenterCell",
        parent=cell_style,
        alignment=TA_CENTER,
    )
    header_style = ParagraphStyle(
        "HeaderCell",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.2,
        leading=9,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    header_right_style = ParagraphStyle(
        "HeaderRightCell",
        parent=header_style,
        alignment=TA_RIGHT,
    )
    header_left_style = ParagraphStyle(
        "HeaderLeftCell",
        parent=header_style,
        alignment=TA_CENTER,
    )

    portfolio = summary.get("portfolio", {})
    holdings = summary.get("holdings", [])

    story = [
        Paragraph("Market Share Live Portfolio Report", title_style),
        Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style),
    ]

    metrics_data = [
        ["Total Buy Amount", "Current Value", "Realized Earn / Loss", "Unrealized Earn / Loss", "Total Earn / Loss", "Portfolio Return"],
        [
            _money(portfolio.get("total_buy_amount")),
            _money(portfolio.get("market_value")),
            _money(portfolio.get("realized_return")),
            _money(portfolio.get("unrealized_return")),
            _money(portfolio.get("total_return")),
            _pct(portfolio.get("return_percent")),
        ],
    ]
    metrics = Table(metrics_data, colWidths=[43 * mm, 43 * mm, 47 * mm, 48 * mm, 47 * mm, 41 * mm])
    metrics.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK_HEADER),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, 1), METRIC_ROW),
                ("TEXTCOLOR", (0, 1), (-1, 1), TEXT_DARK),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.25, GRID_LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(metrics)
    story.append(Spacer(1, 7))

    story.append(Paragraph("Summary by Share Code", h2_style))

    if holdings:
        holdings_data = [
            [
                _header_para("Share", header_left_style),
                _header_para("Buy Amt", header_right_style),
                _header_para("Sell Amt", header_right_style),
                _header_para("Remain Units", header_right_style),
                _header_para("Avg Cost", header_right_style),
                _header_para("Market", header_right_style),
                _header_para("Current Value", header_right_style),
                _header_para("Realized", header_right_style),
                _header_para("Unrealized", header_right_style),
                _header_para("Total P/L", header_right_style),
                _header_para("Return %", header_right_style),
                _header_para("Txns", header_right_style),
            ]
        ]
        for row in holdings:
            holdings_data.append(
                [
                    _para(row.get("share_code"), cell_style),
                    _para(_money(row.get("total_buy_amount")), right_style),
                    _para(_money(row.get("total_sell_amount")), right_style),
                    _para(_number(row.get("remaining_units")), right_style),
                    _para(_money(row.get("average_price")), right_style),
                    _para(_money(row.get("current_price")), right_style),
                    _para(_money(row.get("market_value")), right_style),
                    _para(_money(row.get("realized_return")), right_style),
                    _para(_money(row.get("unrealized_return")), right_style),
                    _para(_money(row.get("total_return")), right_style),
                    _para(_pct(row.get("return_percent")), right_style),
                    _para(row.get("transaction_count"), right_style),
                ]
            )
        story.append(
            _make_table(
                holdings_data,
                [18 * mm, 24 * mm, 23 * mm, 25 * mm, 21 * mm, 22 * mm, 27 * mm, 24 * mm, 25 * mm, 24 * mm, 20 * mm, 13 * mm],
            )
        )
    else:
        story.append(Paragraph("No holdings yet.", subtitle_style))

    story.append(Spacer(1, 7))
    story.append(Paragraph("Buy / Sell Transaction Records", h2_style))

    if records:
        records_data = [
            [
                _header_para("Date", header_left_style),
                _header_para("Type", header_left_style),
                _header_para("Share Code", header_left_style),
                _header_para("Amount", header_right_style),
                _header_para("Share Unit", header_right_style),
                _header_para("Price / Share", header_right_style),
            ]
        ]
        for row in records:
            tx_type = row.get("transaction_type", "BUY")
            records_data.append(
                [
                    _para(row.get("purchase_date"), cell_style),
                    _para(tx_type, center_style),
                    _para(row.get("share_code"), cell_style),
                    _para(_money(row.get("investment_amount")), right_style),
                    _para(_number(row.get("purchase_units")), right_style),
                    _para(_money(row.get("average_price")), right_style),
                ]
            )
        record_table = _make_table(records_data, [31 * mm, 22 * mm, 31 * mm, 46 * mm, 46 * mm, 44 * mm], BLUE_HEADER)
        story.append(record_table)
    else:
        story.append(Paragraph("No transaction records yet.", subtitle_style))

    story.append(Spacer(1, 9))
    story.append(
        Paragraph(
            "Note: Sell profit uses average cost method and does not include broker fees. Market prices may be delayed or unavailable for some symbols. This report is for personal portfolio tracking only.",
            subtitle_style,
        )
    )

    doc.build(story)
    return buffer.getvalue()
