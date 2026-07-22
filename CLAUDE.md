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

## Current state (2026-07-16)
- **Workspace rebuilt:** arm faces a white wall (clean bg), 2 cameras (overhead C922 + wrist Innomaker), taped ~30cm pick rectangle on black mat, white block, glass bowl drop-off. Cables mostly cleared + taped. Lighting locked ~130.
- Calibration is current (arm relocated, not disassembled → teleop mirrors clean → no recalibration needed).
- **Next action:** record `kris0/so101_pickplace_wall_v1` — 50 eps, both cams, even spread, consistent orientation, ~6 recovery demos. Then push → Colab train `act_wall_v1` (40k steps) → `lerobot-rollout --strategy.type=episodic` eval. This is the first policy with every lever pulled at once + a wrist cam for depth.
- Prior policies (single overhead cam): `act_v3` (20 eps, failed left), `act_v4` (39 eps, ~half success — single-cam depth ceiling). Wrist cam is the fix for the "descends but misses" failure.

## After a reliable grasp works
DAgger corrections (`--strategy.type=dagger` + teleop, grab leader on failure, tagged `intervention=True`) to climb from ~70%→~95% without hundreds of new demos → then the teleop web UI ("placement coach": live cam → coverage heatmap → placement overlay) → then chess (board ~34cm playing area is bigger than arm reach from an edge mount; solve by center-side mount or smaller board).
