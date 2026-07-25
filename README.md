# so101-lab

Lab notebook + tooling for my SO-101 arm (LeRobot). Everything I learn doing imitation learning on real hardware, logged so runs are comparable.

**End goal: the arm plays chess.** Current rung: reliable pick-and-place — plus a growing remote-teleop platform so other people can drive the rigs.

## Layout

- `app/` — **Lab Console**: one TypeScript app (TanStack Start + Effect v4, Bun) + a Python driver pinned to lerobot 0.6.0. Three roles from one build: the **hub** (lobby + relay, deployed at https://hub-production-3903.up.railway.app), a headless **rig agent** (your arm or a MuJoCo sim, dials out — no port forwarding), and the default local lab console. `app/driver/controller.py` = drive a remote rig with your own leader arm. See `app/SPEC.md` and `notes/friend-setup.md`.
- `journal.md` — run log, newest on top. Every record/train/eval run: lerobot version, dataset, lighting, orientation policy, result.
- `notes/` — hard-won practices: the three reliability levers, eval checklist, command crib sheet, friend onboarding.
- `scripts/` — small helpers (motor ping, wiggle smoke test, camera preview, dataset frame review).
- `sim/` — MuJoCo learning experiments (ECE 4560 exercises). The *production* sim is `app/driver/backends/sim.py`, not this.
- `phone_teleop/` — iPhone (ARKit) teleop scripts; also supplies the SO-101 URDF the driver's IK uses.

## The three reliability levers

1. **Version match** — record/train/infer on the SAME lerobot version. 0.5.x↔0.6.x mismatch silently under-scales actions (normalization moved out of the policy in 0.6.0). Debug with `lerobot-replay` first.
2. **Lighting** — lock it. Same lights for record and eval; policies trained at one brightness fail at another.
3. **Variation budget** — a ~50-episode dataset can learn position OR orientation invariance, not both. Vary only what you want generalized.

## Hardware

SO-101 leader + follower (Feetech STS3215), Logitech C922 overhead + Innomaker wrist cam (both 640×480@30).
