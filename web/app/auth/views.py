# app/auth/views.py — Authentification (JSON + Form fallback)
from __future__ import annotations

import math
from typing import Optional
from urllib.parse import urlparse, urljoin

from flask import Blueprint, request, jsonify, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user

from .. import db
from ..models import User, AuditLog
from ..security import (
    client_identifier,
    current_login_rate_limiter,
    retry_after_seconds,
)

bp = Blueprint("auth", __name__)


def _ensure_audit_table() -> None:
    try:
        AuditLog.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()


def _log_login_attempt(
    *,
    username: str,
    success: bool,
    client_ip: str,
    user_id: Optional[int] = None,
    message: Optional[str] = None,
    blocked: bool = False,
    remaining_attempts: Optional[int] = None,
    retry_after: Optional[int] = None,
) -> None:
    try:
        _ensure_audit_table()
        entry = AuditLog(
            user_id=user_id if success else None,
            action="login.success" if success else "login.failure",
            meta={
                "username": username or None,
                "client_ip": client_ip,
                "status": "success" if success else "failure",
                "message": message,
                "blocked": bool(blocked),
                "remaining_attempts": remaining_attempts,
                "retry_after": retry_after,
            },
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _format_block_message(retry_after: int) -> str:
    if retry_after <= 0:
        return "Trop de tentatives. Réessaie dans quelques instants."
    minutes = retry_after / 60
    if minutes >= 1:
        minutes_int = max(1, math.ceil(minutes))
        suffix = "s" if minutes_int > 1 else ""
        return f"Trop de tentatives. Réessaie dans {minutes_int} minute{suffix}."
    seconds = max(1, int(retry_after))
    suffix = "s" if seconds > 1 else ""
    return f"Trop de tentatives. Réessaie dans {seconds} seconde{suffix}."


def _safe_redirect_target(target: str | None) -> str | None:
    if not target:
        return None

    try:
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
    except Exception:
        return None

    if test_url.scheme not in ("http", "https"):
        return None
    if test_url.netloc != ref_url.netloc:
        return None

    path = test_url.path or "/"
    if test_url.query:
        path = f"{path}?{test_url.query}"
    if test_url.fragment:
        path = f"{path}#{test_url.fragment}"
    return path


@bp.post("/login")
def login():
    # Tente JSON d’abord, sinon fallback sur les données de formulaire
    data = request.get_json(silent=True)
    if data:
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
    else:
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

    if not username or not password:
        message = "Nom d’utilisateur et mot de passe requis."
        if request.form:
            return redirect(url_for("pages.login", error=message))
        return jsonify(error=message), 400

    limiter = current_login_rate_limiter()
    client_id = client_identifier()
    blocked, blocked_until = limiter.is_blocked(client_id)
    if blocked:
        retry_after = retry_after_seconds(blocked_until)
        message = _format_block_message(retry_after)
        _log_login_attempt(
            username=username,
            success=False,
            client_ip=client_id,
            message=message,
            blocked=True,
            remaining_attempts=0,
            retry_after=retry_after,
        )
        if request.form:
            return redirect(url_for("pages.login", error=message))
        payload = {"error": message, "blocked": True, "remaining_attempts": 0}
        if retry_after:
            payload["retry_after"] = retry_after
        response = jsonify(payload)
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
        return response, 429

    user = User.query.filter_by(username=username).first()
    valid_password = bool(user and user.check_password(password))
    if not valid_password:
        blocked, blocked_until = limiter.register_failure(client_id)
        retry_after = retry_after_seconds(blocked_until) if blocked else None
        remaining = limiter.remaining_attempts(client_id)
        if blocked:
            message = _format_block_message(retry_after or 0)
        else:
            remaining_txt = f" Tentatives restantes : {remaining}." if remaining not in (None, 0) else ""
            message = "Nom d’utilisateur ou mot de passe incorrect." + remaining_txt
        _log_login_attempt(
            username=username,
            success=False,
            client_ip=client_id,
            message=message,
            blocked=blocked,
            remaining_attempts=remaining,
            retry_after=retry_after,
            user_id=user.id if user else None,
        )
        if request.form:
            return redirect(url_for("pages.login", error=message))
        status = 429 if blocked else 401
        payload = {
            "error": message,
            "blocked": blocked,
            "remaining_attempts": max(remaining or 0, 0),
        }
        if retry_after is not None:
            payload["retry_after"] = retry_after
        response = jsonify(payload)
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
        return response, status
    if not user.is_active:
        limiter.register_failure(client_id)
        message = "Compte désactivé. Contacte un administrateur."
        _log_login_attempt(
            username=username,
            success=False,
            client_ip=client_id,
            message=message,
            blocked=False,
            remaining_attempts=limiter.remaining_attempts(client_id),
            user_id=user.id,
        )
        if request.form:
            return redirect(url_for("pages.login", error=message))
        return jsonify(error=message), 403

    limiter.reset(client_id)

    login_user(user)

    _log_login_attempt(
        username=user.username,
        success=True,
        client_ip=client_id,
        user_id=user.id,
        message="Connexion réussie",
    )

    # Si l’appel vient d’un formulaire HTML, on redirige vers la cible souhaitée (ou le dashboard)
    if request.form and not request.is_json:
        next_url = request.form.get("next") or request.args.get("next")
        safe_target = _safe_redirect_target(next_url)
        if safe_target:
            return redirect(safe_target)
        return redirect(url_for("pages.dashboard"))

    # Sinon on reste en JSON
    return jsonify(ok=True, username=user.username, role=user.role.name)

@bp.post("/logout")
@login_required
def logout():
    logout_user()
    # Si formulaire -> retour login; si API -> JSON
    if "text/html" in (request.headers.get("Accept") or ""):
        return redirect(url_for("pages.login"))
    return jsonify(ok=True)

@bp.get("/me")
@login_required
def me():
    u = current_user
    return jsonify(id=u.id, username=u.username, role=u.role.name, is_active=u.is_active)
