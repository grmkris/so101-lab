# so101-lab — context for Claude

Hands-on lab for Kristjan's SO-101 arm (LeRobot imitation learning). **End goal: the arm plays chess.** Current rung: a reliably-grasping pick-and-place policy — and a remote-teleop platform growing around it (`app/`).

## How to work here
- Be concise. Sacrifice grammar for concision. No time estimates (use complexity).
- This repo = the hands-on lab. Learning notes live in the separate `personal` KB repo (`learning/robotics.md`, `learning/robotics-qos.md`).
- After each real record/train/eval run, append a dated entry to `journal.md` (newest on top): lerobot version, dataset, lighting, camera indexes, orientation policy, result. This log is the point — past runs couldn't be compared because nothing was written down.
- Commit + push to `origin main` after meaningful changes. Public repo (build-in-public).

## The app (`app/`) — MOVED to github.com/grmkris/eth-global-lisbon-2026-proof-of-hands
The platform now lives in that public bun monorepo (apps/web + apps/driver, Railway project `proof-of-hands`). The copy under `app/` here is FROZEN — make platform changes in the new repo. Everything below describes the system itself and still applies.
One TypeScript app (`app/console`: TanStack Start, React 19, Effect v4, Bun) + a Python driver (`app/driver`: uv env pinned `lerobot==0.6.0`). Three roles from ONE build, resolved by `LAB_MODE` env:
- **hub** — lobby + relay, **deployed: https://hub-production-3903.up.railway.app** (Railway project `so101-hub`, Dockerfile in `app/console/`, 1 replica + no sleep are load-bearing — in-memory rig registry).
- **agent** — headless rig (arm or MuJoCo sim). Dials OUT to the hub (no inbound ports). `LAB_AUTOCONNECT=sim|real` brings the backend up at boot.
- **console** (default) — the local lab tool: robot page, record wizard, datasets, trainings.

Key facts: transport = 20 Hz HTTP polling + MJPEG re-serve (deliberate — no WS/WebRTC; curl-debuggable); single-writer **lease** per rig (e-stop/teleop_stop bypass it; "Take over" force-steals); safety = 15°/tick remote clamp + 0.5 s deadman + servo EEPROM limits; auth (`HUB_TOKEN`) built but **currently unset**; `app/driver/controller.py` = drive a remote rig with your own leader arm (~16 packets/s). `FOLLOWER_PORT`/`LEADER_PORT`/`ROBOT_ID` env override the defaults in `src/api/rig.ts`. Scripts: `hub`, `hub:prod`, `agent`, `rig:sim`, `rig:sim:viewer`, `rig:real`. Docs: `app/SPEC.md` (architecture), `app/TESTING.md` (checklists), `notes/friend-setup.md` (onboarding).
⚠ Phone teleop source in the console is **broken**: the driver venv lacks the lerobot phone patches (see `phone_teleop/README.md`) — LeLab env has them, `app/driver/.venv` does not.

## Stack (all lerobot 0.6.0 — keep it matched)
- TWO pinned lerobot envs: LeLab uv tool env (`~/.local/share/uv/tools/lelab/bin/`, CLI + rerun viewer) and the driver env (`app/driver/.venv/`). Same version; the crib-sheet CLI track uses LeLab, the console uses the driver env.
- LeLab web UI (`lelab`, port 8000) for calibration/teleop/import. CLI for record/rollout/replay. **Every CLI command is in `notes/crib-sheet.md`** — read it before constructing any lerobot command.
- HF user `kris0`. Ports: follower `/dev/tty.usbmodem5AE60832001`, leader `...5AE60538411`. Both IDs `arm`.
- Training on Colab A100, `git checkout v0.6.0` (matches the local stack). No HF Pro yet.

## The hard-won levers (don't relearn these)
1. **Version match** — record/train/infer on the SAME lerobot version. Mismatch silently under-scales actions. `lerobot-replay` first when debugging (isolates policy vs hardware).
2. **Lighting** — lock it. Policies trained at one brightness fail at another (~120 works, ~50 fails).
3. **Coverage + orientation** — a ~40-ep dataset can't learn position AND orientation invariance. Keep object orientation consistent; spread positions evenly (incl. corners) or the thin regions fail. Proven: act_v3 failed left-of-center because only 5/20 eps were left.
4. **macOS shuffles camera indexes on replug** — ALWAYS verify indexes before a session (console `GET /api/cameras/probe`, or the snippet in crib-sheet). Currently overhead C922=0, wrist Innomaker=1, but they swap.
5. **lerobot degree zero = mid of calibrated range** — any consumer with a different frame (MJCF, URDF) must offset per joint or poses land ~90° off (bit us on shoulder_lift/elbow_flex in the sim; fixed in `backends/sim.py`). wrist_roll zero is calibration-pose-relative across devices — unresolved wart for cross-device leader→follower.

## Current state (2026-07-25)
- **Platform v1 LIVE**: hub on Railway; sim rig (`kris-sim`) + real follower (`kris-arm`) both registered and driven over the internet — browser keyboard AND a real leader through `controller.py`. Remaining: the actual two-person test (friend's follower/leader — `notes/friend-setup.md` is ready), wrist_roll handshake, stale queued hub commands delivered on rig re-register.
- **ML track (2-cam wall setup)**: arm at white wall, overhead C922 (idx 0) + wrist Innomaker (idx 1), 640×480@30. Taped pick rectangle, black mat, lighting locked ~120–130. Working policy: `act_wall_v1` (20 eps, single orientation) = reliable grasp ✅. Orientation model `act_wall_v3_final` (dataset `kris0/so101_pickplace_wall_v1_20260722_174720`, 57 eps, 0°/±45°/±90°): works at 90°/center, **weak at edges + ±45°**. Next: finish to 40k → eval → DAgger-correct edge/45° failures → retrain.
- **Queued next real-world move: SmolVLA fine-tune on blue-pegs** (ggando: SmolVLA 100% vs ACT 80% on same demos) — dataset `kris0/so101_blue_pegs_v1_20260723_171824`, A/B vs `act_blue_pegs_v1`.

## Hard lessons locked in
- **Colab:** ONE training at a time (parallel A100s trip concurrency → disconnect). Always `--save_checkpoint_to_hub=true`. Continue from a Hub ckpt: `--policy.type=act --policy.pretrained_path=<local ckpt dir>`. Escape Colab via HF Jobs when HF Pro exists.
- **At our scale train from scratch by default** (57 eps ≈ 1.5h A100); warm-start only to recover a crash or for DAgger.
- **`lerobot-edit-dataset delete_episodes` is fragile** on multi-resume datasets — push to Hub first, or exclude eps at train time via `--dataset.episodes`.
- Eval on **Mac MPS is slow (~12 Hz)** — usable for eval, not data collection.
- **Railway**: no inbound UDP (control plane only), redeploy wipes in-memory state (rigs re-register in ≤50ms by design; leases are lost — expected).

## Phone teleop (`phone_teleop/`)
iPhone HEBI Mobile I/O → ARKit pose → IK → arm. Standalone scripts work (LeLab env, patched). The console's `phone` source needs the same 2-line patch in `app/driver/.venv` — see `phone_teleop/README.md`. Needs iPhone hotspot + firewall off.

## Roadmap
1. **SmolVLA fine-tune on blue-pegs** (queued — see journal 2026-07-24).
2. Two-person remote teleop test (friend's hardware) → then task assignment / recording by operators (the crowdsourced-data product).
3. DAgger corrections for tight-tolerance failures (keyboard trusted-timeout patch applied, untested).
4. `sim/` learning track (MuJoCo + ECE 4560) — NOT sim2real (ggando: pixel RL 100% sim, total failure real). The production sim is `app/driver/backends/sim.py`.
5. Pegboard mastery → placement coach → chess (board ~34cm > edge-mount reach; center-side mount or smaller board).

## Data collection rules (ggando-validated, 2026-07-24)
- ONE consistent grasp strategy per dataset (mixed strategies = erratic policy at identical loss).
- Dense small workspace beats broad coverage at small ep counts.
- Record SLOW — teleop lag degrades demo quality.
- One dominant desk lamp > ambient light.
