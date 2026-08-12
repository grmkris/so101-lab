"""Ground-truth test of the whole chain: descend to a target, HOLD, photograph.

The photo shows the real offset between the gripper and the intended target —
one run measures homography + FK + execution error together.

Usage: debug_touch.py --xy X Y [--hold-z 0.02] [--out touch.jpg]
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import arm
from capture import grab

CALIB_PATH = Path(__file__).resolve().parent / "calib.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xy", nargs=2, type=float, required=True)
    ap.add_argument("--hold-z", type=float, default=0.02)
    ap.add_argument("--out", default="touch.jpg")
    args = ap.parse_args()

    calib = json.loads(CALIB_PATH.read_text())
    x, y = args.xy
    z = calib["z_table"] + args.hold_z
    home = np.array(calib["home_joints"])

    kin = arm.kinematics_standalone()
    home_xyz = kin.forward_kinematics(home)[:3, 3]
    approach = arm.plan_line(kin, home, home_xyz, [x, y, z])
    print(f"target ({x:.4f},{y:.4f},{z:.4f}), {len(approach)} path points, "
          f"worst step {arm.max_step_deg(approach):.1f} deg")

    robot = arm.connect()
    try:
        arm.move_joints(robot, home, 2.5, gripper=50)
        arm.follow_path(robot, approach, 0.15, gripper=50)
        # settle, then photograph the held pose
        import time

        time.sleep(0.8)
        cv2.imwrite(args.out, grab(calib["camera_index"]))
        j = arm.joints_deg(robot)
        print("held FK xyz:", np.round(kin.forward_kinematics(j)[:3, 3], 4))
        print(f"photo: {args.out}")
        arm.follow_path(robot, approach[::-1], 0.15, gripper=50)
        arm.move_joints(robot, home, 2.0)
    finally:
        robot.disconnect()
        print("robot disconnected (torque off).")


if __name__ == "__main__":
    main()
