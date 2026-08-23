"""Wrist-cam servo calibration: grasp_center pixel + pixel->metre jog matrix A.

Interactive (~3 min, you at the arm):
1. Torque goes OFF. Hand-place the jaws directly AROUND a small test object at
   grasp height (object centered between the jaw tips). Press Enter.
2. Torque on; the arm lifts straight up to hover height. The wrist cam then
   photographs the object — its pixel = grasp_center.
3. The arm auto-jogs +2 cm x and +2 cm y; the object's pixel is tracked across
   jogs (template match, ER fallback) — solves A (px per metre).
4. Saves under "wrist" in calib.json.

Usage: wrist_calibrate.py --wrist-cam 1 [--hover 0.08]
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

import arm
import devices
from capture import grab

CALIB_PATH = Path(__file__).resolve().parent / "calib.json"
DEBUG_DIR = Path(__file__).resolve().parent / "debug"


def find_patch(frame, template):
    res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, conf, _, loc = cv2.minMaxLoc(res)
    cx, cy = loc[0] + template.shape[1] // 2, loc[1] + template.shape[0] // 2
    return (cx, cy), conf


def er_point(frame_path, desc):
    from er_client import point_at

    pts = point_at(frame_path, desc)
    return (pts[0]["x"], pts[0]["y"]) if pts else None


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
    ap.add_argument("--wrist-cam", default="wrist",
                    help="role name, /dev path, or legacy index")
    ap.add_argument("--hover", type=float, default=0.08)
    ap.add_argument("--object", default="the small test object on the black mat")
    ap.add_argument("--center-only", action="store_true",
                    help="redo grasp_center only, keep the existing jog matrix A")
    args = ap.parse_args()

    DEBUG_DIR.mkdir(exist_ok=True)
    calib = json.loads(CALIB_PATH.read_text())
    z_hover = calib["z_table"] + args.hover

    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        robot.bus.disable_torque()
        print("Torque OFF. Hand-place the jaws AROUND the test object at grasp height, "
              "then press SPACE in the preview window.")
        cap = _open(args.wrist_cam)
        win = "wrist view — jaws around object, then SPACE"
        cv2.namedWindow(win)
        try:
            while True:
                ok, f = cap.read()
                if ok:
                    cv2.imshow(win, f)
                if cv2.waitKey(30) & 0xFF == ord(" "):
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()
        j0 = arm.joints_deg(robot)
        p0 = kin.forward_kinematics(j0)[:3, 3]
        print(f"grasp pose recorded, EE at {np.round(p0, 4)}")

        # torque back on and open the jaws WIDE as the FIRST action — j0's own
        # gripper value is whatever the hand-placement left (often nearly
        # closed), so commanding plain j0 pinches the block and the lift
        # carries it wedged between the fingers (zero parallax, garbage A).
        robot.bus.enable_torque()
        arm.move_joints(robot, j0, 1.5, gripper=90)
        hover_xyz = [p0[0], p0[1], z_hover]
        # gripper=90 on every streamed point — path points carry the IK seed's
        # (nearly closed) gripper value and would re-grab the block mid-lift
        arm.follow_path(robot, arm.plan_line(kin, j0, p0, hover_xyz), 0.2, gripper=90)
        arm.settle_to(kin, robot, hover_xyz)
        time.sleep(0.8)

        # grasp_center: where the object (now directly under the jaw axis) appears
        frame = grab(args.wrist_cam)
        f0_path = str(DEBUG_DIR / "wrist_calib_0.jpg")
        cv2.imwrite(f0_path, frame)
        gc = er_point(f0_path, args.object)
        if gc is None:
            raise SystemExit("ER could not find the object in the wrist frame — check the view/replug")
        gc = (float(gc[0]), float(gc[1]))
        print(f"grasp_center = ({gc[0]:.0f}, {gc[1]:.0f})")

        if args.center_only:
            if "wrist" not in calib:
                raise SystemExit("--center-only but no wrist block in calib.json — run full calibration")
            calib["wrist"]["grasp_center"] = [gc[0], gc[1]]
            calib["wrist"]["created"] = time.strftime("%Y-%m-%d %H:%M")
            CALIB_PATH.write_text(json.dumps(calib, indent=2))
            print(f"grasp_center updated in {CALIB_PATH} (A kept)")
            return

        half = 40
        x0, y0 = int(gc[0]), int(gc[1])
        template = frame[max(0, y0 - half) : y0 + half, max(0, x0 - half) : x0 + half]

        # jog +2cm in x, then +2cm in y; track pixel motion
        deltas_m = [(0.02, 0.0), (0.0, 0.02)]
        cols = []
        for k, (dx, dy) in enumerate(deltas_m):
            arm.settle_to(kin, robot, [hover_xyz[0] + dx, hover_xyz[1] + dy, z_hover])
            time.sleep(0.8)
            f = grab(args.wrist_cam)
            fpath = str(DEBUG_DIR / f"wrist_calib_{k+1}.jpg")
            cv2.imwrite(fpath, f)
            (px, py), conf = find_patch(f, template)
            if conf < 0.5:
                print(f"template match weak ({conf:.2f}) — falling back to ER")
                p = er_point(fpath, args.object)
                if p is None:
                    raise SystemExit("lost the object during jog — retry")
                px, py = p
            # object is FIXED; camera moved with the arm — pixel shift per metre of arm motion
            shift = np.hypot(px - gc[0], py - gc[1])
            if shift < 20:
                raise SystemExit(
                    f"jog moved the image only {shift:.0f}px — the object is riding on the "
                    "gripper (or tracking failed). Free the block and retry."
                )
            jog = dx or dy
            cols.append([(px - gc[0]) / jog, (py - gc[1]) / jog])
            print(f"jog {k+1}: pixel ({px:.0f},{py:.0f}), shift ({px-gc[0]:+.0f},{py-gc[1]:+.0f}) px / 2cm, conf {conf:.2f}")
            arm.settle_to(kin, robot, hover_xyz)  # back to start between jogs
            time.sleep(0.4)

        # A: d_pixel = A @ d_xy_metres  (columns = response to x-jog, y-jog)
        A = np.array(cols).T
        det = np.linalg.det(A)
        print(f"A = {np.round(A, 1).tolist()}, det = {det:.0f}")
        if abs(det) < 1e3:
            raise SystemExit("A is near-singular — jogs didn't move the image enough, retry")

        calib["wrist"] = {
            "grasp_center": [gc[0], gc[1]],
            "A": A.tolist(),
            "hover": args.hover,
            "camera_index": args.wrist_cam,
            "created": time.strftime("%Y-%m-%d %H:%M"),
        }
        CALIB_PATH.write_text(json.dumps(calib, indent=2))
        print(f"saved wrist block to {CALIB_PATH}")
    finally:
        robot.disconnect()
        print("robot disconnected (torque off).")


if __name__ == "__main__":
    main()
