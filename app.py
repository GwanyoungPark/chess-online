from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import chess

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
app.config['PROPAGATE_EXCEPTIONS'] = True

# Store game rooms: { room_id: { board, players } }
rooms = {}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)

    if room not in rooms:
        rooms[room] = {
            'board': chess.Board(),
            'players': []
        }

    game = rooms[room]
    sid = request.sid

    if sid not in game['players']:
        game['players'].append(sid)

    # Assign color based on join order
    if game['players'].index(sid) == 0:
        color = 'white'
    else:
        color = 'black'

    emit('assigned_color', {'color': color})
    emit('board_state', {'fen': game['board'].fen()}, to=room)

@socketio.on('move')
def on_move(data):
    room = data['room']
    move_uci = data['move']

    if room not in rooms:
        return

    game = rooms[room]
    board = game['board']

    try:
        move = chess.Move.from_uci(move_uci)
        if move in board.legal_moves:
            board.push(move)
            result = None
            if board.is_checkmate():
                result = 'checkmate'
            elif board.is_stalemate():
                result = 'stalemate'
            elif board.is_check():
                result = 'check'

            emit('board_state', {
                'fen': board.fen(),
                'last_move': move_uci,
                'result': result
            }, to=room)
        else:
            emit('invalid_move', {'move': move_uci})
    except Exception as e:
        emit('error', {'message': str(e)})

if __name__ == '__main__':
    socketio.run(app, debug=True)