from __future__ import annotations

import unittest

import chess

from chess_system.controller import ChessController
from chess_system.model import ResultStatus
from chess_system.mujoco.backend import MujocoChessBackend


class MujocoBackendTests(unittest.TestCase):
    def test_opening_with_capture(self):
        backend = MujocoChessBackend()
        controller = ChessController(backend)
        for move in ("e2e4", "d7d5", "e4d5"):
            result = controller.execute_uci(move)
            self.assertEqual(result.status, ResultStatus.VERIFIED, result.message)
        self.assertTrue(backend.observe_occupancy()["d5"])
        self.assertFalse(backend.observe_occupancy()["e4"])

    def test_complete_checkmating_sequence(self):
        backend = MujocoChessBackend()
        controller = ChessController(backend)
        for move in ("e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"):
            result = controller.execute_uci(move)
            self.assertEqual(result.status, ResultStatus.VERIFIED, result.message)
        self.assertTrue(controller.board.is_checkmate())


if __name__ == "__main__":
    unittest.main()
