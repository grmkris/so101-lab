"""Interactive pixel->world calibration for the workspace camera.

Torque goes OFF at start — you hand-place the gripper TIP touching the table,
click that tip in the camera window, then press SPACE to record the pair.
Collect 5+ points spread across the pick area (corners matter — coverage lever).
Keys:
  click  mark the gripper tip pixel (crosshair shows the pending click)
  SPACE  record pair (pending click pixel + FK of current joints)
  h      record the CURRENT arm pose as the hover/home pose (do this with the
         arm held above the workspace, gripper roughly open)
  q/ESC  solve homography, save calib.json, exit

Usage: .../driver/.venv/bin/python calibrate.py [--cam 0]
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

import arm
import devices

CALIB_PATH = Path(__file__).resolve().parent / "calib.json"

_click = {"pt": None}


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        _click["pt"] = (x, y)


def _open(cam):
    """Open a camera by role name, device path, or legacy index — MJPG asserted.

    Not routed through `lab_cameras` because these scripts need an interactive
    cv2 window, which only exists in the GUI cv2 build (i.e. the Mac).
    """
    dev = devices.camera(cam)
    cap = cv2.VideoCapture(dev)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        raise SystemExit(f"cannot open camera {cam} ({dev})")
    return cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="workspace",
                    help="role name, /dev path, or legacy index")
    args = ap.parse_args()

    robot = arm.connect()
    robot.bus.disable_torque()
    print("Torque OFF — arm is limp, hand-guide it. Support it so it can't fall.")
    kin = arm.kinematics(robot)

    cap = _open(args.cam)

    pairs = []  # (px, py, X, Y, Z)
    home = None
    win = "calibrate — click tip, SPACE record, h home, q quit"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            disp = frame.copy()
            if _click["pt"]:
                cv2.drawMarker(disp, _click["pt"], (0, 255, 0), cv2.MARKER_CROSS, 24, 2)
            for px, py, X, Y, Z in pairs:
                cv2.circle(disp, (int(px), int(py)), 5, (0, 0, 255), -1)
            cv2.putText(
                disp,
                f"pairs: {len(pairs)}  home: {'SET' if home is not None else 'not set'}",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
            )
            cv2.imshow(win, disp)
            k = cv2.waitKey(30) & 0xFF

            if k == ord(" "):
                if _click["pt"] is None:
                    print("click the gripper tip first")
                    continue
                j = arm.joints_deg(robot)
                T = kin.forward_kinematics(j)
                X, Y, Z = T[:3, 3]
                px, py = _click["pt"]
                pairs.append((px, py, float(X), float(Y), float(Z)))
                _click["pt"] = None
                print(f"recorded #{len(pairs)}: pixel ({px},{py}) -> world ({X:.4f},{Y:.4f},{Z:.4f})")
            elif k == ord("h"):
                home = arm.joints_deg(robot).tolist()
                print(f"home pose recorded: {[round(v, 1) for v in home]}")
            elif k in (ord("q"), 27):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        robot.disconnect()
        print("robot disconnected (torque off).")

    if len(pairs) < 4:
        print(f"only {len(pairs)} pairs — need >= 4, nothing saved.")
        return
    if home is None:
        print("WARNING: no home pose recorded (press h next time) — nothing saved.")
        return

    pix = np.array([[p[0], p[1]] for p in pairs], dtype=np.float64)
    world = np.array([[p[2], p[3]] for p in pairs], dtype=np.float64)
    H, _ = cv2.findHomography(pix, world)

    # leave-one-out reprojection check when we have points to spare
    if len(pairs) >= 5:
        errs = []
        for i in range(len(pairs)):
            keep = [j for j in range(len(pairs)) if j != i]
            Hi, _ = cv2.findHomography(pix[keep], world[keep])
            v = Hi @ np.array([pix[i][0], pix[i][1], 1.0])
            errs.append(float(np.linalg.norm(v[:2] / v[2] - world[i])))
        print(f"leave-one-out reprojection error: mean {np.mean(errs)*100:.2f} cm, max {np.max(errs)*100:.2f} cm")

    z_table = float(np.mean([p[4] for p in pairs]))
    calib = {
        "H": H.tolist(),
        "z_table": z_table,
        "home_joints": home,
        "points": pairs,
        "camera_index": args.cam,
        "image_size": [640, 480],
        "created": time.strftime("%Y-%m-%d %H:%M"),
    }
    CALIB_PATH.write_text(json.dumps(calib, indent=2))
    print(f"saved {CALIB_PATH}  (z_table {z_table:.4f} m, {len(pairs)} points)")


if __name__ == "__main__":
    main()
