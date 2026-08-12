"""Shared SO-101 helpers for the gemini_er experiment: connect, IK, interpolated moves.

Run everything with the driver venv (GUI cv2 + placo + lerobot 0.6.0):
  ../eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python
"""

from pathlib import Path

import numpy as np
from lerobot.model.kinematics import RobotKinematics
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
from lerobot.utils.robot_utils import precise_sleep

PORT = "/dev/tty.usbmodem5AE60832001"
URDF = str(Path(__file__).resolve().parent.parent / "phone_teleop/SO101/so101_new_calib.urdf")
FPS = 30
# Same EE box phone_teleop + the driver's ee_chain enforce (metres, URDF base frame).
EE_MIN = np.array([-0.5, -0.5, -0.1])
EE_MAX = np.array([0.5, 0.5, 0.5])


def connect(max_relative_target: float = 15.0) -> SO101Follower:
    cfg = SO101FollowerConfig(
        port=PORT, id="arm", use_degrees=True, max_relative_target=max_relative_target
    )
    robot = SO101Follower(cfg)
    robot.connect(calibrate=False)
    return robot


def kinematics(robot: SO101Follower) -> RobotKinematics:
    return RobotKinematics(
        urdf_path=URDF,
        target_frame_name="gripper_frame_link",
        joint_names=list(robot.bus.motors.keys()),
    )


def kinematics_standalone() -> RobotKinematics:
    # SO-101 motor order, for --dry-run without an arm connected.
    names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    return RobotKinematics(urdf_path=URDF, target_frame_name="gripper_frame_link", joint_names=names)


def joints_deg(robot: SO101Follower) -> np.ndarray:
    obs = robot.get_observation()
    return np.array([obs[f"{m}.pos"] for m in robot.bus.motors])


def move_joints(robot: SO101Follower, target, seconds: float = 2.5, gripper: float | None = None):
    """Linear joint-space interpolation from current pose to target (degrees).

    gripper: 0-100 absolute jaw target, or None to carry the target's own value.
    """
    names = list(robot.bus.motors.keys())
    start = joints_deg(robot)
    tgt = np.array(target, dtype=float)
    if gripper is not None:
        tgt[names.index("gripper")] = gripper
    n = max(2, int(seconds * FPS))
    for i in range(1, n + 1):
        a = start + (tgt - start) * (i / n)
        robot.send_action({f"{m}.pos": float(a[j]) for j, m in enumerate(names)})
        precise_sleep(1.0 / FPS)


def ik_to_xyz(kin: RobotKinematics, current_deg: np.ndarray, xyz) -> np.ndarray:
    """Joint degrees that put the EE at absolute xyz, keeping the current orientation."""
    T = kin.forward_kinematics(current_deg).copy()
    T[:3, 3] = np.asarray(xyz, dtype=float)
    return kin.inverse_kinematics(current_deg, T)
