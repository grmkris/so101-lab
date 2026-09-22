# Overnight handoff (2026-09-23, ~02:00): SO-101 multi-model pick-and-place benchmark

Kris is asleep. Claude handed this to Codex to finish during the night. Work until morning. Keep a
running log in `notes/overnight-bench-status-2026-09-23.md` (newest entries first) and update it after
every milestone. It is the first thing Kris reads.

## Read first
- **The approved plan:** `/home/kristjan/.claude/plans/soft-brewing-spring.md`. It is the spec; read it all.
- `~/CLAUDE.md` (box rules), `~/code/so101-lab/CLAUDE.md` (lab rules), and the top of `journal.md`
  (entry 2026-09-22/23, "first real pickup": the four facts about the gripper, the cameras and contact).
- Box rules that bite:
  - Work on `main`. Commit small and in sequence.
  - **Never `git add -A` or `git add .`**; stage your own paths only. Never `git stash`. Never reset
    or restore files you did not change: another agent has uncommitted edits in robo-harness
    (`apps/server/src/decision/{jev,jev.test,mock,offline,skill-loop.test,strategies,tactics}.ts`,
    `provider-adapter.ts`, `README.md`, `apps/server/package.json`). Work around them.
  - Before any bun/uv/git push in robo-harness: `export PATH=$HOME/.bun/bin:$HOME/.local/bin:$PATH`,
    or the pre-push hook exits 127.
  - The gate is `heavy bun run check`. Exit 75 means another heavy job held the lock and the gate did
    NOT run; retry. Never pipe `heavy`.
  - Env for arm tools: `set -a; . ~/.config/robo-harness.env; set +a` (ROBO_URL, ROBO_IO_URL,
    ROBO_IO_TOKEN). Never print secrets.

## Done so far (robo-harness, local `main`, NOT yet pushed; the gate kept hitting exit 75)
- `fde320a` robo-io:
  - held joints are measured from their command, which fixes the false "gripper move exceeds
    maximum speed" rejections;
  - servo `temperatures` now appear in `/observe`.
  **Already deployed to lab-pi** (`engine.py`, `drivers.py`; backups in `/home/kris/robo-harness/var/backup-20260923/`) and working.
- `5813f66` two scripts:
  - `scripts/lock-cameras.sh`, **already applied on the Pi**: C922 focus 10, exposure 330, white
    balance 4000; the wrist camera stays manual;
  - `scripts/camera-recover.sh <workspace|wrist>`, deployed on the Pi. Rungs: usbreset, then
    power-cycle the hub port, then restart robo-io. Rungs 1 and 2 were tested live: the wrist camera
    was fresh again after 8 s and 7 s, and the arm was untouched. Rung 4 (Pi reboot, then
    `sudo systemctl start robo-io`) is the caller's job; the arm holds its pose through a Pi reboot.
- Push when a gate run is green: `cd ~/code/robo-harness && git push origin main`.

## Work left in progress by stopped agents (git worktrees; merge onto main, then remove them)
1. `.claude/worktrees/bench-cliproxy` (branch `bench-cliproxy`): **5 finished commits.**
   - `0fbcd7b` generic `cliproxy` provider
   - `6bc47ee` token usage in `chat.finished`
   - `f0ec641` `/api/chat` options `step_cap`, `stall_ms`, `system_append`
   - `863d4e9` headless `bun run chat` client
   - `2ab87a9` `bun run probe-models`

   It had not yet run the gate. Cherry-pick or rebase onto main, run the gate, fix only its own
   problems, and run `probe-models` for gpt-6-astra, grok-4.7, claude-opus-5-5 and qwen3.8-max.
   Record the table in the status log.
2. `.claude/worktrees/manip-tools` (branch `manip-tools`): **2 commits.**
   - `81a1b0c` connected-component bright-object detector
   - `45ec8b6` coordinator-side manipulation config

   Plus **uncommitted work**: `decision/skills.ts` (exports of the helpers) and a new
   `decision/sim-arm.ts` (a simulated arm for tests). Finish these per plan section 4: the general
   tools `move_tcp`, `move_tcp_by`, `descend_until_contact`, `set_wrist_roll`, `gripper` (with
   `stalled_at`), `home`, `look` (with crop), `locate` (SAM-3), and a stale camera treated as
   transient. Add tests, run the gate, merge.
   **Tools must stay general: no mention of a block or of any task.**
3. Remove the worktrees after merging (`git worktree remove`, `git branch -d`).
4. The live coordinator runs from `~/code/robo-harness` main. After merging:
   `bun run build && systemctl --user restart robo-app robo-rerun`. robo-io changes are deployed by
   scp to `lab-pi:/home/kris/robo-harness/python/robo_harness/`, followed by
   `sudo systemctl restart robo-io`. Back up first, and only while the arm is idle and has no fault.

## Commissioning data (plan section 3, only partly done)
- **Arm tool:** `bun /tmp/so101-session/arm.ts state | look TAG | tip X Y Z | joints gripper=N | stop`,
  run from `~/code/robo-harness` with the env above.
  - It does IK on netcup and walks the joints in steps of at most 1.6°. Frames are saved to
    `/tmp/so101-session/TAG-*.jpg`.
  - Contact detection: `/tmp/so101-session/touch.sh X Y [z_start]` descends 3 mm at a time and
    stops at the first step that fails to settle.
  - `/tmp/so101-session/calib.sh NAME X Y` = raise, move above the point, touch, save
    `cal-NAME.jpg`. It is untested; Kris interrupted it.
- **Measured tonight:**
  - Closed fingertips touch the mat at model tip z ≈ **−0.031** when pointing down. The mat is at
    z = −0.054, so the jaws reach about **2.3 cm below `gripper_frame_link`**.
  - The first calibration touch: tip (0.134, −0.042) at contact, fingertip in the workspace image
    at about pixel **(207, 292)**, in frame `/tmp/so101-session/t1-ws.jpg`.
  - In the new workspace view (camera in front of the arm, slightly above), image-left is −y.
- **The block** is on the mat, upright, near tip (≈0.12, ≈−0.01). At pose tip (0.12, 0, 0.03) the
  wrist camera sees it centred. It sits at about pixel (255, 297) in the workspace camera.
- **Home pose is still to be chosen.** Pick it raised and pulled back so the gripper does not hide
  the mat, e.g. tip ≈ (0.09, 0, 0.08). The tip (0.12, 0, 0.03) pose hangs over the work area.
- **Reach:** use at most 0.17 m radius (moves fail at 0.20 m and beyond).
- **The white-table clearance guard** refuses geometry below z ≈ −0.039 on joint origins.
- **Remaining:** about 8 more touches across radius 0.10–0.17 m and pan ±25°, avoiding the block by
  3 cm or more. Fit the homography (with the fingertip offset rotating with pan) and check it on a
  held-out point (target within about 1 cm). Record the TCP offset, the safe polygon and the home
  pose in the manipulation config.

## Arm and camera safety (non-negotiable)
- Keep all robo-io guards. Never use `human`-mode leases to get around the camera guard.
- If a camera goes stale for more than 10 s, run
  `ssh lab-pi /home/kris/robo-harness/scripts/camera-recover.sh <role>`.
  - If it is still stale, reboot the Pi (`ssh lab-pi sudo reboot`), then after boot run
    `ssh lab-pi sudo systemctl start robo-io`, followed by
    `ssh lab-pi /home/kris/robo-harness/scripts/lock-cameras.sh`.
  - If it is still broken, stop the run, leave the arm holding, and log it.
- Stop descents at the first step that fails to settle. Pushing into the table spikes the current,
  and that is what dropped the USB cameras tonight.
- If any servo is above 60 °C (`/observe` `temperatures`), pause 10 min.
- Always end with the arm raised (≥5 cm), no lease held, and status logged.

## Models
- Run: `gpt-6-astra`, `grok-4.7`, `qwen3.8-max` via cliproxy (`http://127.0.0.1:8317/v1`).
- `claude-opus-5-5` uses Kris's Claude subscription, which is **nearly out of credits**. Give Opus at
  most 2 trials, and only after the others have run. Skip it if cliproxy returns quota errors.
- Fable is out of quota and is not used.
- If Qwen has no image input through cliproxy, record it as a handicap; don't drop it silently.

## Priority order if time runs short (every step leaves things working)
1. Merge `bench-cliproxy`, gate, push. Record the `probe-models` table.
2. Finish and merge the manipulation tools and skill docs (`skills/so101/EMBODIMENT.md`,
   `MANIPULATION.md`: general facts only). Gate, push, deploy the coordinator.
3. Commissioning: TCP offset, homography, safe zone, home pose.
4. Bench runner, judge and reset operator (plan section 7), with tests on saved frames.
5. Real-arm smoke: the reset operator does 3 pick-and-places, then 1 trial per model.
6. Only if the smoke passes: trials rotating between models (plan: 32 locations; fewer is fine),
   with evidence under `var/bench/2026-09-23/`.
7. **Always by morning:** a report in `notes/overnight-bench-report-2026-09-23.md` with the
   per-model table, the failure breakdown, what was built, what failed and why, plus a dated
   `journal.md` entry. Commit and push so101-lab. Honest numbers, including "0 trials run
   because X".
