# app/auth/views.py — Authentification (JSON + Form fallback)
from flask import Blueprint, request, jsonify, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from ..models import User
from ..security import (
    client_identifier,
    current_login_rate_limiter,
    retry_after_seconds,
)

bp = Blueprint("auth", __name__)

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
        # Si c’est un formulaire, renvoie vers la page login avec un message minimal
        if request.form:
            return redirect(url_for("pages.login"))
        return jsonify(error="username and password required"), 400

    limiter = current_login_rate_limiter()
    client_id = client_identifier()
    blocked, blocked_until = limiter.is_blocked(client_id)
    if blocked:
        if request.form:
            return redirect(url_for("pages.login"))
        response = jsonify(error="Too many login attempts. Try again later.")
        retry_after = retry_after_seconds(blocked_until)
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
        return response, 429

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        blocked, blocked_until = limiter.register_failure(client_id)
        if request.form:
            return redirect(url_for("pages.login"))
        status = 429 if blocked else 401
        message = "Too many login attempts. Try again later." if blocked else "Bad credentials"
        response = jsonify(error=message)
        if blocked and blocked_until:
            retry_after = retry_after_seconds(blocked_until)
            if retry_after:
                response.headers["Retry-After"] = str(retry_after)
        return response, status
    if not user.is_active:
        limiter.register_failure(client_id)
        if request.form:
            return redirect(url_for("pages.login"))
        return jsonify(error="User disabled"), 403

    limiter.reset(client_id)

    login_user(user)

    # Si l’appel vient d’un formulaire HTML, on redirige vers le dashboard
    if request.form and not request.is_json:
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
