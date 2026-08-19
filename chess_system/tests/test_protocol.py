from __future__ import annotations

import math
import unittest

from chess_system.geometry import load_geometry
from chess_system.teleop.protocol import JointStatePacket, LatestJointState
from chess_system.mujoco.teleop import packet_to_controls
import mujoco


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        joints = {name: float(index) for index, name in enumerate(load_geometry().teleoperation["joint_order"])}
        joints["gripper"] = 50.0
        self.packet = JointStatePacket.create(1, "test", joints)

    def test_round_trip(self):
        decoded = JointStatePacket.from_bytes(self.packet.to_bytes())
        self.assertEqual(decoded.sequence, 1)
        self.assertEqual(decoded.joints, self.packet.joints)

    def test_missing_joint_is_rejected(self):
        joints = dict(self.packet.joints)
        del joints["wrist_roll"]
        with self.assertRaises(ValueError):
            JointStatePacket.create(2, "test", joints)

    def test_out_of_order_and_watchdog(self):
        latest = LatestJointState(watchdog_seconds=0.25)
        now = 1_000_000_000
        self.assertTrue(latest.accept(self.packet, received_ns=now))
        self.assertFalse(latest.accept(self.packet, received_ns=now + 1))
        self.assertIsNotNone(latest.latest(now_ns=now + 249_000_000))
        self.assertIsNone(latest.latest(now_ns=now + 251_000_000))

    def test_mujoco_control_conversion(self):
        model = mujoco.MjModel.from_xml_path("sim/model/chess_scene.xml")
        controls = packet_to_controls(model, self.packet)
        self.assertEqual(len(controls), model.nu)
        shoulder = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "shoulder_lift")
        gripper = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "gripper")
        self.assertAlmostEqual(controls[shoulder], math.radians(self.packet.joints["shoulder_lift"]))
        low, high = model.actuator_ctrlrange[gripper]
        self.assertAlmostEqual(controls[gripper], (low + high) / 2)


if __name__ == "__main__":
    unittest.main()
