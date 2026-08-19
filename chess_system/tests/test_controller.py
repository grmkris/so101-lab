from __future__ import annotations

import unittest

import chess

from chess_system.controller import ChessController, occupancy_from_board, plan_move
from chess_system.geometry import SquarePose, load_geometry
from chess_system.model import ManipulationResult, ResultStatus
from chess_system.verification import ALL_SQUARES


class StateBackend:
    name = "state-test"

    def __init__(self, board: chess.Board, mismatch: str | None = None):
        self.occupancy = occupancy_from_board(board)
        self.mismatch = mismatch
        self.held = False
        self.stopped = False

    def square_pose(self, square: str, phase: str) -> SquarePose:
        return load_geometry().square(square)

    def execute_plan(self, plan):
        completed = 0
        for step in plan.steps:
            if step.kind == "capture":
                self.occupancy[step.source] = False
            elif step.kind in ("move", "castle_rook"):
                if not self.occupancy[step.source] or self.occupancy[step.target]:
                    return ManipulationResult(ResultStatus.FAILED, plan.move_id, completed, "invalid state")
                self.occupancy[step.source] = False
                self.occupancy[step.target] = True
            completed += 1
        return ManipulationResult(ResultStatus.VERIFIED, plan.move_id, completed, "done")

    def observe_occupancy(self):
        result = dict(self.occupancy)
        if self.mismatch:
            result[self.mismatch] = not result[self.mismatch]
        return result

    def board_pose_error(self):
        return 0.0, 0.0

    def home(self):
        self.stopped = False

    def hold(self):
        self.held = True

    def emergency_stop(self):
        self.stopped = True


class ControllerTests(unittest.TestCase):
    def test_normal_move_commits_after_verification(self):
        board = chess.Board()
        backend = StateBackend(board)
        controller = ChessController(backend, board=board)
        result = controller.execute_uci("e2e4")
        self.assertEqual(result.status, ResultStatus.VERIFIED)
        self.assertIsNotNone(controller.board.piece_at(chess.E4))
        self.assertIsNone(controller.board.piece_at(chess.E2))

    def test_capture_plan_removes_target_first(self):
        board = chess.Board()
        for uci in ("e2e4", "d7d5"):
            board.push_uci(uci)
        move = chess.Move.from_uci("e4d5")
        plan = plan_move(board, move)
        self.assertEqual([step.kind for step in plan.steps], ["capture", "move"])
        self.assertEqual(plan.steps[0].source, "d5")
        controller = ChessController(StateBackend(board), board=board)
        self.assertTrue(controller.execute_uci("e4d5").ok)

    def test_castling_moves_rook(self):
        board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        plan = plan_move(board, chess.Move.from_uci("e1g1"))
        self.assertEqual([step.kind for step in plan.steps], ["move", "castle_rook"])
        self.assertEqual((plan.steps[1].source, plan.steps[1].target), ("h1", "f1"))
        controller = ChessController(StateBackend(board), board=board)
        self.assertTrue(controller.execute_uci("e1g1").ok)

    def test_black_queenside_castling(self):
        board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1")
        plan = plan_move(board, chess.Move.from_uci("e8c8"))
        self.assertEqual((plan.steps[1].source, plan.steps[1].target), ("a8", "d8"))
        controller = ChessController(StateBackend(board), board=board)
        self.assertTrue(controller.execute_uci("e8c8").ok)

    def test_en_passant_removes_real_capture_square(self):
        board = chess.Board()
        for uci in ("e2e4", "a7a6", "e4e5", "d7d5"):
            board.push_uci(uci)
        plan = plan_move(board, chess.Move.from_uci("e5d6"))
        self.assertEqual(plan.steps[0].kind, "capture")
        self.assertEqual(plan.steps[0].source, "d5")
        self.assertTrue(plan.steps[0].metadata["en_passant"])
        controller = ChessController(StateBackend(board), board=board)
        self.assertTrue(controller.execute_uci("e5d6").ok)

    def test_promotion_pauses_without_operator_swap(self):
        board = chess.Board("8/P7/8/8/8/8/8/4K2k w - - 0 1")
        backend = StateBackend(board)
        controller = ChessController(backend, board=board)
        result = controller.execute_uci("a7a8q")
        self.assertEqual(result.status, ResultStatus.OPERATOR_REQUIRED)
        self.assertEqual(controller.board.fen(), board.fen())
        self.assertTrue(backend.held)

    def test_promotion_commits_after_operator_confirmation(self):
        board = chess.Board("8/P7/8/8/8/8/8/4K2k w - - 0 1")
        controller = ChessController(StateBackend(board), board=board, promotion_handler=lambda square, piece: True)
        result = controller.execute_uci("a7a8n")
        self.assertTrue(result.ok)
        self.assertEqual(controller.board.piece_at(chess.A8).piece_type, chess.KNIGHT)

    def test_visual_mismatch_does_not_commit(self):
        board = chess.Board()
        initial_fen = board.fen()
        backend = StateBackend(board, mismatch="a3")
        controller = ChessController(backend, board=board)
        result = controller.execute_uci("e2e4")
        self.assertEqual(result.status, ResultStatus.OPERATOR_REQUIRED)
        self.assertEqual(controller.board.fen(), initial_fen)
        self.assertTrue(backend.held)

    def test_illegal_move_is_rejected_before_backend(self):
        board = chess.Board()
        controller = ChessController(StateBackend(board), board=board)
        with self.assertRaises(ValueError):
            controller.execute_uci("e2e5")


if __name__ == "__main__":
    unittest.main()
