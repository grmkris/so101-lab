# Run log

Newest on top. Template:

## 2026-08-13 (morning) — v2: persistent arm daemon + hardened orchestrator

Deep-researched (3 agents: lerobot client internals w/ line refs, Live API
stability forensics from our own logs, MolmoAct2 episode semantics) then built:

- **`arm_daemon.py`** — ONE long-lived lerobot RobotClient (imported, not
  subprocess). Cameras+robot connect once; episodes start **~2 s** after the
  command (v1: ~165 s overhead/attempt); per-episode `stub.Ready()` resets the
  server WITHOUT reloading the policy. Idle = torqued hold at the checkpoint's
  ready pose (no pre-pose jerk). **Proprioceptive episode termination**
  (grasp-release trigger / stall / 45 s budget — MolmoAct2 has NO done signal,
  its training episodes avg 17 s; nobody in the field has automated this).
  **Live mid-episode steering VERIFIED on hardware**: task string rides on
  every observation (robot_client.py:414) — swapped "pick up the white cube" →
  "put the white cube in the plastic box" at grip-close, block retained, policy
  redirected. SCENE_ONLY mode (Innomaker cannot survive sustained streaming;
  wrist views are community-documented OOD anyway).
- **`live_agent.py` v2** — tools = daemon verbs (run_task/steer_task/stop_arm/
  arm_status/home); event-driven heartbeat with 10 s stall-recovery timer
  (root cause of the ~100 s Live API deaths = SERVER-SIDE INFERENCE STALLS,
  diagnosed from our logs — the keepalive timeout is just the messenger);
  TaskGroup (gather leaked a duplicate command-reader per reconnect);
  ws ping 10/10 via `HttpOptions(async_client_args=...)`.
- Observed: model checks arm_status before acting, missions survive reconnect
  churn, box→mat extraction completed under v2. Box placement remains the
  model's floor (Ai2's own Block-in-Box: 33.3%). Block went missing off-camera
  at session end — paused there. Still queued: temporal ensembling port
  (ACT-style, targets release-jerk drop scatter), success-trigger validation.

## 2026-08-13 — first zero-shot VLA grasps + ER 2 orchestrator flies (overnight session)

**Not an ML-data day.** The MolmoAct2 remote-inference night: first learned policy
ever to drive this arm, and it grasped zero-shot.

- Stack: `lerobot/MolmoAct2-SO100_101-LeRobot` (Ai2, 5B bf16) served from a
  **Colab L4** via lerobot 0.6.0 async inference (policy_server whitelist-patched
  for molmoact2 + policy-cache patched — upstream reloads the policy per client
  session, 273s each; cached = 2s handshakes). Transport: **Tailscale userspace**
  on Colab (inbound tailnet→localhost forwarding), ~175ms RTT. Nobody has
  published this topology. Scripts: `gemini_er/colab_policy_server.sh`,
  `run_molmoact.sh`.
- **Two roadblocks, both diagnosed to mechanism**: (1) freeze-at-home-pose —
  the server filters near-identical obs from a stationary arm AND the processor
  quantile-clamps out-of-band joint states; fix = start from the checkpoint's
  ready pose (derived from its norm stats: ~[3.3,-34.3,31.4,56,-11.5]).
  (2) sluggish/burst motion — queue starvation at fps 30 (30-act chunks, ~1s
  latency, stale-drop) + 1.8MB raw-frame blocking uplink; fix = fps 15,
  cam0 at 320x240, aggregate latest_only.
- **Results (tuned stack): 4/4 grasps** incl. a ~45°-rotated block (which the
  scripted stack could never do), full mat→box place, then box→mat extraction.
  Motion is slow — that's the trained teleop pace, not lag.
- **ER 2 streaming orchestrator (`live_agent.py`) first flight**: Live API
  session (gemini-robotics-er-2-streaming-preview, free tier), 1fps frames +
  heartbeat, blocking tools (vla_task/home/ack/reset), macOS say for voice.
  ER 2 autonomously ran 4 vla_task attempts with retries after visual
  verification, then home+reset on completion. Hard-won: Live API sockets die
  ~100s (keepalive timeout, preview flakiness) → reconnect + session-resumption
  + mission-resend required; heartbeats interrupt generation → 12s cadence +
  30s holdoff after user turns; model chose 12s tool budgets → clamp 90-180s.
- Env note: driver venv gained google-genai; LeLab env gained grpcio/protobuf/
  matplotlib. Cameras: C922=0, Innomaker wrist=1 (replug), builtin=2 — Innomaker
  wedged once more mid-night, physical replug again; it only does 640x480.
- Data: `gemini_er/data/molmoact2_zeroshot.jsonl`. Next: 50-demo recording
  session → SmolVLA fine-tune (baseline) + MolmoAct2 LoRA (A/B), per plan.

```
## YYYY-MM-DD — <what>
- lerobot: <version/commit> (record) / <version/commit> (train) / <version/commit> (infer)
- dataset: <repo_id> (<n> eps, placement policy, orientation policy)
- lighting: <locked? brightness?>
- result: <what happened>
```

---

## 2026-08-12 — Gemini Robotics ER 2 day: pointing→pick pipeline built, SmolVLA zero-shot flown

**Not an ML-data day** (lighting ambient, not locked). Gemini Robotics 2 dropped;
tested whether ER 2 (`gemini-robotics-er-2-preview`, API key — Gemini CLI OAuth is
dead, killed by the Antigravity migration) can drive the SO-101 as a high-level brain.

- lerobot: 0.6.0 everywhere. LeLab env grew `[smolvla]` extras (transformers 5.5.4;
  numpy 2.3.5→2.2.6 side effect). Driver venv (proof-of-hands repo) runs all
  `gemini_er/` scripts.
- cameras: SHUFFLED AGAIN + wrist cam needed a replug: workspace(front-oblique)=0,
  wrist=1, MacBook builtin=2.
- dataset: `kris0/rollout_smolvla_zeroshot` (2 eps, local only).

**What got built (`gemini_er/`)**: coarse stage (workspace cam → ER 2 point →
arm-touch homography, LOO 0.85 cm after dropping 4 far-field outliers) + fine stage
(wrist-cam servo: `grasp_center` pixel + 2-jog pixel→metre matrix, ER once for
semantics then cv2 template tracking) + IK pick primitive (placo continuation
planning — one-shot IK branch-flips, 25°-jump gate) + proprioceptive grasp detection
(empty close→1.0, block→6.6+; gate + retry) + box cycle (drop verify, container-theft
guard). **Verified picks achieved** (servo converged 6–18 px, grip 8.9–24.2,
ER verify YES).

**ER 2 verdict**: pointing is excellent (dead-center, 2–4 s, incl. "bottom contact
edge" prompts that dodge oblique-cam parallax). Success-detection verify ≈ its
published 87.7% — false verdicts ~1/8, advisory only. It is a real brain; it is NOT
a motor system — matching Google's own SO-101 sample (robotics-pointing-sample:
same architecture, stops at *pointing*) and Spot sample (grasps via wrist cam+depth).

**Hard-won during debugging**: streamed path points carry the IK seed's gripper
value (re-closed jaws mid-lift, thrice); servo sign error (plan said −A⁻¹·err);
close target 5 never squeezed the block (grip test: block stalls at 6.6, so close
to 0); ER hijacked by similar objects at frame edges (sanity-reject >250 px from
grasp_center); container coarse prompt "contact edge" aims drops at the rim.

**SmolVLA zero-shot** (`lerobot/smolvla_base`, MPS, `--rename_map` workspace→camera1
wrist→camera2): moved toward the block with intent, no grasp. Setup is close to its
community-SO-101 pretraining distribution → fine-tune is the move.

**Next**: record 30–50 block→box teleop demos (data rules apply) → SmolVLA fine-tune
on Colab → ER 2 orchestrates (task strings, success verify, retries) + SmolVLA
executes. Submit On-Device 2 trusted-tester form. ChArUco board PDF ready on
Desktop for coverage upgrade when printed.

**Evening addendum — autonomous capability mapping** (user away; wrist cam died
mid-session — Innomaker dropped off the USB bus, indexes re-shuffled, built-in
stole slot 1; needs physical replug). Raw data: `gemini_er/data/*.jsonl`.
- **Touch map (9 cells)**: blind positioning error 2.2–4.5 cm across the mat
  (one 0.6 cm cell near-right), direction consistently "x short", while FK
  self-reports ≤0.6 cm — the torque-on-droop-vs-torque-off-calibration gap,
  quantified. This is exactly the correction the wrist servo was making.
- **Bias-corrected push tour**: with the touch map as an IDW bias field, pushing
  the block works well INSIDE the mapped region (5 of 6 legs reached, final err
  0.6–2.8 cm, 15 cm diagonal in 6 strokes). At the left/far mat edges (outside
  calibration coverage) pushes go sideways — the envelope shrinks exactly where
  the far-field calibration points were dropped.
- **Bias-corrected BLIND grasp: 0/3.** Even with the bias field, open-loop
  grasping of a 2.5 cm block does not work. Closed-loop (wrist cam) or a
  learned policy is REQUIRED — the day's central conclusion, now with numbers.
- **ER 2 jitter study**: on a STATIC frame, pointing is near-deterministic
  (std 2.3 px, max spread 5.8 px over 10 calls). The apparent servo-time jitter
  came from frame-to-frame scene changes, not the model.
- One transient gripper "Input voltage error" at torque-on after hours of use;
  clean ping after 30 s, no recurrence. Watch the PSU under long sessions.

**Late addendum — ChArUco board flips the blind-grasp verdict (upright blocks).**
Printed 5×7/35 mm ChArUco on the mat (per google robotics-pointing-sample, but
improved: arm self-registration instead of hand-measured board origin — arm
touches 5 points, ER points the tip, affine board-mm→arm-cmd absorbs droop/
origin/print scale). `board_calibrate.py`: 19 corners, residuals 0.23–0.6 cm
(~10× better than the touch-map field). `pick_board.py` blind grasp through the
chain: first tries EMPTY — jaws clipped the block's near corner. Root cause:
ER's "contact edge" point is the block's NEAR bottom edge; center is ~1 cm
deeper along the camera axis. Fix = +12 mm offset along the image-up direction
mapped through the board homography. **With offset: upright block 2/2 HELD
(grip 10.0–10.2), tipped-over block 0/3** — put-down drops kept tipping it
(fixed-height release, no orientation awareness). `move_board.py` (square→square
chess primitive, auto-retry with fresh ER locate per attempt) written.
Conclusion sharpened: board-grade calibration makes scripted picks work when
the object matches the script's geometric assumptions; any pose variation
(a tipped block!) breaks it. The VLA case, again, with numbers.

## 2026-07-25 — platform day: console eliminated, leader agent, WebSocket input plane

**No training data today.** Every dataset written was sim checkpoint data
(tagged sim in `app/.data/sim-datasets.json`), so nothing here feeds the ML
track — logged so a future session does not mistake these repos for demos.

- lerobot: 0.6.0 everywhere (record/infer); no training run.
- datasets (ALL SIM, throwaway): `poh_cube_corner_v1` 5 eps ·
  `poh_ckptc_v1` 3 · `poh_finalcheck_v1` 2 · `poh_closeout_v1` 1. Recorded
  through the task/attempt loop as checkpoint evidence, not demonstrations.
- real hardware: leader + follower both on this Mac, driven through the
  DEPLOYED hub (Railway EU West) rather than locally. Teleop worked
  end-to-end; no episodes recorded on the real arm.
- lighting: n/a (no real recording).

**What shipped (repo: eth-global-lisbon-2026-proof-of-hands):**
1. **Console role eliminated** — one deployed web app (the hub) + portless
   headless agents. No `LAB_MODE`, no roles. Camera setup, recording,
   trainings and dataset report cards all ride the rig verb pipe; the hub API
   is GET-only. Dataset episode tables now read parquet straight off the HF
   Hub, so the deployed hub renders them with no local lerobot cache.
2. **Leader agent** (`bun run teleop`) — the teleoperator's side is now
   symmetric with the rig owner's: one no-args command, serial port
   auto-detected, hub URL baked in, registers under the hostname. The BROWSER
   picks the rig ("Drive with X's leader"); the agent claims nothing. Key
   invariant: **a leader is a bound input device of a browser session, never a
   lease holder** — which is what lets a task attempt keep running while a
   remote leader drives it.
3. **The 20-episode loop** — tasks carry a quota, `episodesDone` is derived
   from the dataset's own lerobot meta, and the card shows a real 13/20 bar
   with an auto-continue chain that advances only on a saved episode.
4. **WebSocket input plane** — measured against the deployed hub at a 30 Hz
   target: **24 packets/s over the socket vs 10/s over HTTP keep-alive**,
   which was RTT-bound. Camera preview 8 -> 12.5 fps (`LAB_FRAME_MS`).
   Everything else stays polled HTTP; input falls back to the HTTP mailbox
   whenever a socket is missing (vite dev cannot upgrade one — test the
   socket against `bun run hub:prod`).

**Lever learned (transport):** the felt teleop lag over the cloud hub was not
bandwidth, it was quantization — one-POST-at-a-time is RTT-bound, and the rig
then waited up to a 50 ms poll to pick input up. Event-driven in both
directions removes both; what is left is the physical hop to Railway.

**Owed (needs the arms + a human):** rerun the two hardware checkpoints —
leader-over-wire showing ~30 packets/s via socket, and a task attempt kept by
the browser while the leader drives.

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
