"""Blind grasp via the ChArUco-board chain: ER contact-point -> pixel ->
board-mm homography -> arm-registration affine -> grasp. No wrist cam.

Logs to debug/pick_board.jsonl.
"""

import json
import time

import cv2
import numpy as np

import arm
from capture import grab
from cycle import DEBUG, goto, load
from er_client import point_at

LOG = DEBUG / "pick_board.jsonl"


def main():
    calib = load()
    board = calib.get("board") or exit("no board calibration — run board_calibrate.py")
    H = np.array(board["H"])
    A = np.array(board["affine"])
    zt = calib["z_table"]
    rec = {"t": time.strftime("%H:%M:%S")}

    fpath = str(DEBUG / "pick_board_pre.jpg")
    cv2.imwrite(fpath, grab(calib["camera_index"]))
    pts = point_at(fpath, "the exact point where the small white plastic block touches the checkerboard paper (its bottom contact edge)")
    if not pts:
        exit("block not found")
    def board_pt(px, py):
        v = H @ np.array([px, py, 1.0])
        return v[:2] / v[2]

    # ER points at the near contact edge; block center is ~1 cm farther along
    # the camera's depth axis (image-up maps to away-from-camera on the board)
    edge = board_pt(pts[0]["x"], pts[0]["y"])
    up = board_pt(pts[0]["x"], pts[0]["y"] - 40.0)
    u = (up - edge) / np.linalg.norm(up - edge)
    bmm = edge + u * 12.0
    cmd = A @ np.array([bmm[0], bmm[1], 1.0])
    rec["board_mm"] = [round(float(x), 1) for x in bmm]
    rec["cmd"] = [round(float(x), 4) for x in cmd]
    print(f"block at board ({bmm[0]:.0f},{bmm[1]:.0f}) mm -> arm cmd ({cmd[0]:.4f},{cmd[1]:.4f})")

    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=80)
        goto(robot, kin, [cmd[0], cmd[1], zt + 0.08], gripper=80)
        goto(robot, kin, [cmd[0], cmd[1], zt + 0.015], 0.25, gripper=80)
        cv2.imwrite(str(DEBUG / "pick_board_descend.jpg"), grab(calib["camera_index"]))
        arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=0)
        time.sleep(0.4)
        g = float(arm.joints_deg(robot)[-1])
        rec["grip"] = round(g, 1)
        rec["held"] = g > 3.5
        print(f"grip {g:.1f} -> {'HELD' if rec['held'] else 'EMPTY'}")
        if rec["held"]:
            goto(robot, kin, [cmd[0], cmd[1], zt + 0.12], gripper=0)
            cv2.imwrite(str(DEBUG / "pick_board_held.jpg"), grab(calib["camera_index"]))
            time.sleep(1.0)
            goto(robot, kin, [cmd[0], cmd[1], zt + 0.018], 0.25, gripper=0)
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
