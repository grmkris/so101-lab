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

## 3 — Remote teleop cluster (no hardware, two processes on one Mac)

Simulates "my rig, her laptop, a cloud in between" without a cloud. The only
difference from production is the value of `HUB_URL`.

Two terminal tabs, both in `app/console`:

```sh
# tab 1 — the hub (this is what deploys to Railway)
bun run sim:hub                                    # → :3001
HUB_LATENCY_MS=120 HUB_DROP_RATE=0.05 bun run sim:hub   # …or impaired

# tab 2 — the rig (your existing console + driver)
bun run sim:rig                                    # → :3000
```

Then **open http://localhost:3000 once** — vite loads the server entry lazily, so
the rig link only starts after the first request (in production it starts at
boot). Look for `[rig-link] kris-sim -> http://localhost:3001` in tab 2.

| # | Step | Expect |
|---|------|--------|
| 1 | `:3001/lobby` | `kris-sim` card, online, "no feed" (sim not connected yet) |
| 2 | Open the card → **Take control** → **Connect SIM** | MuJoCo loads on the rig; both feeds appear within ~2 s |
| 3 | **Start teleop (keys)** → click the jog pad → W/S/A/D/Q/E | arm moves in the hub's video; joints grid updates |
| 4 | Release all keys | arm holds — the deadman fires because the hub does **not** replay input |
| 5 | Second browser tab on the same rig | video plays, jog pad hidden, "someone else is driving" |
| 6 | Take over from tab 2, then drive from tab 1 | tab 1 gets 403; one writer at a time |
| 7 | Kill tab 2 (the rig) | lobby flips to offline within 5 s |
| 8 | Restart the rig, then restart the hub | both re-register with no reconnect logic — that is a Railway redeploy |
| 9 | Re-run with `HUB_LATENCY_MS=120 HUB_DROP_RATE=0.3` | still driveable; rig card shows link ≈125 ms; arm still holds on silence |

Going remote for real: deploy the hub (`bun run build && bun run start`), then
start the rig with `HUB_URL=https://<app>.up.railway.app RIG_NAME=kris-sim`.
Nothing else changes.

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
