"""Shared SO-101 helpers for the gemini_er experiment: connect, IK, interpolated moves.

Run everything with the driver venv (GUI cv2 + placo + lerobot 0.6.0):
  ../eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python
"""

from pathlib import Path

import numpy as np
from lerobot.model.kinematics import RobotKinematics
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
from lerobot.utils.robot_utils import precise_sleep

import devices

# Resolved per host: the udev name on lab-pi, the old usbmodem path on the Mac.
PORT = devices.follower_port()
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


def ik_to_xyz(
    kin: RobotKinematics, current_deg: np.ndarray, xyz, iters: int = 30, tol_m: float = 0.003
) -> np.ndarray:
    """Joint degrees that put the EE at absolute xyz, keeping the current orientation.

    placo's solver steps incrementally (the teleop loop re-solves at 30 Hz), so a
    single call under-shoots — iterate until the FK of the solution reaches xyz.
    """
    target = np.asarray(xyz, dtype=float)
    T = kin.forward_kinematics(current_deg).copy()
    T[:3, 3] = target
    j = np.array(current_deg, dtype=float)
    for _ in range(iters):
        j = kin.inverse_kinematics(j, T)
        if np.linalg.norm(kin.forward_kinematics(j)[:3, 3] - target) < tol_m:
            break
    return j


def plan_line(kin: RobotKinematics, start_deg, from_xyz, to_xyz, step_m: float = 0.01):
    """IK continuation along a straight EE line, each step seeded from the last.

    Keeps the solver on one arm configuration branch — one-shot IK to a far
    target can land on a flipped-elbow solution whose joint-space interpolation
    sweeps the EE through a wild arc. Returns the list of joint arrays.
    """
    a, b = np.asarray(from_xyz, float), np.asarray(to_xyz, float)
    n = max(1, int(np.ceil(np.linalg.norm(b - a) / step_m)))
    j = np.array(start_deg, dtype=float)
    path = []
    for i in range(1, n + 1):
        j = ik_to_xyz(kin, j, a + (b - a) * (i / n))
        path.append(j)
    return path


def follow_path(robot: SO101Follower, path, sec_per_point: float = 0.2, gripper: float | None = None):
    """Stream a whole path continuously at 30 Hz — one observation read total.

    Reading state between segments stalls the serial bus and makes the motion
    jerky; here only the start pose is read, then targets stream open-loop.
    """
    names = list(robot.bus.motors.keys())
    pts = [joints_deg(robot)] + [np.array(p, dtype=float).copy() for p in path]
    if gripper is not None:
        gi = names.index("gripper")
        for p in pts:
            p[gi] = gripper
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(sec_per_point * FPS))
        for i in range(1, n + 1):
            v = a + (b - a) * (i / n)
            robot.send_action({f"{m}.pos": float(v[j]) for j, m in enumerate(names)})
            precise_sleep(1.0 / FPS)


def settle_to(kin: RobotKinematics, robot: SO101Follower, xyz, iters: int = 3, tol_m: float = 0.004):
    """Closed-loop on FK: measure where the arm actually is, re-command with the
    error added. Fixes servo lag/gravity droop that open-loop streaming leaves."""
    target = np.asarray(xyz, dtype=float)
    correction = np.zeros(3)
    for _ in range(iters):
        j = joints_deg(robot)
        err = target - kin.forward_kinematics(j)[:3, 3]
        if np.linalg.norm(err) < tol_m:
            break
        correction += err
        move_joints(robot, ik_to_xyz(kin, j, target + correction), 0.8)
    return float(np.linalg.norm(target - kin.forward_kinematics(joints_deg(robot))[:3, 3]))


def max_step_deg(path) -> float:
    """Largest single-joint jump between consecutive path points (branch-flip tell)."""
    if len(path) < 2:
        return 0.0
    diffs = np.abs(np.diff(np.array(path)[:, :5], axis=0))  # ignore gripper
    return float(diffs.max())
