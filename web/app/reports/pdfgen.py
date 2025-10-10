# app/reports/pdfgen.py — génération PDF (reportlab)
from __future__ import annotations
from io import BytesIO
from textwrap import wrap

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics


def build_pdf(event, summary, csv_rows, parent_rows=None) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    def header():
        c.saveState()
        c.setFillColor(colors.HexColor("#003E6B"))
        c.rect(0, height - 2 * cm, width, 2 * cm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1.2 * cm, height - 1.2 * cm, "Préparation Matériel — Rapport")
        c.setFont("Helvetica", 10)
        date_label = event.date.strftime("%d/%m/%Y") if getattr(event, "date", None) else "-"
        c.drawRightString(
            width - 1.2 * cm,
            height - 1.2 * cm,
            f"Événement: {event.name}  •  Date: {date_label}",
        )
        c.restoreState()

    def footer(page):
        c.saveState()
        c.setStrokeColor(colors.HexColor("#E0E0E0"))
        c.line(1 * cm, 1.5 * cm, width - 1 * cm, 1.5 * cm)
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawString(1.2 * cm, 1.0 * cm, "Généré par VERIFMATOS")
        c.drawRightString(width - 1.2 * cm, 1.0 * cm, f"Page {page}")
        c.restoreState()

    parent_rows = parent_rows or []

    header()
    c.setTitle(f"Rapport événement {event.name}")
    info_y = height - 2.9 * cm
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#4F5D75"))
    c.drawString(1.2 * cm, info_y, f"Identifiant : #{event.id}")
    created_label = getattr(getattr(event, "created_by", None), "full_name", None) or getattr(
        getattr(event, "created_by", None), "email", "-"
    )
    c.drawString(6.8 * cm, info_y, f"Créé par : {str(created_label) if created_label else '-'}")

    cards = [
        ("Total", summary.get("total", "-"), "#0A84FF"),
        ("Conformes", summary.get("ok", "-"), "#2BA84A"),
        ("Non conformes", summary.get("not_ok", "-"), "#D64545"),
        ("À traiter", summary.get("todo", "-"), "#F39200"),
    ]
    card_width = (width - 2.4 * cm - (len(cards) - 1) * 0.6 * cm) / len(cards)
    card_height = 2.4 * cm
    card_y = info_y - 0.5 * cm - card_height
    for idx, (label, value, color_code) in enumerate(cards):
        x = 1.2 * cm + idx * (card_width + 0.6 * cm)
        c.saveState()
        c.setFillColor(colors.HexColor(color_code))
        c.roundRect(x, card_y, card_width, card_height, 8, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica", 10)
        c.drawString(x + 0.6 * cm, card_y + card_height - 0.9 * cm, label)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(x + 0.6 * cm, card_y + 0.8 * cm, str(value))
        c.restoreState()

    page = 1

    def new_page():
        nonlocal page, y
        footer(page)
        c.showPage()
        page += 1
        header()
        c.setFont("Helvetica", 9)
        y = height - 3 * cm
        return y

    def wrap_cell(text: str, font_name: str, font_size: int, width_pt: float):
        if text is None:
            return [""]
        clean = str(text).strip()
        if not clean:
            return [""]

        # Try to wrap using actual string width; fallback to textwrap for safety
        max_width = width_pt - 6  # padding left/right
        words = clean.split()
        lines = []
        current = ""
        for word in words:
            tentative = f"{current} {word}".strip()
            if tentative and pdfmetrics.stringWidth(tentative, font_name, font_size) <= max_width:
                current = tentative
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if not lines:
            lines = wrap(clean, 42) or [clean]
        return lines

    def draw_table(title, headers, rows, col_widths):
        nonlocal page, y
        if not rows:
            return
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(colors.HexColor("#212529"))
        c.drawString(1.2 * cm, y, title)
        y -= 0.7 * cm
        c.setFont("Helvetica", 9)

        header_height = 0.7 * cm
        table_left = 1.2 * cm
        table_width = sum(col_widths)

        def draw_header_bar():
            nonlocal y
            c.setFillColor(colors.HexColor("#003E6B"))
            c.roundRect(table_left - 0.1 * cm, y - header_height + 0.1 * cm, table_width + 0.2 * cm, header_height, 4, stroke=0, fill=1)
            c.setFillColor(colors.white)
            x = table_left
            for idx, txt in enumerate(headers):
                c.drawString(x + 4, y - header_height / 2 + 1, str(txt))
                x += col_widths[idx]
            y -= header_height + 0.15 * cm

        def draw_row(vals, row_index):
            nonlocal y
            font_name = "Helvetica"
            font_size = 9
            line_height = font_size + 3
            wrapped = []
            row_height = 0
            for i, v in enumerate(vals):
                lines = wrap_cell(v, font_name, font_size, col_widths[i])
                wrapped.append(lines)
                row_height = max(row_height, len(lines) * line_height + 6)

            if y - row_height < 2.2 * cm:
                new_page()
                c.setFont("Helvetica-Bold", 12)
                c.setFillColor(colors.HexColor("#212529"))
                c.drawString(1.2 * cm, y, f"{title} (suite)")
                y -= 0.7 * cm
                c.setFont("Helvetica", 9)
                draw_header_bar()

            bg_color = colors.HexColor("#F4F6FB") if row_index % 2 == 0 else colors.white
            c.setFillColor(bg_color)
            c.roundRect(table_left - 0.1 * cm, y - row_height + 0.15 * cm, table_width + 0.2 * cm, row_height, 2, stroke=0, fill=1)

            c.setFillColor(colors.HexColor("#2F2F2F"))
            x = table_left
            for idx, lines in enumerate(wrapped):
                line_y = y - 0.35 * cm
                for line in lines:
                    c.drawString(x + 4, line_y, line)
                    line_y -= line_height
                x += col_widths[idx]

            y -= row_height + 0.1 * cm

        draw_header_bar()
        for index, row in enumerate(rows):
            draw_row(row, index)

        y -= 0.6 * cm

    y = card_y - 0.8 * cm

    if parent_rows:
        parent_headers = [
            "Parent",
            "Chargé",
            "Véhicule",
            "Par",
            "Commentaire",
            "Dernière MAJ",
            "Créneaux",
        ]
        parent_widths = [2.8*cm, 1.4*cm, 2.6*cm, 2.2*cm, 4.0*cm, 3.0*cm, 4.0*cm]
        draw_table("Parents & chargement", parent_headers, parent_rows, parent_widths)

    detail_headers = [
        "Parent",
        "Sous-parent",
        "Nom",
        "Qté",
        "Statut",
        "Vérifié par",
        "Commentaire",
        "Date",
    ]
    detail_widths = [2.4*cm, 2.4*cm, 3.2*cm, 1.2*cm, 1.6*cm, 2.5*cm, 3.8*cm, 3.0*cm]
    detail_rows = [row[:8] for row in csv_rows[1:]]
    draw_table("Détails (extrait)", detail_headers, detail_rows, detail_widths)

    footer(page)
    c.showPage()
    c.save()
    return buf.getvalue()
