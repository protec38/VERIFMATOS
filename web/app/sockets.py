# app/sockets.py
from __future__ import annotations
from flask_socketio import join_room, leave_room
from flask import request

# IMPORTANT : on n'importe PAS socketio ici directement,
# on reçoit l'instance via register_socketio_handlers(sio)

def register_socketio_handlers(sio):
    @sio.on("connect")
    def on_connect():
        # Optionnel : on peut logger le SID
        # print("Socket connect:", request.sid)
        # On peut envoyer un petit ack côté client si besoin
        pass

    @sio.on("disconnect")
    def on_disconnect():
        # print("Socket disconnect:", request.sid)
        pass

    @sio.on("join_event")
    def on_join_event(data):
        """
        data = {event_id: int}
        Place ce client dans la "room" de l'événement pour recevoir les updates.
        """
        try:
            event_id = int((data or {}).get("event_id"))
        except Exception:
            return
        room = f"event_{event_id}"
        join_room(room)
        # On peut retourner une info d’accusé
        sio.emit("event_update", {"type": "joined", "event_id": event_id}, room=request.sid)

    @sio.on("leave_event")
    def on_leave_event(data):
        try:
            event_id = int((data or {}).get("event_id"))
        except Exception:
            return
        room = f"event_{event_id}"
        leave_room(room)
