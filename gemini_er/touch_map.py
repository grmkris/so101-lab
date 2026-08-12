"""Positioning-accuracy map: command the EE to a target, hold just above the mat,
photograph, ER-point the gripper tip, compare. One leg per invocation.

Appends to debug/touch_map.jsonl: {target, measured, err_cm}.
"""

import argparse
import json
import time

import cv2
import numpy as np

import arm
from capture import grab
from cycle import DEBUG, load, px2world
from er_client import point_at
from pick import in_bounds

LOG = DEBUG / "touch_map.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", nargs=2, type=float, required=True)
    args = ap.parse_args()
    calib = load()
    tx, ty = args.target
    rec = {"t": time.strftime("%H:%M:%S"), "target": [tx, ty]}
    if not in_bounds(calib, tx, ty):
        rec["result"] = "out_of_bounds"
        print(json.dumps(rec))
        return
    z_hold = calib["z_table"] + 0.008  # low enough that tip-pixel parallax is ~negligible

    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=20)
        cur = arm.joints_deg(robot)
        path = arm.plan_line(kin, cur, kin.forward_kinematics(cur)[:3, 3], [tx, ty, z_hold])
        if arm.max_step_deg(path) > 25:
            rec["result"] = "branch_flip_refused"
            print(json.dumps(rec))
            return
        arm.follow_path(robot, path, 0.15, gripper=20)
        fk_res = arm.settle_to(kin, robot, [tx, ty, z_hold])
        rec["fk_residual_cm"] = round(fk_res * 100, 2)
        time.sleep(0.8)
        fpath = str(DEBUG / f"touch_{tx:.2f}_{ty:.2f}.jpg".replace("-", "m"))
        cv2.imwrite(fpath, grab(calib["camera_index"]))
        arm.follow_path(robot, path[::-1], 0.12, gripper=20)
        arm.move_joints(robot, home, 2.0)
    finally:
        robot.disconnect()

    pts = point_at(fpath, "the very tip of the robot gripper jaws touching near the black mat")
    if pts:
        mx, my = px2world(calib["H"], pts[0]["x"], pts[0]["y"])
        rec["measured"] = [round(float(mx), 4), round(float(my), 4)]
        rec["err_cm"] = round(float(np.hypot(mx - tx, my - ty)) * 100, 1)
        rec["result"] = "ok"
    else:
        rec["result"] = "tip_not_found"
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
