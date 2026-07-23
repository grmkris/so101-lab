# Lab Console (working name) — spec

Web app replacing phosphobot/LeLab for this lab. One purpose: **run the data flywheel with quality gates** — control → guided record → grade → train → eval — for the SO-101 on this Mac, lerobot 0.6.0.

**Standalone-first**: the app is a complete ML-practitioner tool with zero blockchain dependency. Hackathon layers (payments/identity/provenance) bolt on as a separate service talking to this app's API; the core never imports them.

## Principles (non-negotiable, encode the hard-won levers)
1. **Thin wrapper over lerobot 0.6.0.** Backend imports lerobot classes in-process from an env pinned `lerobot==0.6.0`. Never reimplement drivers, calibration math, or dataset format. Version lever preserved by construction.
2. **Quality gates are the product.** Preflight before every session (cam indexes, brightness, calibration). Coverage engineered during recording, not discovered post-mortem.
3. **Never destructive.** No episode deletion (fragile tool, locked-in lesson). Exclusion lists only. Push to Hub early.
4. **Journal always.** Every session produces a draft `journal.md` entry.
5. **No database.** HF Hub (datasets, model repos, checkpoints) + the local lerobot cache ARE the state. The app is a control plane/lens over them, plus thin sidecar JSON for what the Hub can't hold (run configs, lineage, eval notes, coach state). Delete the app → nothing of value is lost.

## Non-goals
- Multi-robot/fleet, cloud hosting, auth, other robot types, mobile UI.
- Replicating phosphobot pro features (marketplace, cloud training UX).
- Replacing `lerobot-rollout` CLI for eval/DAgger in v1 (v2).

## Architecture
```
app/
  backend/    Python 3.12, uv project, deps: lerobot==0.6.0, fastapi, uvicorn, opencv-python, huggingface_hub
  frontend/   bun + Vite + React + shadcn, dev proxy → backend :8100
```
- Backend serves REST + `/ws/joints` (websocket joint stream) + `/cams/{name}` (MJPEG multipart). Port **8100** (LeLab keeps 8000).
- Singleton `RobotManager` owns the serial ports; explicit state machine: `disconnected → connected → teleop | recording`. One owner of the arm at a time; endpoints reject illegal transitions.
- Record/teleop loops cribbed from LeLab's `record.py`/`teleoperate.py` (readable locally in the lelab uv env, same lerobot version).
- App-local sidecar store `app/backend/data/<repo_id>/` for coach config + per-episode prompt tags + session logs. **Nothing extra written into dataset dirs** (keeps Hub push clean).
- Frontend production build served by FastAPI static mount (single-process launch: `make run`).

## Preflight (blocks recording until green)
- **Cameras**: enumerate; live thumbnails; user confirms "workspace" / "wrist" per session (macOS index shuffle). Persist last-known mapping, always re-confirm.
- **Brightness**: mean gray of overhead frame within configured band (default 115–131). Warn outside.
- **Calibration**: follower + leader calibration files exist for id `arm`; show age.
- **Disk**: free space check.

## Features — M0 hub foundation (no hardware needed — build first)
- HF auth status (reuse cached token), whoami.
- **Datasets**: local browse (scan `~/.cache/huggingface/lerobot` meta files, no lerobot import needed) + Hub browse (`kris0/*`).
- **Trainings registry**: every training run as a first-class object with full lineage:
  `run = {name, status: draft→launched→done/failed, dataset(repo_id + exclude list), policy(type, pretrained_path for warm-start), steps/batch/save_freq, hub model repo, wandb url, eval notes}`.
  - List view merges sidecar runs with `kris0/*` Hub model repos → past trainings (act_wall_v1/v3, act_v3/v4, v052c…) appear day one.
  - **Launcher**: "new training" form prefilled from a dataset → generates the exact version-matched Colab cell (crib-sheet convention: v0.6.0 checkout, `--save_checkpoint_to_hub`, `--policy.repo_id`) to copy-paste; registers the run as launched; **progress tracked by polling the Hub repo for checkpoints** (no agent needed inside Colab). One-click HF Jobs later when HF Pro exists.
  - Recommend `--wandb.enable=true` going forward; run page links the wandb curve.
- Acceptance: see all past trainings; create + launch a run; its checkpoints appear as they hit the Hub.

## Features — M1 walking skeleton (control + record)
- Ports: auto-discover `/dev/tty.usbmodem*`, map to follower/leader from saved config.
- Connect/disconnect follower ± leader; live joint readout; torque on/off; move-to-home; **E-stop = torque kill** (always visible).
- Teleop: leader→follower start/stop with cam previews.
- Record session wizard: repo_id auto-named `kris0/<task>_<YYYYMMDD_HHMMSS>`, task string, num eps, episode/reset seconds, cams from verified mapping.
- During recording: cam feeds, episode counter/timer, buttons + hotkeys: end-episode, re-record, discard, finish early.
- **Safe extend**: resume existing dataset (wraps `--resume` + `dataset.root`).
- Acceptance: record a 2-ep smoke dataset, loadable by `LeRobotDataset` in the lelab env, replayable with `lerobot-replay`.

## Features — M2 datasets + report card
- **Local browse**: scan `~/.cache/huggingface/lerobot`; eps/fps/cams/tasks; total frames; size.
- **Hub browse**: list `kris0/*` LeRobot datasets via `huggingface_hub`; pull; push; HF auth status/login. Deep-link each dataset to HF's dataset visualizer for episode playback (v1 playback = link out; embedded player later).
- **Report card** (computed offline, cached in sidecar store):
  - Coverage heatmap: first overhead frame per episode → threshold on black mat → `cv2.minAreaRect` → object (x, y, angle). Scatter + bin counts over the workspace grid.
  - Orientation histogram: object angle bins; plus wrist_roll-at-grasp distribution (grasp = gripper close event from actions).
  - Brightness per episode vs band; flag outliers.
  - Episode health: length outliers, gripper-never-closed, action jerk spikes.
- **Exclude-list builder**: tick episodes → emits `--dataset.episodes="[...]"` copy-string. No deletion.

## Features — M3 coach (guided recording)
- **Workspace config** (per task, stored in sidecar): grid rows×cols mapped to the taped rectangle (define by clicking 4 corners on the overhead frame → homography), orientation buckets (default 0/±45/±90).
- Before each episode: sample target bin = least-covered (position × orientation), render "place at C2, rotate +45°" with an overlay on the live overhead feed.
- After each episode: auto-detect actual placement (same CV), log prompted-vs-actual per episode; live coverage bar during the session.
- Coverage counts merge M2 report card (existing eps) + current session, so extending a dataset targets its real gaps.
- Acceptance: record 20-ep puzzle dataset where no bin has <2 eps.

## Features — cross-cutting
- **Journal draft**: on session end, generate the dated entry (dataset, eps, lighting band observed, cam mapping, coach coverage summary); one-click append to `journal.md` (never silent auto-append).
- Config file `app/backend/config.yaml`: ports, ids, cam defaults, brightness band, HF user.

## v2 (spec'd later, keep in mind)
- Train command generator (Colab cell / HF Jobs) prefilled from dataset + exclude list; run tracker.
- Eval matrix: tagged rollout trials (position×orientation → success grid) feeding the coach; DAgger session UI with intervention stats.
- Phone-teleop as a control source (reuse `phone_teleop/` IK).
- Embedded episode player (video + joint plots).

## API sketch
```
GET  /health, /config
GET  /ports                         # discovered serial ports
POST /robot/connect|disconnect      # {follower: bool, leader: bool}
POST /robot/torque {on}, /robot/home, /robot/estop
POST /teleop/start|stop
GET  /cameras                       # enumerate + thumbnails
POST /cameras/confirm               # {workspace: idx, wrist: idx}
GET  /preflight                     # aggregate gate status
POST /record/start {repo_id?, task, num_eps, ep_s, reset_s, resume?}
POST /record/end-episode|rerecord|discard|finish
GET  /record/status
GET  /datasets/local, /datasets/hub
POST /datasets/pull|push {repo_id}
GET  /datasets/{repo_id}/report     # report card (computes+caches)
GET  /datasets/{repo_id}/exclude    # builder state
POST /coach/workspace               # grid + corners + buckets
GET  /coach/next                    # sampled placement prompt
GET  /journal/draft, POST /journal/append
WS   /ws/joints ; GET /cams/{name}  # mjpeg
```

## Risks / open questions
- In-process record loop is the hardest part (threading: cams + serial + episode events). Mitigation: copy LeLab's working loop structure verbatim first, refactor later.
- Serial port contention with LeLab/CLI — RobotManager must fail loud with "port busy" hint.
- CV placement detection accuracy on colored puzzle pieces vs white block — calibrate threshold per task; prompted-vs-actual logging measures its own error.
- MJPEG at 2×640×480@30 over localhost is fine; don't prematurely WebRTC.
