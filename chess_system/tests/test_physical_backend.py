from __future__ import annotations

import unittest

import chess

from chess_system.controller import ChessController, occupancy_from_board
from chess_system.model import ResultStatus
from chess_system.physical.backend import PhysicalChessBackend
from chess_system.vision.occupancy import BoardObservation


class FakeMotion:
    def __init__(self, board):
        self.occupancy = occupancy_from_board(board)
        self.calls = []
        self.held = False
        self.stopped = False

    def pick_and_place(self, source, target):
        self.calls.append(("move", source, target))
        self.occupancy[source] = False
        self.occupancy[target] = True

    def capture_to_bin(self, source, color):
        self.calls.append(("capture", source, color))
        self.occupancy[source] = False

    def home(self):
        self.calls.append(("home",))

    def hold(self):
        self.held = True

    def emergency_stop(self):
        self.stopped = True


class FakeVerifier:
    def __init__(self, motion):
        self.motion = motion

    def observe(self, _frame):
        return BoardObservation(dict(self.motion.occupancy), {}, 0.0, 0.0, None)


class PhysicalBackendTests(unittest.TestCase):
    def test_dependency_injected_backend_commits_verified_move(self):
        board = chess.Board()
        motion = FakeMotion(board)
        backend = PhysicalChessBackend(motion, FakeVerifier(motion), lambda: object())
        controller = ChessController(backend, board=board)
        result = controller.execute_uci("e2e4")
        self.assertEqual(result.status, ResultStatus.VERIFIED)
        self.assertEqual(motion.calls, [("move", "e2", "e4")])

    def test_emergency_stop_blocks_execution(self):
        board = chess.Board()
        motion = FakeMotion(board)
        backend = PhysicalChessBackend(motion, FakeVerifier(motion), lambda: object())
        backend.emergency_stop()
        controller = ChessController(backend, board=board)
        result = controller.execute_uci("e2e4")
        self.assertEqual(result.status, ResultStatus.STOPPED)
        self.assertTrue(motion.stopped)


if __name__ == "__main__":
    unittest.main()
