"""A small deterministic chess engine, used to drive full games in simulation.

Stockfish is deliberately not a dependency. The simulator track needs a mover
that is reproducible run to run — the same position must always produce the
same ranked move list, so a failed game can be replayed exactly — and it needs
to rank *all* legal moves rather than return one best move, because the
manipulator rejects moves that are legal but mechanically unreachable and asks
for the next candidate.

Strength is not the point. Alpha-beta over material plus piece-square tables at
a shallow depth plays coherent chess, which is all the arm needs to have
something real to do.
"""

from __future__ import annotations

import chess


PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Piece-square tables from White's point of view, rank 1 first.
_PAWN = (
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10,-20,-20, 10, 10,  5,
     5, -5,-10,  0,  0,-10, -5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5,  5, 10, 25, 25, 10,  5,  5,
    10, 10, 20, 30, 30, 20, 10, 10,
    50, 50, 50, 50, 50, 50, 50, 50,
     0,  0,  0,  0,  0,  0,  0,  0,
)
_KNIGHT = (
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
)
_BISHOP = (
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
)
_ROOK = (
     0,  0,  5, 10, 10,  5,  0,  0,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     5, 10, 10, 10, 10, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
)
_QUEEN = (
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -10,  5,  5,  5,  5,  5,  0,-10,
      0,  0,  5,  5,  5,  5,  0, -5,
     -5,  0,  5,  5,  5,  5,  0, -5,
    -10,  0,  5,  5,  5,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
)
_KING = (
     20, 30, 10,  0,  0, 10, 30, 20,
     20, 20,  0,  0,  0,  0, 20, 20,
    -10,-20,-20,-20,-20,-20,-20,-10,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
)
PIECE_SQUARE = {
    chess.PAWN: _PAWN,
    chess.KNIGHT: _KNIGHT,
    chess.BISHOP: _BISHOP,
    chess.ROOK: _ROOK,
    chess.QUEEN: _QUEEN,
    chess.KING: _KING,
}

MATE_SCORE = 100_000


def evaluate(board: chess.Board) -> int:
    """Score the position in centipawns from the side-to-move's perspective."""

    if board.is_checkmate():
        return -MATE_SCORE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0
    for square, piece in board.piece_map().items():
        table_index = square if piece.color == chess.WHITE else chess.square_mirror(square)
        value = PIECE_VALUE[piece.piece_type] + PIECE_SQUARE[piece.piece_type][table_index]
        score += value if piece.color == chess.WHITE else -value
    return score if board.turn == chess.WHITE else -score


def _ordering_key(board: chess.Board, move: chess.Move) -> tuple:
    """Cheap move ordering: captures and promotions first, then a stable tiebreak."""

    victim = board.piece_at(move.to_square)
    gain = PIECE_VALUE[victim.piece_type] if victim else 0
    if move.promotion:
        gain += PIECE_VALUE[move.promotion]
    return (-gain, move.uci())


def _negamax(board: chess.Board, depth: int, alpha: int, beta: int) -> int:
    if depth == 0 or board.is_game_over():
        return evaluate(board)
    best = -MATE_SCORE
    for move in sorted(board.legal_moves, key=lambda m: _ordering_key(board, m)):
        board.push(move)
        try:
            score = -_negamax(board, depth - 1, -beta, -alpha)
        finally:
            board.pop()
        if score > best:
            best = score
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    return best


def rank_moves(board: chess.Board, depth: int = 2) -> list[chess.Move]:
    """Return every legal move, best first.

    The full ranked list is the contract, not just the best move: the caller
    walks it until it finds one the arm can physically execute. Ties break on
    UCI text so the ordering is stable across runs and machines.
    """

    scored: list[tuple[int, str, chess.Move]] = []
    for move in board.legal_moves:
        board.push(move)
        try:
            score = -_negamax(board, depth - 1, -MATE_SCORE, MATE_SCORE)
        finally:
            board.pop()
        scored.append((-score, move.uci(), move))
    scored.sort()
    return [move for _, _, move in scored]


def best_move(board: chess.Board, depth: int = 2) -> chess.Move | None:
    ranked = rank_moves(board, depth)
    return ranked[0] if ranked else None
