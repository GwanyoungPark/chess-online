import os
import secrets

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import chess

app = Flask(__name__)

# SECURITY FIX: the secret key used to be hardcoded in source. It's now read
# from an environment variable, with a random fallback so the app still runs
# out of the box locally. This app doesn't rely on persistent Flask sessions
# for gameplay, so a fresh random key on each restart has no effect on
# players -- if you want a stable key in production, set SECRET_KEY in your
# host's environment variables (e.g. Heroku config vars).
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PROPAGATE_EXCEPTIONS'] = True

# gevent is required here to match the gunicorn worker class in the Procfile.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# In-memory game rooms (no database -- resets on server restart, same as before).
# room_id -> {
#   'board': chess.Board(),
#   'players': {username: 'white' | 'black'},
#   'resigned': bool,
#   'result': 'checkmate' | 'stalemate' | 'white_resigned' | 'black_resigned'
#              | 'draw_agreed' | None
# }
rooms = {}

# Results that permanently end a game and get saved on the room.
GAME_OVER_RESULTS = {'checkmate', 'stalemate'}


def room_state(room_id, result=None):
    """Build the {fen, moves, result} payload broadcast to a room."""
    board = rooms[room_id]['board']
    return {
        'fen': board.fen(),
        'moves': [move.uci() for move in board.move_stack],
        'result': result,
    }


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('join')
def on_join(data):
    room = data.get('room')
    username = data.get('username')
    if not room or not username:
        return

    join_room(room)

    if room not in rooms:
        # First player in the room -- they play white.
        rooms[room] = {
            'board': chess.Board(),
            'players': {username: 'white'},
            'resigned': False,
            'result': None,
        }
        color = 'white'
    else:
        players = rooms[room]['players']
        if username in players:
            # Returning player (e.g. refreshed the page) -- give back their color.
            color = players[username]
        elif len(players) == 1:
            # Second player in the room -- they play black.
            color = 'black'
            players[username] = color
        else:
            # Room already has two players -- everyone else spectates.
            color = 'spectator'

    # Tell this client their role, then sync everyone in the room on the
    # current position (including a previously-saved result, if the game
    # already ended -- e.g. this is a refresh after checkmate).
    emit('assigned_color', {'color': color}, room=request.sid)
    emit('board_state', room_state(room, rooms[room]['result']), room=room)


@socketio.on('move')
def on_move(data):
    room = data.get('room')
    move_uci = data.get('move')
    if not room or not move_uci or room not in rooms:
        return

    if rooms[room]['resigned']:
        emit('invalid_move', room=request.sid)
        return

    board = rooms[room]['board']

    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        # Malformed move string (e.g. a tampered client).
        emit('invalid_move', room=request.sid)
        return

    if move not in board.legal_moves:
        emit('invalid_move', room=request.sid)
        return

    board.push(move)

    game_result = None
    if board.is_checkmate():
        game_result = 'checkmate'
    elif board.is_stalemate():
        game_result = 'stalemate'
    elif board.is_check():
        game_result = 'check'

    if game_result in GAME_OVER_RESULTS:
        rooms[room]['result'] = game_result

    emit('board_state', room_state(room, game_result), room=room)


@socketio.on('resign')
def on_resign(data):
    room = data.get('room')
    username = data.get('username')
    if not room or room not in rooms or username not in rooms[room]['players']:
        return

    player_color = rooms[room]['players'][username]
    game_result = 'white_resigned' if player_color == 'white' else 'black_resigned'

    rooms[room]['resigned'] = True
    rooms[room]['result'] = game_result

    emit('board_state', room_state(room, game_result), room=room)


@socketio.on('draw_offer')
def on_draw_offer(data):
    room = data.get('room')
    username = data.get('username')

    if room in rooms and username in rooms[room]['players']:
        emit('draw_requested', {'from_user': username}, room=room)


@socketio.on('draw_accept')
def on_draw_accept(data):
    room = data.get('room')
    if room not in rooms:
        return

    rooms[room]['resigned'] = True
    rooms[room]['result'] = 'draw_agreed'

    emit('board_state', room_state(room, 'draw_agreed'), room=room)


if __name__ == '__main__':
    socketio.run(app, debug=True)