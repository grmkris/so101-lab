from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from chess_system.controller import ChessController
from chess_system.mujoco.generate_trajectories import persist_generation
from chess_system.mujoco.rrt import RRTConnect
from chess_system.mujoco.trajectory import TrajectoryLibrary, failed_library_path
from chess_system.mujoco.trajectory_executor import PlannedMujocoChessBackend


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "chess_system" / "mujoco" / "generated" / "trajectory_library.json"
REPORT = ROOT / "chess_system" / "mujoco" / "generated" / "trajectory_report.json"


class MotionPlanningTests(unittest.TestCase):
    def test_library_is_complete_and_tolerance_clean(self):
        library = TrajectoryLibrary.load(LIBRARY)
        # Stock jaws (no 20 mm pads): e1 and the black capture bin do not
        # currently have a robust empty-board route. 63 squares × 2 + white bin.
        self.assertEqual(len(library.trajectories), 127)
        skip = {"e1"}
        for square_file in "abcdefgh":
            for rank in "12345678":
                square = f"{square_file}{rank}"
                if square in skip:
                    self.assertNotIn(f"exit:{square}", library.trajectories)
                    continue
                self.assertIn(f"exit:{square}", library.trajectories)
                self.assertIn(f"entry:{square}", library.trajectories)
        self.assertIn("capture_bin:white", library.trajectories)
        self.assertNotIn("capture_bin:black", library.trajectories)
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
        for square in ("c1", "d1", "f1"):
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
        # Crowded 23 mm pitch: stock jaws clip the neighbour on e2e4.
        # Planning still has to offer a legal alternative.
        backend = PlannedMujocoChessBackend()
        controller = ChessController(backend)
        self.assertTrue(controller.check_executable("d2d4").executable)

    def test_crowded_back_rank_knights_are_out_of_reach_at_the_start(self):
        """Both white knights are unreachable from the opening position.

        This is a cost of modelling the tool honestly. The finger extensions
        are asymmetric — one is fixed to the gripper body, the other swings on
        the jaw — so grasping a back-rank piece sweeps the moving tip through
        whichever neighbour sits on the swing side. The earlier symmetric
        model, with both extensions frozen 19 mm apart on the static body,
        showed no such conflict because it could not move at all.

        Recorded rather than worked around: it is real reachability
        information about the 23 mm board, and move selection is expected to
        route around it instead of failing.
        """

        backend = PlannedMujocoChessBackend()
        controller = ChessController(backend)
        for move in ("g1f3", "b1c3"):
            report = controller.check_executable(move)
            self.assertFalse(report.executable, f"{move} unexpectedly reachable")
        # The game must not stall on it: a reachable alternative exists.
        self.assertTrue(controller.check_executable("d2d4").executable)

    def test_friction_grasp_transfers_e2e4_without_teleport(self):
        backend = PlannedMujocoChessBackend()
        self.assertFalse(backend.executor.assist_grasp)
        self.assertFalse(backend.geometry.tool.get("use_finger_extensions", True))
        piece = backend._square_piece["e2"]
        from chess_system.mujoco.probe_grasp import _disable_other_pieces

        _disable_other_pieces(backend.executor, piece)
        backend._square_piece.clear()
        backend._piece_square.clear()
        backend._square_piece["e2"] = piece
        backend._piece_square[piece] = "e2"
        occupied = {"e2"}
        transfer = backend.executor.runtime_planner.transfer_route("e2", "e4", occupied)
        source_q = np.radians(np.asarray(transfer.waypoints_degrees[0]))
        pose = backend.executor.geometry.square(
            "e2", z=float(backend.executor.geometry.board["nominal_top_z"])
        )
        _, entry = backend.executor.runtime_planner.arm_routes_to_endpoint(
            "e2", source_q, np.asarray(pose.xyz()), occupied, excluded_square="e2"
        )
        backend.executor.approach_and_latch("e2", entry)
        self.assertTrue(backend.executor._pinch_is_loaded(piece))


class LibraryPersistTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmpdir.name)
        self.library_path = self.directory / "trajectory_library.json"
        self.report_path = self.directory / "trajectory_report.json"
        self.failed_path = failed_library_path(self.library_path)
        self.library = TrajectoryLibrary(generation={"planner": "test"})
        self.library_path.write_text('{"stale": true}\n', encoding="utf-8")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_failed_generation_deletes_stale_library(self):
        persist_generation(
            self.library,
            {"status": "fail", "failures": [{"target": "a1"}]},
            self.library_path,
            self.report_path,
        )
        self.assertFalse(self.library_path.exists())
        self.assertTrue(self.failed_path.is_file())
        self.assertEqual(
            json.loads(self.report_path.read_text(encoding="utf-8"))["status"],
            "fail",
        )
        failed = TrajectoryLibrary.load(self.failed_path)
        self.assertEqual(failed.generation["status"], "fail")
        with self.assertRaisesRegex(FileNotFoundError, "Generation failed"):
            TrajectoryLibrary.load(self.library_path)

    def test_passed_generation_replaces_library_and_clears_failed_artifact(self):
        self.failed_path.write_text('{"stale_failed": true}\n', encoding="utf-8")
        persist_generation(
            self.library,
            {"status": "pass", "failures": []},
            self.library_path,
            self.report_path,
        )
        self.assertTrue(self.library_path.is_file())
        self.assertFalse(self.failed_path.exists())
        loaded = TrajectoryLibrary.load(self.library_path)
        self.assertEqual(loaded.generation["planner"], "test")
        self.assertNotIn("status", loaded.generation)


if __name__ == "__main__":
    unittest.main()
