"""Push the block to --to X Y with bias-corrected nudge strokes (no wrist cam needed).

Uses the Phase-A touch_map.jsonl bias field: commanded = desired + (target-measured)
of the nearest mapped cell. Strokes approach from the far side and slide through.
Appends to debug/push_log.jsonl.
"""

import argparse
import json
import time

import numpy as np

import arm
from cycle import DEBUG, coarse_locate, goto, load
from pick import in_bounds

LOG = DEBUG / "push_log.jsonl"


def bias_field():
    recs = [json.loads(l) for l in open(DEBUG / "touch_map.jsonl") if "measured" in l]
    cells = [(np.array(r["target"]), np.array(r["target"]) - np.array(r["measured"])) for r in recs]
    def correction(p):
        p = np.asarray(p)
        w = np.array([1.0 / max(np.linalg.norm(c[0] - p), 0.01) ** 2 for c in cells])
        return np.average([c[1] for c in cells], axis=0, weights=w)
    return correction


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", nargs=2, type=float, required=True)
    ap.add_argument("--strokes", type=int, default=6)
    args = ap.parse_args()
    calib = load()
    zt = calib["z_table"]
    z_hover, z_push = zt + 0.06, zt + 0.012
    target = np.array(args.to)
    corr = bias_field()
    rec = {"t": time.strftime("%H:%M:%S"), "to": args.to, "path": []}

    if not in_bounds(calib, *target):
        rec["result"] = "target_out_of_bounds"
        print(json.dumps(rec))
        return

    block = np.array(coarse_locate(calib, "the white plastic block", "push_pre"))
    rec["from"] = [round(float(v), 4) for v in block]

    robot = arm.connect()
    kin = arm.kinematics(robot)
    try:
        home = np.array(calib["home_joints"])
        arm.move_joints(robot, home, 2.5, gripper=0)  # jaws closed = pushing tool
        for s in range(args.strokes):
            vec = target - block
            dist = float(np.linalg.norm(vec))
            rec["path"].append([round(float(v), 4) for v in block])
            if dist < 0.03:
                rec["result"] = "reached"
                break
            d = vec / dist
            c = corr(block)
            # shrink the run-up until it's inside the safe zone (min 1.5 cm)
            runup = 0.05
            while runup >= 0.015 and not in_bounds(calib, *(block - d * runup), margin=0.05):
                runup -= 0.01
            approach = block - d * runup + c
            through = block + d * min(dist, 0.04) + c
            if runup < 0.015 or not in_bounds(calib, *(through - c), margin=0.05):
                rec["result"] = "stroke_out_of_bounds"
                break
            goto(robot, kin, [approach[0], approach[1], z_hover])
            goto(robot, kin, [approach[0], approach[1], z_push], 0.25)
            goto(robot, kin, [through[0], through[1], z_push], 0.3)
            goto(robot, kin, [through[0], through[1], z_hover], 0.2)
            arm.move_joints(robot, home, 2.0)
            time.sleep(0.5)
            block = np.array(coarse_locate(calib, "the white plastic block", f"push_{s}"))
        else:
            rec["result"] = "strokes_exhausted"
        rec["final"] = [round(float(v), 4) for v in block]
        rec["final_err_cm"] = round(float(np.linalg.norm(target - block)) * 100, 1)
    finally:
        robot.disconnect()
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
