"""Pick-and-place cycles: mat -> glass bowl -> mat, driven by ER 2 + wrist servo.

Usage: cycle.py [--cycles 3] [--block "..."] [--bowl "..."]

Per cycle:
  1. pick the block from the mat   (coarse ER -> wrist servo -> grasp)
  2. carry above the bowl, wrist-servo onto the bowl itself, drop in from above the rim
  3. pick the block OUT of the bowl (servo at rim-safe hover, descend inside)
  4. return it to its original mat spot

All lateral transits run at a rim-clearing safe height. ER verify per pick is
logged as advisory (it has produced false negatives), never used to abort.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

import arm
from capture import grab
from er_client import ask, point_at

CALIB = Path(__file__).resolve().parent / "calib.json"
DEBUG = Path(__file__).resolve().parent / "debug"


def load():
    c = json.loads(CALIB.read_text())
    c["H"] = np.array(c["H"])
    return c


def px2world(H, px, py):
    v = H @ np.array([px, py, 1.0])
    return v[:2] / v[2]


def coarse_locate(calib, desc, tag):
    fpath = str(DEBUG / f"coarse_{tag}.jpg")
    cv2.imwrite(fpath, grab(calib["camera_index"]))
    pts = point_at(fpath, f"the exact point where {desc} touches the black mat — its bottom contact edge")
    if not pts:
        raise SystemExit(f"coarse: ER could not find {desc}")
    x, y = px2world(calib["H"], pts[0]["x"], pts[0]["y"])
    print(f"[coarse] {desc}: ({x:.4f},{y:.4f})")
    return float(x), float(y)


def wrist_servo(robot, kin, calib, task, gx, gy, z, thresh=25, rounds=6, tag=""):
    """Center `task` under the jaws at height z.
    Returns (gx, gy, final_err_px) — callers must not descend on a large error."""
    w = calib["wrist"]
    A_inv = np.linalg.inv(np.array(w["A"]))
    gc = np.array(w["grasp_center"])
    best = (np.inf, gx, gy)
    template = None
    for r in range(rounds):
        time.sleep(0.7)
        frame = grab(w["camera_index"])
        cv2.imwrite(str(DEBUG / f"servo_{tag}_{r}.jpg"), frame)
        loc = None
        if template is not None:
            res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
            _, conf, _, tl = cv2.minMaxLoc(res)
            if conf > 0.5:
                loc = (tl[0] + template.shape[1] // 2, tl[1] + template.shape[0] // 2)
        if loc is None:
            for _ in range(2):
                pts = point_at(str(DEBUG / f"servo_{tag}_{r}.jpg"), task)
                # coarse already put the target near the jaws — a point at the frame
                # edge is another object (the box rim hijacked us once)
                if pts and np.linalg.norm(np.array([pts[0]["x"], pts[0]["y"]]) - gc) < 250:
                    loc = (pts[0]["x"], pts[0]["y"])
                    break
                pts = None
            if loc is None:
                print(f"[servo {tag}] no trustworthy target in view")
                break
            x0, y0 = int(loc[0]), int(loc[1])
            template = frame[max(0, y0 - 45): y0 + 45, max(0, x0 - 45): x0 + 45]
        err = np.array(loc, dtype=float) - gc
        d = -(A_inv @ err)
        e = float(np.linalg.norm(err))
        print(f"[servo {tag}] {r+1}: err ({err[0]:+.0f},{err[1]:+.0f}) px, |{e:.0f}|")
        if e < best[0]:
            best = (e, gx, gy)
        if e < thresh:
            return gx, gy, e
        if np.linalg.norm(d) > 0.06:
            break
        gain = 0.5 if e > 150 else 0.35  # bigger first strides from far starts
        gx, gy = gx + gain * d[0], gy + gain * d[1]
        arm.settle_to(kin, robot, [gx, gy, z])
    if np.isfinite(best[0]):
        gx, gy = best[1], best[2]
        arm.settle_to(kin, robot, [gx, gy, z])
    return gx, gy, float(best[0])


def gripper_pos(robot):
    obs = robot.get_observation()
    return float(obs["gripper.pos"])


def grasped(robot, close_target, min_gap=3.5):
    """Proprioceptive grasp check: jaws closing on an object stall ABOVE the
    close target; an empty close reaches it. Free, instant, no vision."""
    g = gripper_pos(robot)
    held = g > close_target + min_gap
    print(f"[grasp check] gripper at {g:.1f} (close target {close_target}) -> {'HELD' if held else 'EMPTY'}")
    return held


def goto(robot, kin, xyz, sec_per_step=0.15, gripper=None):
    t = np.asarray(xyz, dtype=float)
    if not ((arm.EE_MIN <= t) & (t <= arm.EE_MAX)).all():
        raise SystemExit(f"REFUSED: {xyz} outside EE box")
    cur = arm.joints_deg(robot)
    path = arm.plan_line(kin, cur, kin.forward_kinematics(cur)[:3, 3], xyz)
    arm.follow_path(robot, path, sec_per_step, gripper=gripper)
    arm.settle_to(kin, robot, xyz)


def verify(calib, what, tag):
    fpath = str(DEBUG / f"verify_{tag}.jpg")
    cv2.imwrite(fpath, grab(calib["camera_index"]))
    v = ask(fpath, f"Look at the robot arm's gripper. Is a {what} visible held between its jaw "
                   "fingers (lifted off the surface)? Answer only YES or NO.")
    print(f"[verify {tag}] {'HELD' if 'YES' in v.upper() else 'not confirmed'} ({v!r})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--block", default="the small white plastic block")
    ap.add_argument("--bowl", default="the translucent plastic box")
    ap.add_argument("--open", dest="open_", type=float, default=80)
    ap.add_argument("--close", type=float, default=0)  # grip test: empty closes to 1.0, block stalls at ~6.6
    args = ap.parse_args()

    DEBUG.mkdir(exist_ok=True)
    calib = load()
    zt = calib["z_table"]
    z_hover, z_grasp = zt + 0.08, zt + 0.015
    z_safe = zt + 0.16            # clears the box rim laterally (box ~7 cm tall)
    z_rim_hover = zt + 0.12       # servo height above the container
    z_drop = zt + 0.10            # release above the rim, block falls in
    z_bowl_grasp = zt + 0.035     # container floor + lying block
    home = np.array(calib["home_joints"])

    block_xy = coarse_locate(calib, "the white plastic block", "block")

    kin = arm.kinematics_standalone()
    robot = arm.connect()
    kin_r = arm.kinematics(robot)
    try:
        def attempt_pick(cx, cy, hover_z, grasp_z, tag, container_guard=False):
            """servo -> descend -> close -> proprioceptive check. Retries once.
            container_guard: after a HELD close, lift 3 cm and ask ER whether the
            CONTAINER is coming up too (we once abducted the box); if so, release
            and retry. Returns (held, x, y); on failure the arm ends at hover_z."""
            for tries in range(2):
                goto(robot, kin_r, [cx, cy, hover_z], gripper=args.open_)
                cx, cy, e = wrist_servo(robot, kin_r, calib, args.block, cx, cy, hover_z,
                                        tag=f"{tag}t{tries}")
                if e > 60:
                    print(f"[{tag}] servo did not converge ({e:.0f} px) — not descending")
                    continue
                goto(robot, kin_r, [cx, cy, grasp_z], 0.25, gripper=args.open_)
                print("close")
                arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=args.close)
                time.sleep(0.4)
                if grasped(robot, args.close):
                    if container_guard:
                        goto(robot, kin_r, [cx, cy, grasp_z + 0.03], 0.3, gripper=args.close)
                        fpath = str(DEBUG / f"guard_{tag}.jpg")
                        cv2.imwrite(fpath, grab(calib["camera_index"]))
                        v = ask(fpath, f"Is the robot gripper lifting or tilting {args.bowl} "
                                       "itself (the container, not just the small block)? Answer only YES or NO.")
                        if "YES" in v.upper():
                            print(f"[{tag}] GUARD: holding the container — releasing")
                            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
                            continue
                    goto(robot, kin_r, [cx, cy, z_safe], gripper=args.close)
                    return True, cx, cy
                print(f"[{tag}] empty jaws — reopening and retrying")
                arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
            goto(robot, kin_r, [cx, cy, hover_z], gripper=args.open_)
            return False, cx, cy

        arm.move_joints(robot, home, 2.5, gripper=args.open_)
        for c in range(args.cycles):
            print(f"===== cycle {c+1}/{args.cycles} =====")
            # 1. pick from mat (gated: never approach the bowl empty-handed)
            held, gx, gy = attempt_pick(*block_xy, z_hover, z_grasp, f"c{c}pick")
            if not held:
                print("ABORT cycle: could not grasp the block from the mat")
                break
            verify(calib, "small white object", f"c{c}_pick")

            # 2. drop into the container (located FRESH — it moves).
            # Aim at the CENTER of the opening, not the contact edge — the edge
            # prompt put drops on the rim.
            bx, by = coarse_locate(calib, args.bowl, f"c{c}_container")
            goto(robot, kin_r, [bx, by, z_safe], gripper=args.close)
            bx, by, be = wrist_servo(robot, kin_r, calib,
                                     f"the center of the open top of {args.bowl}",
                                     bx, by, z_safe, thresh=35, rounds=8, tag=f"c{c}bowl")
            if be > 80:
                print("container servo did not converge — dropping anyway would hit the rim; skipping to retry")
                block_xy = (gx, gy)  # still holding the block; put it back down
                goto(robot, kin_r, [gx, gy, z_hover], gripper=args.close)
                goto(robot, kin_r, [gx, gy, z_grasp + 0.02], 0.25, gripper=args.close)
                arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
                goto(robot, kin_r, [gx, gy, z_hover], gripper=args.open_)
                continue
            goto(robot, kin_r, [bx, by, z_drop], 0.25, gripper=args.close)
            print("release into container")
            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
            time.sleep(0.4)
            goto(robot, kin_r, [bx, by, z_safe], gripper=args.open_)

            # gate stage 3 on the drop actually having landed inside
            dpath = str(DEBUG / f"drop_{c}.jpg")
            cv2.imwrite(dpath, grab(calib["camera_index"]))
            v = ask(dpath, f"Is {args.block} inside {args.bowl}? Answer only YES or NO.")
            if "YES" not in v.upper():
                print("drop missed the container — re-picking from wherever it landed")
                block_xy = coarse_locate(calib, "the white plastic block", f"c{c}_missed")
                continue  # restart the cycle from the pick

            # 3. pick out of the container (fresh location, rim-safe hover, box-theft guard)
            bx, by = coarse_locate(calib, args.bowl, f"c{c}_container2")
            held, bx2, by2 = attempt_pick(bx, by, z_rim_hover, z_bowl_grasp, f"c{c}out",
                                          container_guard=True)
            if not held:
                print("ABORT cycle: could not grasp the block out of the container — leaving it there")
                break
            verify(calib, "small white object", f"c{c}_out")

            # 4. return to the mat spot
            gx, gy = block_xy
            goto(robot, kin_r, [gx, gy, z_safe], gripper=args.close)
            goto(robot, kin_r, [gx, gy, zt + 0.05], 0.25, gripper=args.close)
            print("release on mat")
            arm.move_joints(robot, arm.joints_deg(robot), 0.8, gripper=args.open_)
            time.sleep(0.3)
            goto(robot, kin_r, [gx, gy, z_hover], gripper=args.open_)
        arm.move_joints(robot, home, 2.5)
        print("all cycles done")
    finally:
        robot.disconnect()
        print("robot disconnected (torque off).")


if __name__ == "__main__":
    main()
