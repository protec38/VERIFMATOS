# app/sockets.py — Handlers Socket.IO (temps réel)
from flask_socketio import join_room, leave_room
from flask import request
from .models import EventShareLink

def room_for_event(event_id: int) -> str:
    return f"event-{event_id}"

def register_socketio_handlers(socketio):
    @socketio.on("join_event")
    def join(data):
        # data can provide event_id or token
        event_id = data.get("event_id")
        token = data.get("token")
        if not event_id and token:
            link = EventShareLink.query.filter_by(token=token, active=True).first()
            if link and link.event_id:
                event_id = link.event_id
        if not event_id:
            return
        join_room(room_for_event(int(event_id)))

    @socketio.on("leave_event")
    def leave(data):
        event_id = data.get("event_id")
        if not event_id:
            return
        leave_room(room_for_event(int(event_id)))

    @socketio.on("ping")
    def ping(data):
        socketio.emit("pong", {"echo": data})
