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
    return render_template('index.html')

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    username = data.get('username')
    join_room(room) # Join the socket network room [1]
    
    # 1. Initialize room if it doesn't exist
    if room not in rooms:
        rooms[room] = {'board': chess.Board(), 'players': {username: 'white'}, 'resigned': False}
        color = 'white'
    else:
        # 2. Check if they are a returning player (Auto-Rejoin)
        if username in rooms[room]['players']:
            color = rooms[room]['players'][username]
        # 3. If there is only 1 player, the new person becomes black
        elif len(rooms[room]['players']) == 1:
            color = 'black'
            rooms[room]['players'][username] = color
        # 4. NEW: If the room is full, they become a spectator!
        else:
            color = 'spectator'
            
    # Tell the user their assigned role
    emit('assigned_color', {'color': color}, room=request.sid)
    
    # Always emit the current board state and move history to the room
    current_board = rooms[room]['board']
    move_history = [move.uci() for move in current_board.move_stack]
    emit('board_state', {'fen': current_board.fen(), 'moves': move_history, 'result': None}, room=room)

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

@socketio.on('draw_offer')
def on_draw_offer(data):
    room = data.get('room')
    username = data.get('username')
    
    # Verify the user is actually playing in this room
    if room in rooms and username in rooms[room]['players']:
        # Broadcast the offer to the opponent
        emit('draw_requested', {'from_user': username}, room=room)

@socketio.on('draw_accept')
def on_draw_accept(data):
    room = data.get('room')
    
    if room in rooms:
        # We can reuse the 'resigned' flag to permanently lock the server board
        rooms[room]['resigned'] = True 
        
        board = rooms[room]['board']
        # Broadcast the agreed draw to both players so their screens update
        emit('board_state', {'fen': board.fen(), 'result': 'draw_agreed'}, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)