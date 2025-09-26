# app/sockets.py
from __future__ import annotations
from flask import request
from flask_socketio import join_room, leave_room, emit

def register_socketio_handlers(socketio):
    @socketio.on("connect")
    def on_connect():
        try:
            emit("connected", {"sid": request.sid})
        except Exception:
            pass

    @socketio.on("join_event")
    def on_join_event(data):
        try:
            event_id = int((data or {}).get("event_id") or 0)
        except Exception:
            event_id = 0
        if not event_id:
            return
        room = f"event_{event_id}"
        join_room(room)
        # notifie les autres (optionnel)
        try:
            emit("event_update",
                 {"type": "presence", "event_id": event_id, "sid": request.sid},
                 room=room, include_self=False)
        except Exception:
            pass

    @socketio.on("leave_event")
    def on_leave_event(data):
        try:
            event_id = int((data or {}).get("event_id") or 0)
        except Exception:
            event_id = 0
        if not event_id:
            return
        room = f"event_{event_id}"
        try:
            leave_room(room)
        except Exception:
            pass

    @socketio.on("disconnect")
    def on_disconnect():
        # rien de spécial
        pass
