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
    username = data.get('username')
    join_room(room)
    
    # If the room doesn't exist, create it with a fresh board [1]
    if room not in rooms:
        rooms[room] = {'board': chess.Board(), 'players': {}}
    
    players = rooms[room]['players']
    
    # 1. Check if this is a returning player who just refreshed
    if username in players:
        # Re-assign them their original color!
        emit('assigned_color', {'color': players[username]})
        
    # 2. If it is a new player, and the room is empty
    elif len(players) == 0:
        players[username] = 'white'
        emit('assigned_color', {'color': 'white'})
        
    # 3. If it is a new player, and there is one person in the room
    elif len(players) == 1:
        players[username] = 'black'
        emit('assigned_color', {'color': 'black'})
        
    # 4. Third person joins -> spectator (no color assigned)
    else:
        pass
        
    # Always emit the current board state so the refreshed player can see the pieces
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

@socketio.on('resign')
def on_resign(data):
    room = data.get('room')
    username = data.get('username')
    
    # 1. Verify the room exists and the user is actually a registered player in it
    if room not in rooms or username not in rooms[room]['players']:
        return
        
    player_color = rooms[room]['players'][username]
    board = rooms[room]['board']
    
    # 2. Determine the endgame status based on who resigned
    if player_color == 'white':
        game_result = 'white_resigned'
    else:
        game_result = 'black_resigned'
        
    # 3. Broadcast the resignation result to both players so their screens update
    emit('board_state', {'fen': board.fen(), 'result': game_result}, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)