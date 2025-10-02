# app/reports/pdfgen.py — génération PDF (reportlab)
from __future__ import annotations
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm

def build_pdf(event, summary, csv_rows) -> bytes:
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

    header()
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.2*cm, height-3*cm, "Synthèse")
    c.setFont("Helvetica", 11)
    c.drawString(1.2*cm, height-3.7*cm, f"Total: {summary['total']}")
    c.drawString(6*cm, height-3.7*cm, f"OK: {summary['ok']}")
    c.drawString(9*cm, height-3.7*cm, f"Non conforme: {summary['not_ok']}")
    c.drawString(13*cm, height-3.7*cm, f"À faire: {summary['todo']}")

    y = height-4.6*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.2*cm, y, "Détails (extrait)")
    y -= 0.7*cm
    c.setFont("Helvetica", 9)
    # Table header
    headers = ["Parent", "Sous-parent", "Nom", "Qté", "Statut", "Vérifié par", "Commentaire", "Date"]
    colx = [1.2*cm, 4.2*cm, 7.2*cm, 11.0*cm, 12.5*cm, 14.5*cm, 1.2*cm, 1.2*cm]  # used incrementally
    colw = [3.0*cm, 3.0*cm, 3.8*cm, 1.5*cm, 1.8*cm, 4.5*cm, 9.5*cm, 3.0*cm]  # not fully strict

    def draw_row(vals, y):
        x = 1.2*cm
        max_h = 0.5*cm
        for i, v in enumerate(vals[:6]):  # keep table tighter (first 6 cols)
            c.drawString(x+2, y, str(v)[:32])
            x += [3.0*cm, 3.0*cm, 3.8*cm, 1.5*cm, 1.8*cm, 4.5*cm][i]
        return y-0.55*cm

    # draw header
    c.setFillColor(colors.HexColor("#F39200"))
    c.rect(1.1*cm, y-0.2*cm, width-2.2*cm, 0.5*cm, stroke=0, fill=1)
    c.setFillColor(colors.black)
    y -= 0.45*cm
    y = draw_row(headers, y)

    # draw up to ~30 rows per page
    count = 0
    for row in csv_rows[1:]:  # skip header
        if y < 2.5*cm:
            footer(1)
            c.showPage()
            header()
            y = height-3*cm
            c.setFont("Helvetica", 9)
            # redraw header
            c.setFillColor(colors.HexColor("#F39200"))
            c.rect(1.1*cm, y-0.2*cm, width-2.2*cm, 0.5*cm, stroke=0, fill=1)
            c.setFillColor(colors.black)
            y -= 0.45*cm
            y = draw_row(headers, y)
        y = draw_row(row, y)
        count += 1

    footer(1)
    c.showPage()
    c.save()
    return buf.getvalue()
