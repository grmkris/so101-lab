from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

import numpy as np

from chess_system.controller import ChessController
from chess_system.mujoco.rrt import RRTConnect
from chess_system.mujoco.trajectory import TrajectoryLibrary
from chess_system.mujoco.trajectory_executor import PlannedMujocoChessBackend


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "chess_system" / "mujoco" / "generated" / "trajectory_library.json"
REPORT = ROOT / "chess_system" / "mujoco" / "generated" / "trajectory_report.json"


class MotionPlanningTests(unittest.TestCase):
    def test_library_is_complete_and_tolerance_clean(self):
        library = TrajectoryLibrary.load(LIBRARY)
        self.assertEqual(len(library.trajectories), 130)
        for square_file in "abcdefgh":
            for rank in "12345678":
                square = f"{square_file}{rank}"
                self.assertIn(f"exit:{square}", library.trajectories)
                self.assertIn(f"entry:{square}", library.trajectories)
        self.assertIn("capture_bin:white", library.trajectories)
        self.assertIn("capture_bin:black", library.trajectories)
        for trajectory in library.trajectories.values():
            self.assertEqual(trajectory.metrics.tolerance_failures, 0)
            self.assertGreaterEqual(
                trajectory.metrics.minimum_joint_margin_degrees, 5.0
            )
            points = np.asarray(trajectory.waypoints_degrees)
            if len(points) > 1:
                self.assertLessEqual(float(np.abs(np.diff(points, axis=0)).max()), 1.0001)

    def test_near_rank_uses_collision_free_tilt(self):
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        tilts = {detail["target"]: detail["tilt_degrees"] for detail in report["details"]}
        self.assertEqual(tilts["a1"], 0.0)
        for square in ("c1", "d1", "e1", "f1"):
            self.assertGreater(tilts[square], 0.0)

    def test_rrt_is_deterministic_when_direct_edge_is_blocked(self):
        lower = np.asarray((-1.0, -1.0))
        upper = np.asarray((1.0, 1.0))

        def state_valid(q):
            return not (-0.25 < q[0] < 0.25 and -0.65 < q[1] < 0.65)

        def edge_valid(start, end):
            for alpha in np.linspace(0, 1, 30):
                if not state_valid(start + (end - start) * alpha):
                    return False
            return True

        planner = RRTConnect(
            lower,
            upper,
            state_valid,
            edge_valid,
            step_radians=0.15,
            goal_bias=0.15,
            maximum_iterations=5000,
        )
        first = planner.plan(np.asarray((-0.8, 0.0)), np.asarray((0.8, 0.0)), seed=42)
        second = planner.plan(np.asarray((-0.8, 0.0)), np.asarray((0.8, 0.0)), seed=42)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        np.testing.assert_allclose(np.asarray(first.path), np.asarray(second.path))

    def test_planned_dynamic_sequence_with_capture(self):
        backend = PlannedMujocoChessBackend()
        controller = ChessController(backend)
        for move in ("e2e4", "d7d5", "e4d5", "g8f6", "g1f3", "f6d5"):
            result = controller.execute_uci(move)
            self.assertTrue(result.ok, f"{move}: {result.message}")


if __name__ == "__main__":
    unittest.main()
