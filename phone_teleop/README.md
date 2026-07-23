# Phone teleoperation (iPhone → SO-101)

Control the SO-101 by moving your iPhone in space. The phone's ARKit 6DOF pose drives the
gripper's end-effector via inverse kinematics (Placo). Native lerobot `phone` teleoperator.

## What's here
- `teleoperate.py` — configured for our arm (SO101Follower, port `...5AE60832001`, id `arm`, iOS).
- `record.py` — record a dataset via phone teleop (EE-space observations/actions).
- `SO101/` — URDF + meshes (needed for IK; target frame `gripper_frame_link`).
- `phone_debug.py`, `b1_check.py` — diagnostics (what the phone is streaming / button state).

## One-time setup (already done)
```bash
uv pip install --python ~/.local/share/uv/tools/lelab/bin/python teleop placo hebi-py
# URDF + meshes fetched from TheRobotStudio/SO-ARM100 Simulation/SO101 into ./SO101/
```

## iPhone app
Install **HEBI Mobile I/O** (App Store). In its settings set **Family = `HEBI`**, **Name = `mobileIO`**.

## Network — the thing that makes discovery work
HEBI discovers via multicast but streams pose via unicast UDP. Home/office WiFi with client
isolation blocks it. **Use the iPhone's Personal Hotspot and connect the Mac to it**, and
**turn off the macOS firewall** (System Settings → Network → Firewall). Keep the app in the
**foreground with auto-lock OFF** — a backgrounded/locked phone stops broadcasting ("Mobile I/O not found").

## Run
```bash
cd ~/Code/github-com/so101-lab/phone_teleop
~/.local/share/uv/tools/lelab/bin/python teleoperate.py
```
- Hold phone screen-up, top edge pointing same direction as the gripper.
- **Press & hold B1** → captures reference pose, starts teleop. Move phone → arm follows.
- **A3 slider** → gripper open/close. Release B1 to pause.

## Known bugs we patched in lerobot (fragile — LOST on lerobot reinstall)
In `lerobot/teleoperators/phone/teleop_phone.py`:
1. **B1 read (calibrate):** `_wait_for_capture_trigger` read B1 with `get_int(1)` only. Our phone
   sends B1 as a **bool**, so calibration never triggered. Patched to fall back to `get_bool(1)`.
2. **None feedback crash:** `_read_current_pose` did `pose = fbk[0]` with no None check, so any
   phone feedback hiccup (app dims / network blip) crashed with `TypeError: NoneType not
   subscriptable` — this is the "doesn't work again" failure. Patched to `if fbk is None: return
   False, None, None, None` so callers retry through the gap.

Both are candidate upstream PRs. If you reinstall/upgrade lerobot, re-apply both or teleop breaks.

## Safety (in our teleoperate.py)
- **Ctrl+C disables torque** (try/finally → `robot.disconnect()`). The stock example left the arm
  powered and holding on exit — dangerous. Always stop with Ctrl+C.
- Gentler motion: `end_effector_step_sizes=0.3`, `max_ee_step_m=0.08` (fast phone moves are skipped,
  not lunged), tighter EE bounds. Still: keep a hand near the power switch, small motions first.

## Tuning
- Axis inverted/swapped → sign flips in `MapPhoneActionToRobotAction`.
- Motion speed → `end_effector_step_sizes` (default 0.5) in `teleoperate.py`.
- Workspace limits / safety → `EEBoundsAndSafety` (bounds, `max_ee_step_m`).

## Remote (another country)
Put iPhone + Mac on the same **Tailscale** network → the native LAN teleop works over the
internet, no extra infra. (Same hotspot-style direct path, just via tailnet.)
```
