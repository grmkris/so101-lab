---
name: so101-desk
description: Drive the real SO-101 follower from this agent via persistent joint jogging and camera snaps (not ACT). Use when picking, placing, jogging, visual-servoing, probing desk cameras, putting something in the tub, or the user runs /so101-desk.
---

# SO-101 desk jog

Tool: `gemini_er/desk.py`. Motion code lives in `gemini_er/arm.py` + `capture.py`. Ports/IDs: `notes/crib-sheet.md`.

Python for **serve** (lerobot + cv2):
`PY` = `eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python` (see `gemini_er/README.md`).
Client verbs: any python.

## Session

1. Do not start `serve` or energize until the user asks to pick/place/jog.
2. Never run with `gemini_er/arm_daemon.py` (same serial port).
3. `$PY gemini_er/desk.py serve` once. Leave it running. Idle = torqued hold.
4. `python gemini_er/desk.py cams` then **look at** `debug/desk_workspace.jpg` and `debug/desk_wrist.jpg`. Motion is refused until this serve has a successful `cams`. Typical this desk: workspace C922, wrist Innomaker; macOS indexes shuffle.
5. Fast path if `calib.json` still matches this camera/base: `pick.py` / `cycle.py` (mat→container→mat). Overlay dry-run first. Jog only if homography is stale or those scripts miss.

## Verbs

```
python gemini_er/desk.py pose | status | snap [workspace|wrist|both]
python gemini_er/desk.py delta shoulder_pan=-4 gripper=80
python gemini_er/desk.py goto ready
python gemini_er/desk.py grip 80
python gemini_er/desk.py grip-state
python gemini_er/desk.py save tub_hover
python gemini_er/desk.py stop          # disconnect, torque off
```

`delta`: joints relative ±8° clamp; **gripper absolute** 0–100. `goto NAME` uses `gemini_er/desk_poses.json` (`ready` is seeded; record others with `save`).

## Visual servo

`delta` → `snap both` → look → nudge. Wrist for jaw alignment; workspace for pan and container.

This desk, C922 face-to-face: image-right = **negative** `shoulder_pan`. `+shoulder_lift` = **down**. Confirm on the first 3° nudge; do not assume if the operator moved.

## Pick / place gates

Pick is done only when **all** are true: wrist shows object **between** fingers, `grip-state` is `held`, lift leaves the original spot empty.

Place: transit high → `goto` a recorded hover (`save tub_hover` first) → snap must show the object **over the container mouth** → then `grip 80`. Never open beside the rim.

Empty close ≈1, held ≈7–22, open ≥45 (`grip_test.py` / `cycle.grasped`).

## After the run

`stop` the serve. Journal the result in `journal.md`.
