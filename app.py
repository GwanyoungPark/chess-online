from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import chess

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess-secret'
# Using gevent for async_mode as required by your deployment setup
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
app.config['PROPAGATE_EXCEPTIONS'] = True

# Store game rooms: { room_id: { board, players: {sid: color} } }
rooms = {}

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    
    # If the room doesn't exist, create it with a fresh board
    if room not in rooms:
        rooms[room] = {'board': chess.Board(), 'players': {}}
    
    # Assign colors to up to 2 players based on their session ID (request.sid)
    player_count = len(rooms[room]['players'])
    if player_count == 0:
        rooms[room]['players'][request.sid] = 'white'
        emit('assigned_color', {'color': 'white'})
    elif player_count == 1 and request.sid not in rooms[room]['players']:
        rooms[room]['players'][request.sid] = 'black'
        emit('assigned_color', {'color': 'black'})
    else:
        # Third person joins -> becomes a spectator. No color is assigned.
        pass
        
    # Emit the current board state to the person who just joined
    current_board = rooms[room]['board']
    emit('board_state', {'fen': current_board.fen(), 'result': None})

@socketio.on('move')
def on_move(data):
    room = data['room']
    move_uci = data['move']
    
    if room not in rooms:
        return
        
    board = rooms[room]['board']
    
    try:
        # Parse the move sent by the frontend
        move = chess.Move.from_uci(move_uci)
        
        # Validate if the move is strictly legal
        if move in board.legal_moves:
            board.push(move)
            
            # Check endgame states
            game_result = None
            if board.is_checkmate():
                game_result = 'checkmate'
            elif board.is_stalemate():
                game_result = 'stalemate'
            elif board.is_check():
                game_result = 'check'
                
            # Broadcast the valid move and game status to everyone in the room
            emit('board_state', {'fen': board.fen(), 'result': game_result}, room=room)
        else:
            # Tell the specific client their move was illegal so it snaps back
            emit('invalid_move', room=request.sid)
    except ValueError:
        # Catch errors if the move format was manipulated
        emit('invalid_move', room=request.sid)

if __name__ == '__main__':
    socketio.run(app, debug=True)