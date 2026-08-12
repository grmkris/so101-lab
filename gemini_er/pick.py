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
    ap.add_argument("--grasp", type=float, default=0.015)
    ap.add_argument("--open", dest="open_", type=float, default=80)
    ap.add_argument("--close", type=float, default=5)
    ap.add_argument("--seconds", type=float, default=2.5)
    ap.add_argument("--no-servo", action="store_true",
                    help="skip the wrist-cam fine stage (coarse only)")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the ER grasp verification after lift")
    ap.add_argument("--no-descend", action="store_true",
                    help="servo convergence test only: stop after the fine stage, return home")
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

    # -- plan (IK continuation from home; no arm needed for dry-run) ----------
    kin = arm.kinematics_standalone()
    for xyz in ([x, y, z_hover], [x, y, z_grasp]):
        t = np.asarray(xyz)
        if not ((arm.EE_MIN <= t) & (t <= arm.EE_MAX)).all():
            sys.exit(f"REFUSED: {xyz} outside EE box")
    home_xyz = kin.forward_kinematics(home)[:3, 3]
    approach = arm.plan_line(kin, home, home_xyz, [x, y, z_hover])
    descend = arm.plan_line(kin, approach[-1], [x, y, z_hover], [x, y, z_grasp], step_m=0.005)
    j_hover, j_grasp = approach[-1], descend[-1]
    reach_err = np.linalg.norm(kin.forward_kinematics(j_grasp)[:3, 3] - [x, y, z_grasp])
    worst_jump = max(arm.max_step_deg(approach), arm.max_step_deg(descend))
    print(f"waypoints (deg):\n  home  {np.round(home, 1)}\n  hover {np.round(j_hover, 1)}\n  grasp {np.round(j_grasp, 1)}")
    print(f"IK reach error at grasp: {reach_err*100:.2f} cm, worst joint step: {worst_jump:.1f} deg "
          f"({len(approach)}+{len(descend)} path points)")
    if reach_err > 0.02:
        sys.exit("REFUSED: IK cannot reach target within 2 cm — likely outside workspace")
    if worst_jump > 25.0:
        sys.exit("REFUSED: joint jump > 25 deg along path — IK branch flip, unsafe to interpolate")

    if args.dry_run:
        print("dry run — no motion.")
        return

    # -- execute ---------------------------------------------------------------
    robot = arm.connect()
    try:
        import time

        print("-> home");  arm.move_joints(robot, home, args.seconds, gripper=args.open_)
        print("-> hover"); arm.follow_path(robot, approach, 0.15, gripper=args.open_)
        arm.settle_to(kin, robot, [x, y, z_hover])

        # -- fine stage: wrist-cam servo at hover (see wrist_calibrate.py) ----
        gx, gy = x, y
        wrist = calib.get("wrist")
        if not args.no_servo and args.task and wrist:
            from capture import grab
            from er_client import point_at

            A_inv = np.linalg.inv(np.array(wrist["A"]))
            gc = np.array(wrist["grasp_center"])
            debug_dir = Path(__file__).resolve().parent / "debug"
            debug_dir.mkdir(exist_ok=True)
            best = (np.inf, gx, gy)
            template = None
            for round_ in range(6):
                time.sleep(0.7)
                fpath = str(debug_dir / f"servo_{round_}.jpg")
                frame = grab(wrist["camera_index"])
                cv2.imwrite(fpath, frame)
                # ER once for semantics; template tracking after that for precision
                # (ER re-points at a slightly different spot each call — ~1 cm jitter)
                loc = None
                if template is not None:
                    res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
                    _, conf, _, top_left = cv2.minMaxLoc(res)
                    if conf > 0.5:
                        loc = (top_left[0] + template.shape[1] // 2,
                               top_left[1] + template.shape[0] // 2)
                if loc is None:
                    pts = point_at(fpath, args.task)
                    if not pts:  # ER flakes occasionally on a clean frame — one retry
                        cv2.imwrite(fpath, grab(wrist["camera_index"]))
                        pts = point_at(fpath, args.task)
                    if not pts:
                        print("servo: target not in wrist view — keeping current position")
                        break
                    loc = (pts[0]["x"], pts[0]["y"])
                    x0, y0, half = int(loc[0]), int(loc[1]), 45
                    template = frame[max(0, y0 - half): y0 + half, max(0, x0 - half): x0 + half]
                err_px = np.array(loc) - gc
                # object must SHIFT by -err in the image; A maps arm motion -> object pixel shift
                d = -(A_inv @ err_px)
                e = np.linalg.norm(err_px)
                print(f"servo {round_+1}: err ({err_px[0]:+.0f},{err_px[1]:+.0f}) px "
                      f"-> move ({d[0]*100:+.1f},{d[1]*100:+.1f}) cm")
                if e < best[0]:
                    best = (e, gx, gy)
                if e < 12:
                    print("servo: converged")
                    break
                if np.linalg.norm(d) > 0.06:
                    print("servo: correction > 6 cm, not trusting it — stopping")
                    break
                nx, ny = gx + 0.6 * d[0], gy + 0.6 * d[1]
                # servo steps are visually grounded — allow a wider margin than coarse
                if not in_bounds(calib, nx, ny, margin=0.05):
                    print("servo: corrected target out of bounds — stopping")
                    break
                gx, gy = nx, ny
                arm.settle_to(kin, robot, [gx, gy, z_hover])
            if np.isfinite(best[0]) and (gx, gy) != best[1:]:
                gx, gy = best[1], best[2]
                print(f"servo: settling at best position (err {best[0]:.0f} px)")
                arm.settle_to(kin, robot, [gx, gy, z_hover])
        elif not args.no_servo and args.task:
            print("servo: no wrist calibration in calib.json — run wrist_calibrate.py (coarse only)")

        if args.no_descend:
            print("-> no-descend: returning home")
            arm.follow_path(robot, approach[::-1], 0.15, gripper=args.open_)
            return

        # -- descend at the (possibly corrected) xy ---------------------------
        cur = arm.joints_deg(robot)
        down = arm.plan_line(kin, cur, kin.forward_kinematics(cur)[:3, 3], [gx, gy, z_grasp], step_m=0.005)
        print("-> descend"); arm.follow_path(robot, down, 0.25, gripper=args.open_)
        fk_err = arm.settle_to(kin, robot, [gx, gy, z_grasp])
        print(f"-> settled, residual FK error {fk_err*100:.2f} cm")
        j_grasp = arm.joints_deg(robot)

        print("-> close"); arm.move_joints(robot, j_grasp, 1.0, gripper=args.close)
        time.sleep(0.4)  # let the squeeze settle before the lift
        print("-> lift");  arm.follow_path(robot, down[::-1], 0.15, gripper=args.close)
        print("-> home");  arm.follow_path(robot, approach[::-1], 0.15, gripper=args.close)

        if not args.no_verify and args.task:
            from capture import grab as _grab
            from er_client import ask

            time.sleep(0.7)
            vpath = str(Path(__file__).resolve().parent / "debug" / "verify.jpg")
            Path(vpath).parent.mkdir(exist_ok=True)
            cv2.imwrite(vpath, _grab(cam))  # workspace cam sees the gripper at home
            verdict = ask(vpath, f"Is {args.task} currently held between the robot gripper jaws? Answer only YES or NO.")
            print(f"GRASP {'SUCCESS' if 'YES' in verdict.upper() else 'FAIL'} (ER verdict: {verdict!r})")

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
