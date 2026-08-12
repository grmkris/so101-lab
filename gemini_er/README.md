# gemini_er — Gemini Robotics-ER 2 as a brain for the SO-101

Language command → ER 2 points at the target in the workspace cam →
pixel→world homography → IK pick primitive. Plan-then-act, not closed-loop.

## Env
Everything runs with the driver venv (GUI cv2 + placo + lerobot 0.6.0):

```bash
PY=../../eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python
export GEMINI_API_KEY=...   # free: https://aistudio.google.com/apikey
```

(Gemini CLI OAuth died with the Antigravity migration — API key only.)

## Order of operations
```bash
# 0. verify camera indexes EVERY session (macOS shuffles on replug)
$PY capture.py 0 /tmp/check.jpg && open /tmp/check.jpg

# 1. vision-only smoke test — no arm risk
$PY er_client.py /tmp/check.jpg "the glass bowl" /tmp/overlay.jpg && open /tmp/overlay.jpg

# 2. calibrate (interactive: hand-place tip, click, SPACE; h = home pose; q = save)
$PY calibrate.py --cam 0

# 3. pick primitive without ER, dry first, then live (no object, then object)
$PY pick.py --dry-run --xy 0.22 0.00
$PY pick.py --xy 0.22 0.00

# 4. full loop
$PY pick.py --task "the white block" --dry-run   # overlay only
$PY pick.py --task "the white block"
```

## Files
- `arm.py` — connect (max_relative_target=15 clamp), FK/IK (placo via lerobot
  `RobotKinematics`, URDF from `../phone_teleop/SO101/`), joint-space
  interpolated moves @30 Hz.
- `capture.py` — one frame by index.
- `er_client.py` — `gemini-robotics-er-2-preview` REST; points come back
  `[y,x]` normalized 0–1000, converted to pixels; `overlay()` for eyeballing.
- `calibrate.py` — arm-as-ground-truth homography (torque off, tip on table,
  click + SPACE ×5+), leave-one-out error report, saves `calib.json`
  (H, z_table, home_joints).
- `pick.py` — target from `--xy` or ER 2; refuses targets outside the
  calibrated rectangle (+2 cm) or the EE box; home→hover→descend→close→lift.

## v2: wrist-cam fine stage + cycles
- `wrist_calibrate.py --wrist-cam 1` — interactive: jaws around a test object,
  SPACE; learns `grasp_center` + jog matrix A (saved under `"wrist"` in
  calib.json). `--center-only` redoes placement without jogs.
- `grip_test.py` — calibrates the proprioceptive grasp detector (empty close
  reads ~1.0, block stalls ~6.6+ — that's how picks are confirmed).
- `pick.py` now servos via the wrist cam by default (`--no-servo` to skip,
  `--no-descend` for convergence tests) and ER-verifies the grasp after lift.
- `cycle.py --cycles N` — mat → box → mat round trips: fresh container locate
  per stage, drop verified by ER, container-theft guard on in-box picks.

## Zero-shot SmolVLA (the VLA track)
```bash
PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH" lerobot-rollout ... \
  --rename_map='{"observation.images.workspace_cam": "observation.images.camera1", "observation.images.wrist_cam": "observation.images.camera2"}' \
  --policy.path=lerobot/smolvla_base --policy.device=mps
```
(full command in journal 2026-08-12; LeLab env has the `[smolvla]` extras).
Zero-shot: moves toward the target with intent, no grasp — fine-tune on 30–50
task demos is the path (ggando: SmolVLA 100% post-fine-tune).

## Known limits
- Homography assumes the target sits ON the table plane; tall objects offset xy.
- Wrist orientation is whatever the home pose has (orientation_weight 0.01) —
  top-down-ish grasps only.
- Re-calibrate whenever the camera or arm base moves.
