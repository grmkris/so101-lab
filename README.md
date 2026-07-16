# so101-lab

Lab notebook + tooling for my SO-101 arm (LeRobot). Everything I learn doing imitation learning on real hardware, logged so runs are comparable.

**End goal: the arm plays chess.** Current rung: reliable pick-and-place.

## Layout

- `journal.md` — run log, newest on top. Every record/train/eval run: lerobot version, dataset, lighting, orientation policy, result.
- `scripts/` — small helpers (motor ping, wiggle smoke test, camera preview, dataset frame review).
- `notes/` — hard-won practices: the three reliability levers, eval checklist, command crib sheet.
- (planned) `ui/` — teleop web UI: live camera in browser → dataset coverage heatmap → "place the object here" placement coach.

## The three reliability levers

1. **Version match** — record/train/infer on the SAME lerobot version. 0.5.x↔0.6.x mismatch silently under-scales actions (normalization moved out of the policy in 0.6.0). Debug with `lerobot-replay` first.
2. **Lighting** — lock it. Same lights for record and eval; policies trained at one brightness fail at another.
3. **Variation budget** — a ~50-episode dataset can learn position OR orientation invariance, not both. Vary only what you want generalized.

## Hardware

SO-101 leader + follower (Feetech STS3215), Logitech C922 overhead (640×360 — native 16:9), wrist cam Innomaker 32×32 UVC incoming.
