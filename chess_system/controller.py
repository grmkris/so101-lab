"""python-chess orchestration with physical verification before state commit."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable

from .backend import ChessBackend
from .geometry import FILES, RANKS, load_geometry
from .model import ManipulationResult, MovePlan, MoveStep, ResultStatus
from .verification import ALL_SQUARES, verify_occupancy

try:
    import chess
except ImportError:  # pragma: no cover - exercised by the helpful runtime error
    chess = None


PromotionHandler = Callable[[str, str], bool]


def _require_python_chess():
    if chess is None:
        raise RuntimeError("python-chess is required: install the chess_system runtime dependencies")


def occupancy_from_board(board) -> dict[str, bool]:
    _require_python_chess()
    return {square: board.piece_at(chess.parse_square(square)) is not None for square in ALL_SQUARES}


def plan_move(board, move, move_id: str | None = None) -> MovePlan:
    """Expand one legal python-chess move into manipulation steps.

    Captures are removed before the moving piece is touched. Castling moves the
    king first and rook second. Promotion deliberately pauses for an operator
    swap after the pawn reaches its destination.
    """

    _require_python_chess()
    if move not in board.legal_moves:
        raise ValueError(f"illegal move in current position: {move.uci()}")

    source = chess.square_name(move.from_square)
    target = chess.square_name(move.to_square)
    mover = board.piece_at(move.from_square)
    if mover is None:
        raise ValueError(f"source square {source} is empty")

    steps: list[MoveStep] = []
    if board.is_en_passant(move):
        capture_index = move.to_square - 8 if mover.color == chess.WHITE else move.to_square + 8
        capture_square = chess.square_name(capture_index)
        captured = board.piece_at(capture_index)
        if captured is None:
            raise ValueError("en-passant capture square is unexpectedly empty")
        steps.append(
            MoveStep(
                "capture",
                source=capture_square,
                capture_bin="white" if captured.color == chess.WHITE else "black",
                metadata={"en_passant": True},
            )
        )
    elif board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured is None:
            raise ValueError("capture target is unexpectedly empty")
        steps.append(
            MoveStep(
                "capture",
                source=target,
                capture_bin="white" if captured.color == chess.WHITE else "black",
            )
        )

    steps.append(MoveStep("move", source=source, target=target))

    if board.is_castling(move):
        if chess.square_file(move.to_square) > chess.square_file(move.from_square):
            rook_source = "h1" if mover.color == chess.WHITE else "h8"
            rook_target = "f1" if mover.color == chess.WHITE else "f8"
        else:
            rook_source = "a1" if mover.color == chess.WHITE else "a8"
            rook_target = "d1" if mover.color == chess.WHITE else "d8"
        steps.append(MoveStep("castle_rook", source=rook_source, target=rook_target))

    if move.promotion:
        steps.append(
            MoveStep(
                "promotion_pause",
                source=target,
                target=target,
                metadata={"piece_type": chess.piece_name(move.promotion)},
            )
        )

    before = occupancy_from_board(board)
    after_board = copy.deepcopy(board)
    after_board.push(move)
    return MovePlan(
        move_id=move_id or uuid.uuid4().hex,
        uci=move.uci(),
        steps=tuple(steps),
        occupancy_before=before,
        occupancy_after=occupancy_from_board(after_board),
        expected_fen_after=after_board.fen(),
    )


class ChessController:
    def __init__(self, backend: ChessBackend, board=None, promotion_handler: PromotionHandler | None = None):
        _require_python_chess()
        self.backend = backend
        self.board = board or chess.Board()
        self.promotion_handler = promotion_handler
        self.geometry = load_geometry()

    def execute_uci(self, uci: str) -> ManipulationResult:
        move = chess.Move.from_uci(uci)
        plan = plan_move(self.board, move)
        translation, rotation = self.backend.board_pose_error()
        limits = self.geometry.raw["validation"]
        if (
            translation > limits["board_translation_abort"]
            or abs(rotation) > limits["board_rotation_abort_degrees"]
        ):
            self.backend.hold()
            return ManipulationResult(
                ResultStatus.OPERATOR_REQUIRED,
                plan.move_id,
                message=f"board pose outside tolerance: {translation * 1000:.1f} mm / {rotation:.2f} deg",
            )

        physical = self.backend.execute_plan(plan)
        if physical.status not in (ResultStatus.VERIFIED, ResultStatus.OPERATOR_REQUIRED):
            self.backend.hold()
            return physical

        promotion = next((step for step in plan.steps if step.kind == "promotion_pause"), None)
        if promotion:
            piece_type = str(promotion.metadata["piece_type"])
            if self.promotion_handler is None or not self.promotion_handler(promotion.target or "", piece_type):
                self.backend.hold()
                return ManipulationResult(
                    ResultStatus.OPERATOR_REQUIRED,
                    plan.move_id,
                    completed_steps=physical.completed_steps,
                    message=f"replace pawn at {promotion.target} with {piece_type}, then resume",
                )

        observed = self.backend.observe_occupancy()
        translation, rotation = self.backend.board_pose_error()
        report = verify_occupancy(
            plan.occupancy_after,
            observed,
            translation_error=translation,
            rotation_error_degrees=rotation,
            translation_abort=limits["board_translation_abort"],
            rotation_abort_degrees=limits["board_rotation_abort_degrees"],
        )
        if not report.ok:
            self.backend.hold()
            return ManipulationResult(
                ResultStatus.OPERATOR_REQUIRED,
                plan.move_id,
                completed_steps=physical.completed_steps,
                message=report.message,
                observed_occupancy=observed,
            )

        self.board.push(move)
        return ManipulationResult(
            ResultStatus.VERIFIED,
            plan.move_id,
            completed_steps=len(plan.steps),
            message="move executed, visually verified, and committed",
            observed_occupancy=observed,
        )
