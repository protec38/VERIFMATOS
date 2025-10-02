# app/sockets.py
from __future__ import annotations
from flask_socketio import join_room, leave_room
from flask import request

# IMPORTANT : on n'importe PAS socketio ici directement,
# on reçoit l'instance via register_socketio_handlers(sio)

EVENT_NAMESPACE = "/events"

def register_socketio_handlers(sio):
    def _setup_namespace(ns=None):
        emit_ns = ns or "/"

        @sio.on("connect", namespace=ns)
        def _connect():
            # Optionnel : on peut logger le SID
            # print("Socket connect:", request.sid)
            pass

        @sio.on("disconnect", namespace=ns)
        def _disconnect():
            # print("Socket disconnect:", request.sid)
            pass

        @sio.on("join_event", namespace=ns)
        def _join_event(data):
            """Place ce client dans la room de l'événement pour recevoir les updates."""
            try:
                event_id = int((data or {}).get("event_id"))
            except Exception:
                return
            room = f"event_{event_id}"
            join_room(room, namespace=ns)
            sio.emit(
                "event_update",
                {"type": "joined", "event_id": event_id},
                to=request.sid,
                namespace=emit_ns,
            )

        @sio.on("leave_event", namespace=ns)
        def _leave_event(data):
            try:
                event_id = int((data or {}).get("event_id"))
            except Exception:
                return
            room = f"event_{event_id}"
            leave_room(room, namespace=ns)

    _setup_namespace()
    if EVENT_NAMESPACE != "/":
        _setup_namespace(EVENT_NAMESPACE)
