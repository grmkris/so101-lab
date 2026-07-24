# Run log

Newest on top. Template:

```
## YYYY-MM-DD — <what>
- lerobot: <version/commit> (record) / <version/commit> (train) / <version/commit> (infer)
- dataset: <repo_id> (<n> eps, placement policy, orientation policy)
- lighting: <locked? brightness?>
- result: <what happened>
```

---

## 2026-07-24 — ggando 4-post arc digested + sim on-ramp started

Read ggando's full SO-101 series (same hardware, ~6 months ahead of us on the RL question). Punchline table:

| Post | What | Result |
|---|---|---|
| so101-rl-lift | state-based SAC in MuJoCo | 100% in sim (11 reward versions, finger-pad collision fix) |
| image-rl-grasp | pixel RL (DrQ-v2) in MuJoCo | 100% in sim (2M steps, 19 reward versions) → **sim2real: complete failure** |
| so101-hil-serl | real-world RL (SAC + reward classifier + leader interventions) | 70% after 757 eps, weeks of debugging, 3h babysitting, 3 dead cameras. His verdict: "ACT on 50 demos would probably achieve similar results with less total effort" |
| smolvla-so101 | **SmolVLA fine-tune** on 75 teleop demos | **100% (5/5) vs ACT 80%** on same data. 20k steps, batch 64, ~10h RTX 3090 |

**Strategic read:** he tried to escape the IL data treadmill via RL and landed back on better-IL (pretrained VLA + clean demos). So: sim = learning/prototyping track only (RL mechanics, IK, reward design), NOT a path to pegboard reliability. Real-world track stays IL: **SmolVLA on blue-pegs is the queued next move**, DAgger as correction tool.

**His data lessons (adopt):**
- Consistency > quantity — ONE grasp strategy per dataset (his mixed nudge/rotate v2 was erratic at identical loss vs uniform v3).
- Dense small workspace > broad coverage at small N (75 eps in 10cm ≫ 50 eps in 30cm).
- **Record SLOW** — teleop lag in the sync record loop degrades demo quality.
- One dominant desk lamp beats ambient (also killed his reward classifier when violated).

**Queued: SmolVLA fine-tune on blue-pegs** — `--policy.type=smolvla --policy.pretrained_path=lerobot/smolvla_base` (needs `pip install 'lerobot[smolvla]'` in the Colab env), dataset `kris0/so101_blue_pegs_v1_20260723_171824`, batch 64, 20k steps, resize_with_pad 512×512 (default), Colab A100, `--save_checkpoint_to_hub=true`. A/B eval vs `act_blue_pegs_v1`. **Risk:** 450M model on Mac MPS inference — ACT already ran ~12Hz; SmolVLA's action chunks amortize but test before trusting.

**Repos to crib from:** ggand0/pick-101 (MuJoCo env, DLS-IK, 4-step pick, finger-pad fix), ggand0/vla-so101 (SmolVLA pipeline), ggand0/lerobot branch `hilserl-so101` (hardware robustness: camera auto-reconnect, motor retry — useful beyond RL), johnsutor/so101-nexus (6 MuJoCo tasks, leader-teleop-into-sim, BC+PPO, LeRobot-format recording).

**Sim on-ramp (`sim/`):** MuJoCo + SO-101 MJCF from TheRobotStudio/SO-ARM100 Simulation/SO101, ECE 4560 lab-4 exercises ported (`so101_mujoco_utils.py`, `run_sim.py`), so101-nexus installed for leader-into-sim teleop. Arms disconnected today — nexus teleop untested, command documented in `sim/README.md`.

## 2026-07-23 — 2-cam wall dataset, orientation model, Colab saga, phone teleop

**Dataset `kris0/so101_pickplace_wall_v1_20260722_174720`** (2 cams: workspace_cam idx0 + wrist_cam idx1, 640×480@30). Grew 20 → 38 → 58 eps via `lerobot-record --resume` (needs `--dataset.root=...`). Orientation batches: base 0°, then ±90°, then ±45° (discrete buckets, position varied within each). Brightness locked 115–131.
- Cleaned bad eps with `lerobot-edit-dataset --operation.type=delete_episodes --operation.episode_indices="[...]"`. ⚠️ **This tool is FRAGILE** — on a multi-resume dataset it hit a video-length mismatch, failed mid-op, and **gutted the local dataset** (info.json → 0 eps). Recovered from the auto-made `<name>_old` backup dir it leaves + the Hub copy. Lesson: **push to Hub before editing**, and prefer excluding eps at train time (`--dataset.episodes`) over deleting.
- Dead ep57 (phone-call, 20s no-grasp) excluded at train time via `--dataset.episodes="[$(seq -s, 0 56)]"` → 57 eps.

**Models (all ACT, 2-cam, 52M params, Colab A100 @ v0.6.0):**
- `act_wall_v1` (20 eps) — reliable single-orientation grasp. ✅ the "it works" milestone.
- `act_wall_v2` (38 eps, 0°/±90°) — died in the Colab saga (see below).
- `act_wall_v3` (57 eps, 0°/±45°/±90°) — died at step ~10k, checkpoint saved to Hub.
- `act_wall_v3_final` — **continued** from the 10k checkpoint (warm-start), loss dropped 0.172→0.113.

**Colab disconnect saga (big lesson):** ran **two A100 notebooks in parallel** → tripped Colab's concurrency limit → both disconnected, one runtime wiped (lost on-disk checkpoints). Fixes now standard:
- **`--save_checkpoint_to_hub=true`** → checkpoints push to the Hub every `save_freq`; survive any disconnect.
- **Resume/continue** from a Hub checkpoint: download `checkpoints/NNNNNN/pretrained_model`, then `lerobot-train --policy.type=act --policy.pretrained_path=<local dir> ...` (NOTE: `--policy.type=act` is REQUIRED alongside `--policy.pretrained_path` or draccus errors).
- **Run ONE training at a time.** No parallel.
- Real escape hatch: **HF Jobs** — `lerobot-train --job.target=a100-large --job.detach=true` runs headless on HF cloud GPU from the CLI, survives laptop close, pushes to Hub. Needs **HF Pro** ($9/mo) + ~$2.50/hr A100. `hf jobs list/logs/cancel` to manage.

**Eval (act_wall_v3 ~20k checkpoint):** orientation invariance REAL — good at 90°/perpendicular/center, weak at edges + ±45°.

**Eval (`act_wall_v3_final`, full 40k, on the arm) — ✅ the win:** orientation-invariant grasp works, "otherwise pretty good." Two residual gaps only: (1) **top-left at 45°, near the base** (thin data + folded-pose geometry), (2) **drop/release slightly unreliable** (fuzzy release point in demos). Model is usable as-is. Optional polish: resume ~15 targeted eps (top-left/45°/near-base + deliberate consistent drops) → retrain from scratch on union excluding ep57 (`eps = list(range(57)) + list(range(58,73))`). Or bank it and move to the pegboard.
- Note: rollout eval on **Mac MPS runs slow (~12 Hz vs 30 target FPS)** — works but sluggish; frames may drop. Fine for eval, not ideal for data collection.

**DAgger (human-in-the-loop correction) — the reliability tool:** `lerobot-rollout --strategy.type=dagger` + `--teleop.type=so101_leader ...`. Policy runs autonomously; press **`tab`** to grab the leader and correct, `tab` again to hand back. Corrections tagged `intervention=True`, saved as episodes. Add to dataset → continue training. This is how you close specific gaps (edges/45°) efficiently.

**Phone teleoperation — WORKS** (see `phone_teleop/README.md`). iPhone HEBI Mobile I/O app → ARKit 6DOF pose → IK (Placo + SO-101 URDF) → arm end-effector. Fixes needed: (1) patched a lerobot bug where calibrate read B1 as int-only (our phone sends bool); (2) network via **iPhone Personal Hotspot + macOS firewall off** (WiFi client-isolation blocks the feedback UDP); (3) made `teleoperate.py` robust (retry phone connect, skip over-fast frames). Remote-over-internet path: Tailscale.

**New playground: pegboard "Varied Jigsaw Puzzle"** — rigid colored link pieces with holes that slot over pegs. This is a **peg-insertion / assembly** task (canonical, and the precision-placement skill the chess arm needs). Hard-but-doable by hand → the next real challenge after the orientation model. Ramp: grasp-a-piece → insert-over-one-peg → two-peg → build a pattern.

## 2026-07-16 — v3 dataset + act_v3/act_v4 (LeLab-era, lerobot 0.6.0)

- lerobot: 0.6.0 everywhere (LeLab record / Colab `git checkout v0.6.0` train / lelab-env rollout) — version lever locked.
- dataset: `kris0/so101_pickplace_v3_20260716_132204` — 20 eps → extended to 39 via `lerobot-record --resume`. Random position, consistent orientation (wrist_roll std 12.6 vs 42 in old data), brightness locked 104–122.
- `act_v3` (20 eps, 30k steps, loss 0.063): failed left-of-center — coverage gap (only 5/20 eps left side).
- `act_v4` (39 eps, same recipe): ~half successful. Some clean grasps, spectacular misses elsewhere. Reading: single overhead cam depth ceiling + 39 eps still thin.
- New 0.6 tooling learned: `lerobot-record` = data collection only; policy deployment = `lerobot-rollout --strategy.type=episodic`, dataset must be named `rollout_*`. DAgger strategy exists built-in (leader-arm corrections tagged `intervention=True`) — the path from ~70% to ~95% later.
- LeLab gotcha: shipped frontend bundle is stale vs source — built `frontend/` with bun and swapped `dist` into the uv tool install to get the teleop camera panel.
- **Next: workspace rebuild, all changes batched at once** — arm facing wall (clean background), wrist cam (Innomaker, print 32×32 mount), rigid overhead mount, fixed lights, tape marks, recalibrate → canonical 40–60 ep dataset. No more recording in the current scene.

## 2026-07-16 — baseline state (backfill)

- Best policy so far: `kris0/act_pickplace_v052c` — 50k steps, loss 0.062, trained on Colab with git-checkout `05a52238` (0.5.2) to match the 0.5.2 record/infer stack.
- dataset: `kris0/so101_pickplace_clean` — 47 eps, random position (continuous, no clustering), but grasp wrist_roll spans 146° → orientation too varied for the dataset size.
- result: descends fully, grasp flaky; strongly lighting-dependent (works ~120 brightness, fails ~50–60).
- Earlier attempts: 0.6.1-trained models on 0.5.2 inference stopped ~70% down — the version-mismatch bug. `lerobot-replay` (perfect playback) is what isolated it.
- Next: LeLab (latest lerobot, whole loop one version), v3 dataset 60–80 eps with consistent orientation + locked lights.
