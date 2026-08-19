from __future__ import annotations

import math
import unittest

from chess_system.geometry import load_geometry
from chess_system.mujoco.validate_reach import validate as validate_reach


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.geometry = load_geometry()

    def test_board_dimensions_and_reach(self):
        report = self.geometry.report()
        self.assertEqual(report["square_mm"], 23.0)
        self.assertEqual(report["playfield_mm"], 184.0)
        self.assertTrue(report["inside_conditioned_radial_envelope"])
        self.assertEqual(len(list(self.geometry.squares())), 64)

    def test_coordinate_convention(self):
        a1 = self.geometry.square("a1")
        h1 = self.geometry.square("h1")
        a8 = self.geometry.square("a8")
        self.assertGreater(a1.y, h1.y, "a-file must be on the robot's left")
        self.assertGreater(a8.x, a1.x, "rank 8 must be farther from the robot")
        self.assertAlmostEqual(a1.x, 0.0965)
        self.assertAlmostEqual(a1.y, 0.0805)

    def test_clearance_contract(self):
        pitch = self.geometry.square_size
        self.assertGreaterEqual(pitch - self.geometry.piece["base_diameter"], 0.009)
        self.assertGreaterEqual(pitch - self.geometry.tool["maximum_open_outer_width"], 0.004)

    def test_capture_bins_are_reachable_and_outside_board(self):
        half_playfield = self.geometry.playfield_size / 2
        for color in ("white", "black"):
            x, y = self.geometry.capture_bin(color)
            self.assertGreater(abs(y), half_playfield)
            self.assertLess(math.hypot(x, y), self.geometry.robot["conditioned_radius_range"][1])

    def test_all_64_vertical_grasps_pass_model_gate(self):
        report = validate_reach()
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["vertical_grasp_ik_failures"], [])
        self.assertEqual(report["vertical_grasp_board_contact_failures"], [])


if __name__ == "__main__":
    unittest.main()
