from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import chess
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess-secret'
# Using gevent for async_mode as required by your deployment setup
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
app.config['PROPAGATE_EXCEPTIONS'] = True

# Store game rooms: { room_id: { board, players: {sid: color} } }
rooms = {}

@app.route('/')
def index():
    # Load the patch notes from the JSON file
    notes = []
    if os.path.exists('patch_notes.json'):
        with open('patch_notes.json', 'r') as file:
            notes = json.load(file)
            
    # Send the notes data to index.html using Jinja2
    return render_template('index.html', patch_notes=notes)

@socketio.on('join')
def on_join(data):
    room = data['room']
    username = data.get('username')
    join_room(room)
    
    # If the room doesn't exist, create it with a fresh board and a resigned tracker
    if room not in rooms:
        rooms[room] = {'board': chess.Board(), 'players': {}, 'resigned': False}
    
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
        
    # Always emit the current board state and move history
    current_board = rooms[room]['board']
    move_history = [move.uci() for move in current_board.move_stack] # Get the move list
    emit('board_state', {'fen': current_board.fen(), 'moves': move_history, 'result': None})


@socketio.on('move')
def on_move(data):
    room = data['room']
    move_uci = data['move']
    
    if room not in rooms:
        return
        
    # Reject the move if someone has already resigned
    if rooms[room].get('resigned'):
        emit('invalid_move', room=request.sid)
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
                
            # Broadcast the valid move, game status, and history to everyone
            move_history = [move.uci() for move in board.move_stack] # Get the move list
            emit('board_state', {'fen': board.fen(), 'moves': move_history, 'result': game_result}, room=room)

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
    
    # Lock the room on the server
    rooms[room]['resigned'] = True 

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