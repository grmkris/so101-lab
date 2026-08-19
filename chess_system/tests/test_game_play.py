from __future__ import annotations

import unittest

import chess

from chess_system.controller import ChessController, plan_move
from chess_system.engine import evaluate, rank_moves
from chess_system.model import ExecutabilityReport, ManipulationResult, ResultStatus
from chess_system.mujoco.backend import MujocoChessBackend


class EngineTests(unittest.TestCase):
    def test_ranking_is_deterministic_and_total(self):
        board = chess.Board()
        first = [move.uci() for move in rank_moves(board, depth=2)]
        second = [move.uci() for move in rank_moves(board, depth=2)]
        self.assertEqual(first, second)
        self.assertCountEqual(first, [move.uci() for move in board.legal_moves])

    def test_ranking_prefers_a_free_queen(self):
        # Black queen on d5 is undefended and White's rook on d1 can take it.
        board = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
        self.assertEqual(rank_moves(board, depth=2)[0].uci(), "d1d5")

    def test_evaluation_is_side_to_move_relative(self):
        white = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        black = chess.Board("4k3/8/8/8/8/8/8/3QK3 b - - 0 1")
        self.assertGreater(evaluate(white), 0)
        self.assertLess(evaluate(black), 0)

    def test_mate_in_one_is_found(self):
        # Back-rank mate: Re8# is the only mate, and the king is boxed in by
        # its own pawns.
        board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1")
        best = rank_moves(board, depth=2)[0]
        board.push(best)
        self.assertTrue(board.is_checkmate())


class _ScriptedBackend(MujocoChessBackend):
    """Kinematic backend that refuses a named set of moves as unreachable."""

    def __init__(self, unreachable: set[str]):
        super().__init__()
        self.unreachable = unreachable
        self.probes: list[str] = []

    def can_execute(self, plan) -> ExecutabilityReport:
        self.probes.append(plan.uci)
        if plan.uci in self.unreachable:
            return ExecutabilityReport(
                uci=plan.uci,
                executable=False,
                reason="scripted obstruction",
                blocked_step=0,
            )
        return ExecutabilityReport(uci=plan.uci, executable=True)


class ReachabilityTests(unittest.TestCase):
    def test_select_move_skips_unreachable_and_probes_lazily(self):
        board = chess.Board()
        ranked = rank_moves(board, depth=2)
        blocked = {move.uci() for move in ranked[:2]}
        backend = _ScriptedBackend(blocked)
        controller = ChessController(backend, board=board)

        chosen, rejected = controller.select_move(ranked)

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.uci(), ranked[2].uci())
        self.assertEqual([r.uci for r in rejected], [m.uci() for m in ranked[:2]])
        self.assertFalse(any(r.executable for r in rejected))
        # Lazy: it stops probing at the first reachable move.
        self.assertEqual(len(backend.probes), 3)

    def test_select_move_returns_none_when_nothing_is_reachable(self):
        board = chess.Board()
        ranked = rank_moves(board, depth=2)
        backend = _ScriptedBackend({move.uci() for move in ranked})
        controller = ChessController(backend, board=board)

        chosen, rejected = controller.select_move(ranked)

        self.assertIsNone(chosen)
        self.assertEqual(len(rejected), len(ranked))

    def test_unreachable_move_halts_instead_of_executing(self):
        board = chess.Board()
        backend = _ScriptedBackend({"e2e4"})
        controller = ChessController(backend, board=board)

        result = controller.execute_uci("e2e4")

        self.assertEqual(result.status, ResultStatus.OPERATOR_REQUIRED)
        self.assertIn("mechanically unreachable", result.message)
        # The board must not advance and the piece must not have moved.
        self.assertEqual(controller.board.fen(), chess.Board().fen())
        self.assertTrue(backend.observe_occupancy()["e2"])
        self.assertFalse(backend.observe_occupancy()["e4"])

    def test_backend_without_preflight_is_treated_as_optimistic(self):
        backend = MujocoChessBackend()
        controller = ChessController(backend)
        self.assertFalse(hasattr(backend, "can_execute"))
        report = controller.check_executable("e2e4")
        self.assertTrue(report.executable)
        self.assertIsInstance(
            controller.execute_uci("e2e4"), ManipulationResult
        )


class PreflightOccupancyTests(unittest.TestCase):
    def test_capture_plan_frees_the_target_before_the_mover_is_probed(self):
        # 1. e4 d5 2. exd5 — the capture step must vacate d5 before the pawn
        # on e4 is planned into it, or the preflight rejects its own move.
        board = chess.Board()
        for uci in ("e2e4", "d7d5"):
            board.push(chess.Move.from_uci(uci))
        plan = plan_move(board, chess.Move.from_uci("e4d5"))

        kinds = [step.kind for step in plan.steps]
        self.assertEqual(kinds, ["capture", "move"])
        self.assertEqual(plan.steps[0].source, "d5")
        self.assertEqual(plan.steps[1].source, "e4")
        self.assertEqual(plan.steps[1].target, "d5")


if __name__ == "__main__":
    unittest.main()
