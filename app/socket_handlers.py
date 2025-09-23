from flask_socketio import join_room, leave_room
from flask import request
from .extensions import socketio

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        socketio.emit('joined', {'room': room}, to=room)
