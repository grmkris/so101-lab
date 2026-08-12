"""Pick the block and place it on a target ChArUco square (the chess primitive).

Usage: move_board.py --square COL ROW   (5x7 board, 35 mm squares, 0-indexed)
Logs to debug/move_board.jsonl.
"""

import argparse
import json
import time

import cv2
import numpy as np

import arm
from capture import grab
from cycle import DEBUG, goto, load
from er_client import point_at

LOG = DEBUG / "move_board.jsonl"
SQ = 35.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--square", nargs=2, type=int, required=True, metavar=("COL", "ROW"))
    args = ap.parse_args()
    calib = load()
    board = calib.get("board") or exit("no board calibration — run board_calibrate.py")
    H = np.array(board["H"])
    A = np.array(board["affine"])
    zt = calib["z_table"]
    rec = {"t": time.strftime("%H:%M:%S"), "square": args.square}

    def board_pt(px, py):
        v = H @ np.array([px, py, 1.0])
        return v[:2] / v[2]

    def locate(tag):
        fpath = str(DEBUG / f"move_board_{tag}.jpg")
        cv2.imwrite(fpath, grab(calib["camera_index"]))
        pts = point_at(fpath, "the exact point where the small white plastic block touches the checkerboard paper (its bottom contact edge)")
        if not pts:
            return None
        edge = board_pt(pts[0]["x"], pts[0]["y"])
        up = board_pt(pts[0]["x"], pts[0]["y"] - 40.0)
        u = (up - edge) / np.linalg.norm(up - edge)
        return edge + u * 12.0

    dst = np.array([SQ / 2 + SQ * args.square[0], SQ / 2 + SQ * args.square[1]])
    place_cmd = A @ np.array([dst[0], dst[1], 1.0])
    rec["to_mm"] = [round(float(x), 1) for x in dst]
    rec["attempts"] = []

    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=80)
        rec["held"] = False
        for att in range(3):
            src = locate(f"pre{att}")
            if src is None:
                print("block not found")
                break
            pick_cmd = A @ np.array([src[0], src[1], 1.0])
            print(f"attempt {att}: board ({src[0]:.0f},{src[1]:.0f}) -> square {args.square} ({dst[0]:.0f},{dst[1]:.0f}) mm")
            goto(robot, kin, [pick_cmd[0], pick_cmd[1], zt + 0.08], gripper=80)
            goto(robot, kin, [pick_cmd[0], pick_cmd[1], zt + 0.015], 0.25, gripper=80)
            arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=0)
            time.sleep(0.4)
            g = float(arm.joints_deg(robot)[-1])
            rec["attempts"].append({"from_mm": [round(float(x), 1) for x in src], "grip": round(g, 1)})
            rec["held"] = g > 3.5
            print(f"grip {g:.1f} -> {'HELD' if rec['held'] else 'EMPTY'}")
            if rec["held"]:
                break
            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=80)
            goto(robot, kin, [pick_cmd[0], pick_cmd[1], zt + 0.08], gripper=80)
            arm.move_joints(robot, home, 2.0, gripper=80)
        if rec["held"]:
            goto(robot, kin, [pick_cmd[0], pick_cmd[1], zt + 0.08], gripper=0)
            goto(robot, kin, [place_cmd[0], place_cmd[1], zt + 0.08], gripper=0)
            goto(robot, kin, [place_cmd[0], place_cmd[1], zt + 0.014], 0.25, gripper=0)
            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=45)
            arm.move_joints(robot, arm.joints_deg(robot), 0.5, gripper=80)
            goto(robot, kin, [place_cmd[0], place_cmd[1], zt + 0.08], gripper=80)
        arm.move_joints(robot, home, 2.0, gripper=80)
        cv2.imwrite(str(DEBUG / "move_board_post.jpg"), grab(calib["camera_index"]))
    finally:
        robot.disconnect()

    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
