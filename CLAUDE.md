# so101-lab — context for Claude

Hands-on lab for Kristjan's SO-101 arm (LeRobot imitation learning). **End goal: the arm plays chess.** Current rung: a reliably-grasping pick-and-place policy.

## How to work here
- Be concise. Sacrifice grammar for concision. No time estimates (use complexity).
- This repo = the hands-on lab. Learning notes live in the separate `personal` KB repo (`learning/robotics.md`, `learning/robotics-qos.md`).
- After each real record/train/eval run, append a dated entry to `journal.md` (newest on top): lerobot version, dataset, lighting, camera indexes, orientation policy, result. This log is the point — past runs couldn't be compared because nothing was written down.
- Commit + push to `origin main` after meaningful changes. Public repo (build-in-public).

## Stack (all lerobot 0.6.0 — keep it matched)
- All `lerobot-*` binaries in the LeLab uv env: `~/.local/share/uv/tools/lelab/bin/`. Prefix `PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH"` so the rerun viewer resolves.
- LeLab web UI (`lelab`, port 8000) for calibration/teleop/import. CLI for record/rollout/replay.
- **Every command is in `notes/crib-sheet.md`** — read it before constructing any lerobot command.
- HF user `kris0`. Ports: follower `/dev/tty.usbmodem5AE60832001`, leader `...5AE60538411`. Both IDs `arm`.
- Training on Colab A100, `git checkout v0.6.0` (matches the local stack). No HF Pro yet.

## The hard-won levers (don't relearn these)
1. **Version match** — record/train/infer on the SAME lerobot version. Mismatch silently under-scales actions. `lerobot-replay` first when debugging (isolates policy vs hardware).
2. **Lighting** — lock it. Policies trained at one brightness fail at another (~120 works, ~50 fails).
3. **Coverage + orientation** — a ~40-ep dataset can't learn position AND orientation invariance. Keep object orientation consistent; spread positions evenly (incl. corners) or the thin regions fail. This was proven: act_v3 failed left-of-center because only 5/20 eps were left.
4. **macOS shuffles camera indexes on replug** — ALWAYS verify indexes before a session (snippet in crib-sheet). Currently overhead C922=0, wrist Innomaker=1, but they swap.

## Current state (2026-07-23) — see journal.md 2026-07-23 for the full run
- **2-cam wall setup:** arm at white wall, overhead C922 (idx 0) + wrist Innomaker (idx 1), 640×480@30. Taped pick rectangle, black mat, lighting locked ~120–130. Calibration current (id `arm`). **Verify cam indexes every session** (macOS shuffles).
- **Working policy:** `act_wall_v1` (20 eps, single orientation) = reliable grasp ✅. **Orientation model:** dataset `kris0/so101_pickplace_wall_v1_20260722_174720` (57 clean eps, 0°/±45°/±90°). `act_wall_v3_final` continued-training on Colab (warm-start from 10k ckpt, loss ~0.11). Local 20k-equiv ckpt at `~/act_wall_v3_20k/checkpoints/010000/pretrained_model`.
- **Eval finding:** orientation invariance works at 90°/center; **weak at edges + ±45°** (coverage gaps + maybe undertraining).
- **Next action:** finish `act_wall_v3_final` to 40k → eval orientations → **DAgger-correct** the edge/45° failures (`--strategy.type=dagger` + leader, `tab` to take over) → add corrections, retrain.

## Hard lessons locked in (2026-07-23)
- **Colab:** run ONE training at a time (parallel A100s trip concurrency → disconnect). Always `--save_checkpoint_to_hub=true` so a disconnect can't lose progress. Continue from a Hub ckpt: `--policy.type=act --policy.pretrained_path=<local ckpt dir>`. Escape Colab entirely with **HF Jobs** (`lerobot-train --job.target=a100-large --job.detach=true`, needs HF Pro).
- **At our scale train from scratch by default** (57 eps ≈ 1.5h A100); warm-start only to recover a crash or for DAgger.
- **`lerobot-edit-dataset delete_episodes` is fragile** on multi-resume datasets — push to Hub first, or exclude eps at train time via `--dataset.episodes`.
- Eval on **Mac MPS is slow (~12 Hz)** — usable for eval, not for data collection.

## Phone teleop — WORKS (`phone_teleop/`)
iPhone HEBI Mobile I/O → ARKit pose → IK → arm. Run `phone_teleop/teleoperate.py`. Needs iPhone hotspot + firewall off + a lerobot B1-bool patch (documented in `phone_teleop/README.md`). Remote path: Tailscale.

## Roadmap after the orientation model
DAgger to close edge/45° gaps → **pegboard peg-insertion** (new playground: rigid link pieces over pegs = the precision-placement / assembly skill, canonical + chess-relevant) → teleop web UI (placement coach) → chess (board ~34cm > edge-mount reach; solve via center-side mount or smaller board).
