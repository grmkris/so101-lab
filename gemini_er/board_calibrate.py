"""ChArUco-board calibration with arm self-registration (no ruler needed).

1. Detect the printed board (5x7, 35 mm squares, 26 mm markers, DICT_4X4_250)
   in the workspace cam -> homography pixel -> board-mm.
2. Command the arm to 4 spread touch points, photograph each, ER-point the tip,
   convert to board-mm.
3. Fit affine board-mm -> arm-command coordinates. The affine absorbs droop,
   board placement, print scale, everything systematic.
4. Save {"board": {"H": ..., "affine": ...}} into calib.json.

Usage: board_calibrate.py
"""

import json
import time

import cv2
import numpy as np

import arm
from capture import grab
from cycle import DEBUG, load
from er_client import point_at

CALIB_PATH = __import__("pathlib").Path(__file__).resolve().parent / "calib.json"

SQUARES = (5, 7)
SQUARE_M = 0.035
MARKER_M = 0.026


def detect_board(frame, tag):
    dic = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
    board = cv2.aruco.CharucoBoard(SQUARES, SQUARE_M, MARKER_M, dic)
    det = cv2.aruco.CharucoDetector(board)
    corners, ids, _, _ = det.detectBoard(frame)
    if corners is None or len(corners) < 8:
        raise SystemExit(f"board detection failed ({0 if corners is None else len(corners)} corners) — check view")
    all_obj = board.getChessboardCorners()  # (N,3) board metres
    obj = np.array([all_obj[i][:2] for i in ids.flatten()])
    pix = corners.reshape(-1, 2)
    H, _ = cv2.findHomography(pix, obj * 1000.0)  # pixel -> board mm
    disp = frame.copy()
    for p in pix:
        cv2.circle(disp, (int(p[0]), int(p[1])), 4, (0, 0, 255), -1)
    cv2.imwrite(str(DEBUG / f"board_{tag}.jpg"), disp)
    print(f"board: {len(pix)} corners detected")
    return H


def pix_to_board(H, px, py):
    v = H @ np.array([px, py, 1.0])
    return v[:2] / v[2]


def main():
    DEBUG.mkdir(exist_ok=True)
    calib = load()
    zt = calib["z_table"]
    cam = calib["camera_index"]

    H = detect_board(grab(cam), "detect")

    # spread arm-frame touch targets, shifted +2 cm x because the arm lands
    # ~3-4 cm short (touch_map) — the ACTUAL touches must land on the board
    targets = [(0.15, -0.10), (0.22, -0.10), (0.15, -0.02), (0.22, -0.02), (0.185, -0.06)]
    pairs = []
    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=20)
        for tx, ty in targets:
            cur = arm.joints_deg(robot)
            path = arm.plan_line(kin, cur, kin.forward_kinematics(cur)[:3, 3], [tx, ty, zt + 0.008])
            if arm.max_step_deg(path) > 25:
                print(f"({tx},{ty}) branch flip — skipping")
                continue
            arm.follow_path(robot, path, 0.15, gripper=20)
            arm.settle_to(kin, robot, [tx, ty, zt + 0.008])
            time.sleep(0.8)
            fpath = str(DEBUG / f"reg_{tx}_{ty}.jpg")
            cv2.imwrite(fpath, grab(cam))
            arm.follow_path(robot, path[::-1], 0.12, gripper=20)
            pts = point_at(fpath, "the very tip of the robot gripper jaws near the checkerboard paper")
            if not pts:
                print(f"({tx},{ty}) tip not found — skipping")
                continue
            bx, by = pix_to_board(H, pts[0]["x"], pts[0]["y"])
            pairs.append(((bx, by), (tx, ty)))
            print(f"cmd ({tx},{ty}) -> board ({bx:.0f},{by:.0f}) mm")
        arm.move_joints(robot, home, 2.0)
    finally:
        robot.disconnect()

    if len(pairs) < 3:
        raise SystemExit(f"only {len(pairs)} registration pairs — need >= 3")
    src = np.array([p[0] for p in pairs], dtype=np.float64)  # board mm
    dst = np.array([p[1] for p in pairs], dtype=np.float64)  # arm cmd
    A, _ = cv2.estimateAffine2D(src.reshape(-1, 1, 2), dst.reshape(-1, 1, 2))
    res = [float(np.linalg.norm((A @ np.array([*s, 1.0])) - d)) for s, d in zip(src, dst)]
    print(f"affine residuals: {[round(r*100,2) for r in res]} cm")

    calib_raw = json.loads(CALIB_PATH.read_text())
    calib_raw["board"] = {
        "H": H.tolist(),
        "affine": A.tolist(),
        "residuals_cm": [round(r * 100, 2) for r in res],
        "created": time.strftime("%Y-%m-%d %H:%M"),
    }
    CALIB_PATH.write_text(json.dumps(calib_raw, indent=2))
    print(f"saved board calibration ({len(pairs)} pairs)")


if __name__ == "__main__":
    main()
