from __future__ import annotations

import unittest

from chess_system.fabrication.validate_assets import validate


class GeneratedAssetTests(unittest.TestCase):
    def test_piece_meshes_match_manifest_envelope(self):
        report = validate()
        self.assertEqual(report["status"], "pass", report)


if __name__ == "__main__":
    unittest.main()
