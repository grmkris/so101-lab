"""Language -> Gemini Robotics-ER 2 point -> homography -> scripted IK pick.

Usage (driver venv python):
  pick.py --dry-run --xy 0.22 0.05      # IK targets printed, NO arm connection
  pick.py --xy 0.22 0.05                # pick at workspace coords (metres)
  pick.py --task "the white block"      # ER 2 picks the pixel from a fresh frame
  pick.py --task "..." --dry-run        # ER + overlay only, no motion

Flags: --cam (default from calib.json) --hover 0.08 --grasp 0.02
       --open 80 --close 20 --seconds 2.5
Safety: max_relative_target=15 clamp, joint-space interpolation, EE-box +
calibrated-rectangle bounds check before any motion. Ctrl-C safe (finally
disconnect -> torque off). Stay within reach of the arm.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import arm

CALIB_PATH = Path(__file__).resolve().parent / "calib.json"
OVERLAY_PATH = Path(__file__).resolve().parent / "last_pick_overlay.jpg"


def load_calib():
    c = json.loads(CALIB_PATH.read_text())
    c["H"] = np.array(c["H"])
    return c


def pixel_to_world(H, px, py):
    v = H @ np.array([px, py, 1.0])
    return v[:2] / v[2]


def in_bounds(calib, x, y, margin=0.02):
    pts = np.array([[p[2], p[3]] for p in calib["points"]])
    lo, hi = pts.min(axis=0) - margin, pts.max(axis=0) + margin
    return lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", help='e.g. "the white block"')
    ap.add_argument("--xy", nargs=2, type=float, help="workspace target in metres (skips ER)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cam", type=int, default=None)
    ap.add_argument("--hover", type=float, default=0.08)
    ap.add_argument("--grasp", type=float, default=0.02)
    ap.add_argument("--open", dest="open_", type=float, default=80)
    ap.add_argument("--close", type=float, default=20)
    ap.add_argument("--seconds", type=float, default=2.5)
    args = ap.parse_args()
    if not args.task and not args.xy:
        sys.exit("need --task or --xy")

    calib = load_calib()
    cam = args.cam if args.cam is not None else calib["camera_index"]

    # -- resolve target xy ----------------------------------------------------
    if args.xy:
        x, y = args.xy
        print(f"manual target: ({x:.4f}, {y:.4f})")
    else:
        from capture import grab
        from er_client import overlay, point_at

        frame_path = str(Path(__file__).resolve().parent / "last_frame.jpg")
        cv2.imwrite(frame_path, grab(cam))
        pts = point_at(frame_path, args.task)
        if not pts:
            sys.exit("ER 2 returned no points")
        p = pts[0]
        x, y = pixel_to_world(calib["H"], p["x"], p["y"])
        overlay(frame_path, pts, str(OVERLAY_PATH))
        print(f'ER point for "{args.task}": pixel ({p["x"]:.0f},{p["y"]:.0f}) -> world ({x:.4f},{y:.4f})')
        print(f"overlay: {OVERLAY_PATH}")

    if not in_bounds(calib, x, y):
        sys.exit(f"REFUSED: ({x:.3f},{y:.3f}) outside calibrated rectangle (+2cm margin)")

    z_hover = calib["z_table"] + args.hover
    z_grasp = calib["z_table"] + args.grasp
    home = np.array(calib["home_joints"])

    # -- plan waypoints (IK seeded from home; no arm needed for dry-run) ------
    kin = arm.kinematics_standalone()
    for xyz in ([x, y, z_hover], [x, y, z_grasp]):
        t = np.asarray(xyz)
        if not ((arm.EE_MIN <= t) & (t <= arm.EE_MAX)).all():
            sys.exit(f"REFUSED: {xyz} outside EE box")
    j_hover = arm.ik_to_xyz(kin, home, [x, y, z_hover])
    j_grasp = arm.ik_to_xyz(kin, j_hover, [x, y, z_grasp])
    # sanity: does IK actually reach the target?
    reach_err = np.linalg.norm(kin.forward_kinematics(j_grasp)[:3, 3] - [x, y, z_grasp])
    print(f"waypoints (deg):\n  home  {np.round(home, 1)}\n  hover {np.round(j_hover, 1)}\n  grasp {np.round(j_grasp, 1)}")
    print(f"IK reach error at grasp: {reach_err*100:.2f} cm")
    if reach_err > 0.02:
        sys.exit("REFUSED: IK cannot reach target within 2 cm — likely outside workspace")

    if args.dry_run:
        print("dry run — no motion.")
        return

    # -- execute ---------------------------------------------------------------
    robot = arm.connect()
    try:
        s = args.seconds
        print("-> home");  arm.move_joints(robot, home, s, gripper=args.open_)
        print("-> hover"); arm.move_joints(robot, j_hover, s, gripper=args.open_)
        print("-> descend"); arm.move_joints(robot, j_grasp, s, gripper=args.open_)
        print("-> close"); arm.move_joints(robot, j_grasp, 1.0, gripper=args.close)
        print("-> lift");  arm.move_joints(robot, j_hover, s, gripper=args.close)
        print("-> home");  arm.move_joints(robot, home, s, gripper=args.close)
        print("done — inspect the grasp, Ctrl-C or Enter to release + exit")
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=args.open_)
    finally:
        robot.disconnect()
        print("robot disconnected (torque off).")


if __name__ == "__main__":
    main()
