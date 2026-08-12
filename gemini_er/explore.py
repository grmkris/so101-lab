"""Capability mapping: pick the block from wherever it is, place it at --target,
measure everything, append a JSON record to debug/explore_log.jsonl.

One invocation = one pick+place leg. Run repeatedly over a grid to map the mat.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

import arm
from cycle import DEBUG, coarse_locate, goto, load, wrist_servo
from pick import in_bounds

LOG = DEBUG / "explore_log.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", nargs=2, type=float, required=True)
    ap.add_argument("--block", default="the small white plastic block")
    ap.add_argument("--open", dest="open_", type=float, default=80)
    ap.add_argument("--close", type=float, default=0)
    args = ap.parse_args()

    DEBUG.mkdir(exist_ok=True)
    calib = load()
    zt = calib["z_table"]
    z_hover, z_grasp, z_place = zt + 0.08, zt + 0.015, zt + 0.05
    tx, ty = args.target
    rec = {"t": time.strftime("%H:%M:%S"), "target": [tx, ty],
           "servo_err": [], "grip": []}

    if not in_bounds(calib, tx, ty):
        rec["result"] = "target_out_of_bounds"
        print(json.dumps(rec))
        return

    block_xy = coarse_locate(calib, "the white plastic block", "explore_pre")
    rec["picked_from"] = [round(v, 4) for v in block_xy]

    robot = arm.connect()
    kin = arm.kinematics(robot)
    held = False
    cx, cy = block_xy
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=args.open_)
        for attempt in range(3):
            goto(robot, kin, [cx, cy, z_hover], gripper=args.open_)
            cx, cy, e = wrist_servo(robot, kin, calib, args.block, cx, cy, z_hover,
                                    tag=f"exp{attempt}")
            rec["servo_err"].append(round(e, 1))
            if e > 60:
                cx, cy = coarse_locate(calib, "the white plastic block", "explore_re")
                continue
            goto(robot, kin, [cx, cy, z_grasp], 0.25, gripper=args.open_)
            arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=args.close)
            time.sleep(0.4)
            g = float(arm.joints_deg(robot)[-1])
            rec["grip"].append(round(g, 1))
            if g > args.close + 3.5:
                held = True
                break
            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
            goto(robot, kin, [cx, cy, z_hover], gripper=args.open_)
            cx, cy = coarse_locate(calib, "the white plastic block", "explore_re")
        rec["picked"] = held
        if held:
            goto(robot, kin, [cx, cy, z_hover], gripper=args.close)
            goto(robot, kin, [tx, ty, z_hover], gripper=args.close)
            goto(robot, kin, [tx, ty, z_place], 0.25, gripper=args.close)
            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
            time.sleep(0.3)
            goto(robot, kin, [tx, ty, z_hover], gripper=args.open_)
        arm.move_joints(robot, home, 2.0, gripper=args.open_)
    finally:
        robot.disconnect()

    if held:
        lx, ly = coarse_locate(calib, "the white plastic block", "explore_post")
        rec["landed"] = [round(lx, 4), round(ly, 4)]
        rec["place_err_cm"] = round(float(np.hypot(lx - tx, ly - ty)) * 100, 1)
        rec["result"] = "ok"
    else:
        rec["result"] = "pick_failed"

    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
