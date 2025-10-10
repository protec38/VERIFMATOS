# app/reports/pdfgen.py — génération PDF (reportlab)
from __future__ import annotations
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm


def build_pdf(event, summary, csv_rows, parent_rows=None) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    def header():
        c.setFillColor(colors.HexColor("#003E6B"))
        c.rect(0, height-2*cm, width, 2*cm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1.2*cm, height-1.2*cm, "Préparation Matériel — Rapport")
        c.setFont("Helvetica", 10)
        c.drawRightString(width-1.2*cm, height-1.2*cm, f"Événement: {event.name} | Date: {event.date or '-'}")

    def footer(page):
        c.setStrokeColor(colors.HexColor("#EEEEEE"))
        c.line(1*cm, 1.5*cm, width-1*cm, 1.5*cm)
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawRightString(width-1.2*cm, 1.0*cm, f"Page {page}")

    parent_rows = parent_rows or []

    header()
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.2*cm, height-3*cm, "Synthèse")
    c.setFont("Helvetica", 11)
    c.drawString(1.2*cm, height-3.7*cm, f"Total: {summary['total']}")
    c.drawString(6*cm, height-3.7*cm, f"OK: {summary['ok']}")
    c.drawString(9*cm, height-3.7*cm, f"Non conforme: {summary['not_ok']}")
    c.drawString(13*cm, height-3.7*cm, f"À faire: {summary['todo']}")

    page = 1

    def new_page():
        nonlocal page, y
        footer(page)
        c.showPage()
        page += 1
        header()
        c.setFont("Helvetica", 9)
        y = height-3*cm
        return y

    def draw_table(title, headers, rows, col_widths):
        nonlocal page, y
        if not rows:
            return
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1.2*cm, y, title)
        y -= 0.6*cm
        c.setFont("Helvetica", 9)

        def draw_header_bar():
            nonlocal y
            c.setFillColor(colors.HexColor("#F39200"))
            c.rect(1.1*cm, y-0.2*cm, sum(col_widths)+0.2*cm, 0.5*cm, stroke=0, fill=1)
            c.setFillColor(colors.black)
            y -= 0.35*cm
            draw_row(headers)

        def draw_row(vals):
            nonlocal y
            x = 1.2*cm
            for i, v in enumerate(vals):
                txt = str(v) if v is not None else ""
                c.drawString(x+2, y, txt[:36])
                x += col_widths[i]
            y -= 0.55*cm

        draw_header_bar()
        for row in rows:
            if y < 2.5*cm:
                new_page()
                c.setFont("Helvetica-Bold", 12)
                c.drawString(1.2*cm, y, f"{title} (suite)")
                y -= 0.6*cm
                c.setFont("Helvetica", 9)
                draw_header_bar()
            draw_row(row)

        y -= 0.4*cm

    y = height-4.6*cm

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
