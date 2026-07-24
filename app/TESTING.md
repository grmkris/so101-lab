# Lab Console — testing checklists

Two scripted walk-throughs: a sim smoke you can run anytime with zero hardware,
and the rig session for the real arm (user present — never actuate the real arm
unattended).

Start the app: `cd app/console && bun run dev` → http://localhost:3000
(the Python driver spawns lazily on first robot/camera call; venv at
`app/driver/.venv`, `uv sync` in `app/driver` if missing).

## 1 — Sim smoke (no hardware)

| # | Step | Expect |
|---|------|--------|
| 1 | Dashboard `/` | rig card shows arm: disconnected; API line green |
| 2 | Robot page → **Connect SIM** | state connected · SIM badge; both cams stream (MuJoCo scene) |
| 3 | Source `scripted expert` → Start teleop | arm runs the pick choreography in the streams |
| 4 | Stop → source `keyboard (EE jog)` → Start teleop → click the key pad | W/S/A/D/Q/E jog the arm; O/C gripper |
| 5 | Release all keys / click away | arm holds pose (deadman ~0.5 s) |
| 6 | Source `phone` → Start teleop (no phone around) | arm holds; after ~40 s a friendly "phone not found" error surfaces |
| 7 | Record page → source `Scripted expert`, 2 eps × 5 s | REC/RESET HUD cycles, `done — 2/2 saved`, dataset gets SIM badge on Datasets page |
| 8 | Record again → source `Keyboard`, drive during REC via the pad | keys drive the arm while recording; 2/2 saved |
| 9 | Datasets page → `report` link on the new dataset | episode table renders; exclude an ep → `--dataset.episodes` flag string appears |
| 10 | E-STOP during any teleop | physics pauses, state back to connected |

CLI equivalent of 7–8 (drives the driver directly):
`app/driver/.venv/bin/python` + `test_sim_driver.py` / `test_t3_keys_record.py`
(session tmp scripts; both loop connect→record→verify `LeRobotDataset` loads).

## 2 — Rig session (real arm, user at the rig)

Pre-flight (every session — macOS shuffles camera indexes on replug):
- [ ] Robot page → Probe cameras → identify workspace/wrist → **Confirm**
- [ ] Brightness inside the 115–131 band (one dominant desk lamp)
- [ ] Both arms powered + plugged (follower `...832001`, leader `...538411`)

| # | Step | Expect |
|---|------|--------|
| 1 | **Connect (leader + follower)** | state connected · leader: yes; joints grid live |
| 2 | Source `leader arm` → Start teleop | follower mirrors leader ~60 Hz, no lag spikes |
| 3 | Stop → `keyboard (EE jog)` → Start → jog gently | EE-space jog works; **big jump attempt → driver stderr shows the 15°/frame clamp warning** |
| 4 | `phone (HEBI, hold B1)` — iPhone hotspot, firewall off, HEBI app foreground | after B1 calibration pose capture: hold B1 + move phone drives the arm; release B1 → holds |
| 5 | E-STOP (raised arm — catch it!) | torque kills instantly, arm goes limp |
| 6 | Record 2 real eps, source `leader` (cameras confirmed) | REC HUD; episode saves on timeout / ✓ keep; `done — 2/2` |
| 7 | Datasets → report card on the new set | lengths sane, no unexpected `short` flags |

Phone runbook details: `phone_teleop/README.md` (hotspot, firewall, B1/A3 mapping).

## Regression suite (run after driver/console changes)

```sh
cd app/console && bunx tsc --noEmit && bunx biome check src
cd app/driver && .venv/bin/python -c "import ast; [ast.parse(open(f).read(),f) for f in ['driver.py','teleop_loop.py','recorder.py']]"
# + sim smoke rows 2–8 above (or the two driver test scripts)
```

Known gaps / by design:
- Real-mode record HUD shows no camera streams (the recorder owns the devices).
- Report card needs the dataset in the local cache (`~/.cache/huggingface/lerobot`).
- Contract changes need a dev-server restart (the API handler survives HMR on purpose).
