"""Blind grasp with bias-field correction, no wrist cam: ER locates the block in
the workspace cam, the touch-map bias corrects the command, descend + close +
proprioceptive check. Logs to debug/pick_blind.jsonl.
"""

import json
import time

import numpy as np

import arm
from cycle import DEBUG, coarse_locate, goto, load
from push import bias_field

LOG = DEBUG / "pick_blind.jsonl"


def main():
    calib = load()
    zt = calib["z_table"]
    corr = bias_field()
    rec = {"t": time.strftime("%H:%M:%S")}

    block = np.array(coarse_locate(calib, "the white plastic block", "blind_pre"))
    c = corr(block)
    cmd = block + c
    rec["block"] = [round(float(v), 4) for v in block]
    rec["correction_cm"] = [round(float(v) * 100, 1) for v in c]

    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=80)
        goto(robot, kin, [cmd[0], cmd[1], zt + 0.08], gripper=80)
        goto(robot, kin, [cmd[0], cmd[1], zt + 0.015], 0.25, gripper=80)
        arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=0)
        time.sleep(0.4)
        g = float(arm.joints_deg(robot)[-1])
        rec["grip"] = round(g, 1)
        rec["held"] = g > 3.5
        if rec["held"]:
            # lift, show off, put it back down gently
            goto(robot, kin, [cmd[0], cmd[1], zt + 0.10], gripper=0)
            time.sleep(1.0)
            goto(robot, kin, [cmd[0], cmd[1], zt + 0.03], 0.25, gripper=0)
        arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=80)
        goto(robot, kin, [cmd[0], cmd[1], zt + 0.08], gripper=80)
        arm.move_joints(robot, home, 2.0, gripper=80)
    finally:
        robot.disconnect()

    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
