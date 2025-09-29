# app/reports/views.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime
import csv
import io

from flask import Blueprint, abort, make_response, jsonify
from flask_login import login_required, current_user

from .. import db
from ..models import Event, Role
from .utils import compute_summary, rows_for_csv  # build_event_tree est ré-exporté si besoin

bp = Blueprint("reports", __name__)


# -------------------- Helpers sécurité --------------------
def _require_can_view_event(ev: Event) -> None:
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)


# -------------------- Helpers format --------------------
def _fmt_ts(ts: Optional[datetime]) -> str:
    if not ts:
        return ""
    # format lisible
    return ts.strftime("%Y-%m-%d %H:%M")

def _esc_pdf_text(s: str) -> str:
    """Échappe le texte pour un contenu PDF ( (), \ )."""
    return (
        (s or "")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )

def _chunk_lines(lines: List[str], per_page: int) -> List[List[str]]:
    out: List[List[str]] = []
    for i in range(0, len(lines), per_page):
        out.append(lines[i:i+per_page])
    return out


# -------------------- Générateur PDF « pur Python » --------------------
def _make_simple_pdf(title: str, pages: List[List[str]]) -> bytes:
    """
    Construit un PDF minimal, multi-pages, avec police standard Helvetica.
    Chaque page est une liste de lignes de texte.
    """
    # Indices des objets:
    # 1: Font (Helvetica)
    # 2..N: Streams de contenu (autant que de pages)
    # PAGES: l'objet /Pages
    # puis Catalog
    objects: List[bytes] = []
    xref_offsets: List[int] = []

    def add_obj(obj_text: bytes) -> int:
        """Ajoute un objet, retourne son numéro (1-indexed)."""
        xref_offsets.append(len(pdf))
        objects.append(obj_text)
        return len(objects)

    # Début PDF
    pdf_parts: List[bytes] = []
    pdf_parts.append(b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")
    pdf = b"".join(pdf_parts)

    # 1) Font
    font_obj_num = add_obj(
        b"1 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        b"endobj\n"
    )

    page_obj_nums: List[int] = []
    content_obj_nums: List[int] = []

    # Mise en page
    # A4 portrait: 595 x 842
    page_w, page_h = 595, 842
    left = 50
    top_first = 800   # y de départ de la zone de texte
    top_other = 812   # on remonte un poil sur les autres pages
    line_height = 14

    for pi, lines in enumerate(pages, start=1):
        y0 = top_first if pi == 1 else top_other

        # Construit le contenu texte PDF
        stream_lines: List[str] = []
        stream_lines.append("BT")
        stream_lines.append("/F1 12 Tf")
        stream_lines.append("1 0 0 1 0 0 Tm")  # matrice identité
        stream_lines.append(f"{left} {y0} Td")
        stream_lines.append(f"{line_height} TL")

        if pi == 1:
            # Titre en gras "visuel" (on reste en Helvetica 12, juste une ligne dédiée)
            stream_lines.append(f"({_esc_pdf_text(title)}) Tj")
            stream_lines.append("T*")

        for ln in lines:
            stream_lines.append(f"({_esc_pdf_text(ln)}) Tj")
            stream_lines.append("T*")

        stream_lines.append("ET")
        stream_text = "\n".join(stream_lines).encode("latin-1", "ignore")

        content = (
            b"<< /Length " + str(len(stream_text)).encode() + b" >>\n"
            b"stream\n" + stream_text + b"\nendstream\n"
        )
        content_obj_num = add_obj(
            f"{len(objects)+1} 0 obj\n".encode() + content + b"endobj\n"
        )
        content_obj_nums.append(content_obj_num)

        page_obj_num = add_obj(
            f"{len(objects)+1} 0 obj\n".encode()
            + (
                b"<< /Type /Page"
                b" /Parent PAGES 0 R"
                b" /MediaBox [0 0 595 842]"
                b" /Resources << /Font << /F1 1 0 R >> >>"
                b" /Contents " + f"{content_obj_num} 0 R".encode() +
                b" >>\nendobj\n"
            )
        )
        page_obj_nums.append(page_obj_num)

    # /Pages
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    pages_obj_num = add_obj(
        f"{len(objects)+1} 0 obj\n".encode()
        + (
            b"<< /Type /Pages"
            b" /Count " + str(len(page_obj_nums)).encode() +
            b" /Kids [" + kids.encode() + b"]"
            b" >>\nendobj\n"
        )
    )

    # Remplace le parent PAGES dans chaque page (on a utilisé un placeholder "PAGES 0 R")
    fixed_objects: List[bytes] = []
    for obj in objects:
        fixed_objects.append(obj.replace(b"PAGES 0 R", f"{pages_obj_num} 0 R".encode()))
    objects = fixed_objects

    # Catalog
    catalog_obj_num = add_obj(
        f"{len(objects)+1} 0 obj\n".encode()
        + (b"<< /Type /Catalog /Pages " + f"{pages_obj_num} 0 R".encode() + b" >>\nendobj\n")
    )

    # Concaténation finale avec xref
    # On reconstruit le flux: header + objets avec offsets + xref + trailer
    body = b""
    xref_offsets = []
    # recalcul des offsets en concaténant dans l'ordre
    offset = len(pdf)
    objs_serialized: List[bytes] = []
    for obj in objects:
        xref_offsets.append(offset)
        objs_serialized.append(obj)
        offset += len(obj)
    body = b"".join(objs_serialized)

    # xref
    xref_start = len(pdf) + len(body)
    xref = ["xref", f"0 {len(objects)+1}", "0000000000 65535 f "]
    for off in xref_offsets:
        xref.append(f"{off:010d} 00000 n ")
    xref_bytes = ("\n".join(xref) + "\n").encode()

    trailer = (
        b"trailer\n<< /Size " + str(len(objects)+1).encode()
        + b" /Root " + f"{catalog_obj_num} 0 R".encode()
        + b" >>\nstartxref\n" + str(xref_start).encode() + b"\n%%EOF\n"
    )

    return pdf + body + xref_bytes + trailer


# -------------------- Routes --------------------
@bp.get("/reports/event/<int:event_id>/summary")
@login_required
def event_summary(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    return jsonify(compute_summary(event_id))


@bp.get("/reports/event/<int:event_id>/csv")
@login_required
def event_csv(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)

    rows = rows_for_csv(event_id)

    si = io.StringIO()
    writer = csv.writer(si, delimiter=";")
    writer.writerow(
        ["node_id", "path", "name", "type", "quantity", "status", "verifier", "timestamp", "vehicle"]
    )
    for r in rows:
        writer.writerow([
            r.get("node_id", ""),
            r.get("path", ""),
            r.get("name", ""),
            r.get("type", ""),
            r.get("quantity", ""),
            r.get("status", "") or "",
            r.get("verifier", "") or "",
            _fmt_ts(r.get("timestamp")),
            r.get("vehicle", "") or "",
        ])

    out = make_response(si.getvalue())
    out.headers["Content-Type"] = "text/csv; charset=utf-8"
    out.headers["Content-Disposition"] = f'attachment; filename="event_{event_id}.csv"'
    return out


@bp.get("/reports/event/<int:event_id>/pdf")
@login_required
def event_pdf(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)

    summary = compute_summary(event_id)
    rows = rows_for_csv(event_id)

    title = f"Événement #{event_id} — {ev.name or ''}"
    lines: List[str] = []

    # Totaux
    totals = summary.get("totals", {})
    lines.append(f"Date: {ev.date or '-'}")
    lines.append(
        f"Totaux: {totals.get('ok', 0)} OK / {totals.get('bad', 0)} Non conformes / {totals.get('wait', 0)} En attente "
        f"(total {totals.get('total', 0)})"
    )
    lines.append("")

    # Parents chargés (si présents)
    parents = summary.get("parents", [])
    if parents:
        lines.append("Parents / chargement véhicule :")
        for p in parents:
            lab = p["name"]
            if p.get("charged") and p.get("vehicle"):
                lines.append(f"  - {lab}: CHARGÉ dans véhicule '{p['vehicle']}'")
            elif p.get("charged"):
                lines.append(f"  - {lab}: CHARGÉ")
            else:
                lines.append(f"  - {lab}: non chargé")
        lines.append("")

    # Lignes d’items (chemin | nom | qté | statut | vérificateur | date | véhicule)
    lines.append("Détails des items verifiés :")
    lines.append("chemin | nom | qt | statut | vérificateur | date | véhicule")
    for r in rows:
        if (r.get("type") or "").upper() != "ITEM":
            continue
        st = r.get("status") or "-"
        by = r.get("verifier") or "-"
        ts = _fmt_ts(r.get("timestamp"))
        veh = r.get("vehicle") or "-"
        q = r.get("quantity") if r.get("quantity") is not None else "-"
        lines.append(f"{r.get('path','-')} | {r.get('name','-')} | {q} | {st} | {by} | {ts} | {veh}")

    # Pagination très simple ~45 lignes par page
    pages = _chunk_lines(lines, per_page=45)
    pdf_bytes = _make_simple_pdf(title, pages)

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="event_{event_id}.pdf"'
    return resp
