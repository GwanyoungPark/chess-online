// ---------- Cached DOM references ----------
const roomInputEl = document.getElementById('room-input');
const lobbyEl = document.getElementById('lobby');
const gameEl = document.getElementById('game');
const statusEl = document.getElementById('status');
const turnIndicatorEl = document.getElementById('turn-indicator');
const boardEl = document.getElementById('board');
const promotionMenuEl = document.getElementById('promotion-menu');
const moveTableEl = document.getElementById('move-table');
const moveListContainerEl = document.getElementById('move-list-container');

// ---------- Socket & game state ----------
const socket = io();
let board, game;
let myColor = null;
let roomId = null;
let isResigned = false;        // Locks the board once the game has ended by resignation/draw
let pendingPromotion = null;   // { source, target } while the promotion menu is open
let currentMoveOffset = 0;     // Which move we're viewing (for history navigation)
let isViewingHistory = false;  // True while looking at a past position
let selectedSquare = null;     // Currently tapped square, for tap-to-move

// Automatically generate (once) or retrieve the player's persistent ID.
let username = localStorage.getItem('chessPlayerId');
if (!username) {
  username = 'player_' + Math.random().toString(36).substr(2, 9);
  localStorage.setItem('chessPlayerId', username);
}

// If a room code is already in the URL (e.g. a shared link), auto-join.
const urlRoom = new URLSearchParams(window.location.search).get('room');
if (urlRoom) {
  roomInputEl.value = urlRoom;
  joinGame();
}

// True when it's the local player's turn to move.
function isMyTurn() {
  return (game.turn() === 'w' && myColor === 'white') ||
         (game.turn() === 'b' && myColor === 'black');
}

function joinGame() {
  roomId = roomInputEl.value.trim();
  if (!roomId) return alert('Enter a room code!');

  // Update the URL so a refresh remembers the room code.
  window.history.replaceState(null, '', '?room=' + roomId);

  socket.emit('join', { room: roomId, username: username });

  lobbyEl.classList.add('hidden');
  gameEl.classList.remove('hidden');
}

function resignGame() {
  if (!roomId) return;
  if (confirm('Are you sure you want to resign?')) {
    socket.emit('resign', { room: roomId, username: username });
  }
}

function offerDraw() {
  if (!roomId) return;
  if (confirm('Are you sure you want to offer a draw?')) {
    socket.emit('draw_offer', { room: roomId, username: username });
  }
}

function leaveRoom() {
  window.history.replaceState(null, '', window.location.pathname);
  window.location.reload();
}

function highlightSquare(squareEl) {
  clearHighlights();
  // Kept as direct inline styling (not a CSS class) so it can't be silently
  // overridden by chessboard.js's own .square-55d63 rules.
  squareEl.style.border = '3px solid #e94560';
  squareEl.style.boxSizing = 'border-box';
}

function clearHighlights() {
  document.querySelectorAll('.square-55d63').forEach(s => {
    s.style.border = '';
    s.style.boxSizing = '';
  });
}

socket.on('assigned_color', (data) => {
  myColor = data.color;
  const boardOrientation = (myColor === 'black') ? 'black' : 'white';

  statusEl.textContent = (myColor === 'spectator')
    ? '👁️ You are spectating'
    : `You are playing as ${myColor}`;

  game = new Chess();
  board = Chessboard('board', {
    draggable: (myColor !== 'spectator'),
    position: 'start',
    orientation: boardOrientation,
    onDragStart,
    onDrop,
    onSnapEnd,
    pieceTheme: 'https://raw.githubusercontent.com/oakmac/chessboardjs/master/website/img/chesspieces/wikipedia/{piece}.png'
  });

  // Safely attach the tap-to-move listener (only once).
  if (!boardEl.dataset.tapEnabled) {
    boardEl.dataset.tapEnabled = 'true';

    boardEl.addEventListener('click', function (e) {
      if (game.game_over() || isResigned || isViewingHistory || myColor === 'spectator') return;
      if (!isMyTurn()) return;

      const squareEl = e.target.closest('.square-55d63');
      if (!squareEl) return;

      const square = squareEl.getAttribute('data-square');
      const piece = game.get(square);

      if (selectedSquare === null) {
        if (piece && piece.color === myColor.charAt(0)) {
          selectedSquare = square;
          highlightSquare(squareEl);
        }
      } else {
        if (piece && piece.color === myColor.charAt(0)) {
          selectedSquare = square;
          highlightSquare(squareEl);
          return;
        }

        onDrop(selectedSquare, square);
        selectedSquare = null;
        clearHighlights();
      }
    });
  }
});

socket.on('board_state', (data) => {
  // Rebuild the game history from the backend's authoritative move list.
  game = new Chess();
  if (data.moves) {
    data.moves.forEach(m => {
      // chess.js cleanly processes standard UCI moves (e.g. 'e2e4' or 'e7e8q').
      game.move({
        from: m.substring(0, 2),
        to: m.substring(2, 4),
        promotion: m.length > 4 ? m[4] : undefined
      });
    });
  }

  // If we're looking at the live position, snap the pieces to the current state.
  if (!isViewingHistory) {
    board.position(game.fen());
    currentMoveOffset = game.history().length;
  }

  updateMoveList();

  const myTurn = isMyTurn();
  turnIndicatorEl.textContent = myTurn ? '🟢 Your turn' : "⏳ Opponent's turn";

  if (data.result === 'checkmate') {
    statusEl.textContent = myTurn ? '😞 You lost! Checkmate.' : '🏆 You won! Checkmate!';
  } else if (data.result === 'stalemate') {
    statusEl.textContent = '🤝 Stalemate! Draw.';
  } else if (data.result === 'check') {
    turnIndicatorEl.textContent += ' ⚠️ Check!';
  } else if (data.result === 'white_resigned') {
    isResigned = true;
    statusEl.textContent = 'White resigned! Black wins! 🎉';
  } else if (data.result === 'black_resigned') {
    isResigned = true;
    statusEl.textContent = 'Black resigned! White wins! 🎉';
  } else if (data.result === 'draw_agreed') {
    isResigned = true;
    statusEl.textContent = '🤝 Game drawn by mutual agreement.';
  }
});

socket.on('invalid_move', () => {
  board.position(game.fen()); // Snap back
});

// NOTE: this used to be registered twice in the original file, which popped
// the "accept draw?" confirmation dialog twice for the receiving player.
// It's now registered once.
socket.on('draw_requested', (data) => {
  // Make sure the person who clicked "offer" doesn't get asked themselves.
  if (data.from_user !== username) {
    if (confirm('Your opponent has offered a draw. Do you accept?')) {
      socket.emit('draw_accept', { room: roomId });
    }
  }
});

function onDragStart(source, piece) {
  if (game.game_over() || isResigned || isViewingHistory) return false;
  if (!isMyTurn()) return false;
  if (myColor === 'white' && piece.startsWith('b')) return false;
  if (myColor === 'black' && piece.startsWith('w')) return false;
}

function onDrop(source, target) {
  if (game.game_over() || isResigned || isViewingHistory) return 'snapback';

  const piece = game.get(source);

  // 1. Detect pawn promotion.
  if (piece && piece.type === 'p') {
    const isWhitePromotion = (piece.color === 'w' && target.charAt(1) === '8');
    const isBlackPromotion = (piece.color === 'b' && target.charAt(1) === '1');

    if (isWhitePromotion || isBlackPromotion) {
      // Check the move is actually legal first (e.g. not blocked).
      const tempMove = game.move({ from: source, to: target, promotion: 'q' });
      if (tempMove === null) return 'snapback';
      game.undo(); // Undo -- we only wanted to verify legality.

      pendingPromotion = { source: source, target: target };
      promotionMenuEl.style.display = 'block';

      // Visually snap the pawn back while we wait for the user's choice.
      return 'snapback';
    }
  }

  // 2. Normal move processing.
  const move = game.move({ from: source, to: target, promotion: 'q' });
  if (move === null) return 'snapback';

  socket.emit('move', {
    room: roomId,
    username: username,
    move: move.from + move.to + (move.promotion || '')
  });
}

function choosePromotion(pieceType) {
  if (!pendingPromotion) return;

  const move = game.move({
    from: pendingPromotion.source,
    to: pendingPromotion.target,
    promotion: pieceType
  });

  if (move) {
    socket.emit('move', {
      room: roomId,
      username: username,
      move: move.from + move.to + pieceType
    });
  }

  promotionMenuEl.style.display = 'none';
  pendingPromotion = null;
}

function cancelPromotion() {
  promotionMenuEl.style.display = 'none';
  pendingPromotion = null;
}

function onSnapEnd() {
  board.position(game.fen());
}

function updateMoveList() {
  const history = game.history(); // e.g. ['e4', 'e5', 'Nf3']
  const activeIndex = currentMoveOffset - 1; // Move currently being viewed, if any
  const rows = [];

  for (let i = 0; i < history.length; i += 2) {
    const moveNum = (i / 2) + 1;
    const whiteMove = history[i];
    const blackMove = history[i + 1] || '';
    const whiteClass = (activeIndex === i) ? 'move-white active-move' : 'move-white';
    const blackClass = (activeIndex === i + 1) ? 'move-black active-move' : 'move-black';

    rows.push(
      '<tr>' +
        `<td class="move-num">${moveNum}.</td>` +
        `<td class="${whiteClass}">${whiteMove}</td>` +
        `<td class="${blackClass}">${blackMove}</td>` +
      '</tr>'
    );
  }

  // Build the whole table body in one string and write it once, rather than
  // repeatedly appending to innerHTML in the loop (each += re-parses the
  // entire table).
  moveTableEl.innerHTML = rows.join('');

  // Auto-scroll the move list to the bottom, unless viewing history.
  if (!isViewingHistory) {
    moveListContainerEl.scrollTop = moveListContainerEl.scrollHeight;
  }
}

function navigateHistory(step) {
  const history = game.history();
  currentMoveOffset += step;

  if (currentMoveOffset < 0) currentMoveOffset = 0; // Don't go before move 0

  if (currentMoveOffset >= history.length) {
    // Back to the live position.
    currentMoveOffset = history.length;
    isViewingHistory = false;
    board.position(game.fen());
  } else {
    // Looking at the past: build a temporary board up to that move.
    isViewingHistory = true;
    let tempGame = new Chess();
    for (let i = 0; i < currentMoveOffset; i++) {
      tempGame.move(history[i]);
    }
    board.position(tempGame.fen());
  }
  updateMoveList();
}