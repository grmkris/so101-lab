# Overnight SO-101 benchmark status — 2026-09-23

Newest first. Overnight decisions follow the approved handoff and plan; morning resumption is logged separately below.

## 2026-09-23 09:17 CEST — hardware camera zoom comparison

- Kris explicitly requested hardware crop/zoom experiments after fixing lighting. This supersedes the overnight preference for software-only crop for these morning camera tests. The arm stayed stationary throughout; no lease, motion, service restart or provider call.
- Saved the original C922 V4L2 controls, then captured zoom values 100, 125, 150 and 200 (1x, 1.25x, 1.5x, 2x), all at 640x480. Also tested 150 with electronic pan -7200 / tilt -14400. Focus 10, manual exposure 330, white balance 4000 and all wrist settings remained unchanged.
- Selected **zoom 150, pan -7200, tilt -14400** for live review: the shifted crop centers the empty gripper/object and useful mat area; 2x loses more upper-arm context. This is a visual framing preference, not proof of extra optical resolution or coverage across all robot poses. Reach-area coverage still needs checking during commissioning.
- Live controls now hold the selected framing; startup/recovery scripts are unchanged, so persistence across re-enumeration is not guaranteed. Original values were zoom 100 / pan 0 / tilt 0. Restore with `ssh lab-pi 'v4l2-ctl -d /dev/cam_context --set-ctrl=zoom_absolute=100,pan_absolute=0,tilt_absolute=0'`. Freeze the chosen view before homography calibration; the current mapping is still unset.
- Private before/after control dumps, `summary.json` and a four-view `comparison.jpg` are under `robo-harness/var/bench/2026-09-23/camera-zoom-0911/`; source frames/state are `commissioning/zoom-*-0911-*`. Final 09:15 capture confirms identical measured joints, no fault/operator, fresh cameras (24/30 ms), max servo 41 C. Public notes contain no room images.
- Workbench: `http://100.105.51.45:8940/` over Tailscale. Motor/camera host: `lab-pi`, `100.77.154.45`.

## 2026-09-23 08:57 CEST — lighting corrected; elbow lag reproduced in isolation

- Kris corrected the lighting and asked to continue. Fresh 08:50 workspace imagery clearly shows the arm, empty gripper, mat and object; the overexposure blocker is resolved. Wrist imagery is fresh but dark and mostly mat from this pose. Frames are saved as `commissioning/lighting-check-085038-*`.
- A further 6 mm upward request completed two joint operations, raising the model tip 4.33 mm, with 3.00 mm final Cartesian error (`reached: false`). The handoff's example home `(0.09, 0, 0.08)` failed dry IK (18.3 mm error at the wrist limit) and was never commanded. A reachable raised candidate `(0.105, -0.03577, 0.06)` stopped at its first step: elbow residual 0.910 degrees, beyond the unchanged 0.8-degree threshold. No descent or contact.
- Inspected the failed coupled step, then issued one bounded elbow-only diagnostic: target change -1.6 degrees, predicted upward/outward with ample mat clearance. It moved -0.791 degrees and stopped with residual 0.808791 degrees. This rules out simultaneous joint motion as the sole cause of the lag; do not treat a failed settle as table contact in this raised pose. Last operation `ea3781a9-7a13-4d0e-9387-088a2aa02a76` failed honestly; no automatic replay.
- The temporary console's failure-cleanup fallback used the wrong endpoint/body. A separate private `commissioning/morning-diagnostic.ts` corrects it to `/control/cancel-owner` with `boot_id`, matching the production adapter, and adds the single bounded elbow test. Production code/config are unchanged. The previous operation had already dropped its lease; post-failure observations confirmed no owner in both cases.
- Final state at 08:57: model tip `(0.117977, -0.035645, 0.040785) m`, visually raised empty gripper, fault/operator null, unchanged boot, fresh cameras, maximum servo 41 C. Evidence: `commissioning/elbow-diagnostic-stop-*`, `morning-actions.jsonl`, `morning-measured.jsonl`, and the original action/measured ledgers. All room images remain local.
- Decision: stop physical probes here. The next hardware work is diagnosis of elbow settling under load, with any gain change treated as a reviewed configuration change with backup. Keep the 0.8-degree completion guard and all motor limits. TCP, homography, safe polygon, repeatable home, reset smoke and model smoke remain unfinished; no pickup, descent, reset or scored trial occurred.

## 2026-09-23 08:49 CEST — user-requested morning motion diagnostic

- Correction to the earlier completion wording: the overnight report and software delivery were complete; the physical benchmark was not. Zero scored trials were run, and the live runner/reset adapters remain unfinished. The user is now asking to resume movement.
- At 08:47, commanded a 5 mm upward model-tip diagnostic from the measured parked pose through the existing guarded commissioning console: agent lease, no takeover, at most 1.6-degree joint steps, measured completion and first-failed-step stopping. Two joint operations completed. No descent, grasp, calibration or gain/limit changes.
- Measured model tip moved from `(0.124250, -0.037682, 0.031183)` to `(0.122199, -0.036778, 0.034454) m`: 3.27 mm upward, with 2.83 mm total error from the requested target. The helper returned `reached: false`; joint completion is not Cartesian accuracy. Final elbow residual was 0.741 degrees, inside the unchanged 0.8-degree joint threshold.
- Post-move state at 08:49: no fault or operator/lease, unchanged boot, both camera streams fresh, maximum servo 41 C, raised hold. Last operation `0b1d97d0-2aad-44d7-8eb9-a9d9e855a8f5` completed. Action and measured-state ledgers remain in ignored `robo-harness/var/bench/2026-09-23/commissioning/`.
- Two coordinator evidence attempts were refused (stale wrist image; observation HTTP 503); incomplete manifests are preserved in `morning-motion-0847/` and `morning-motion-0848/`. The commissioning console then saved fresh direct I/O frames with the existing 400 ms guard as `commissioning/morning-motion-0850-*` (actual capture 08:49; filename is a label). Workspace/wrist frame ages were 56/17 ms. No freshness threshold changed.
- New visual blocker: the workspace JPEG is severely overexposed in morning light. Fresh frames do not establish usable vision. Stop this diagnostic with the arm raised; restore usable exposure before visual alignment/contact work, then resolve measured positioning and commission TCP, homography, safe polygon and home. Benchmark resets/model smoke remain gated; scored trials and resets remain zero.

## 2026-09-23 07:27 CEST — final continuation verification

- Verified `so101-lab` `main` and `origin/main` match at `9f63362`; the Markdown report, HTML report, journal entry and status log are present and pushed before 07:30.
- Verified `robo-harness` `main` and `origin/main` match at `ac75f4b`; `robo-app` and `robo-rerun` are active. A read-only status check shows no robot error, fault, operator or lease, no running chat, unchanged boot ID, fresh workspace/wrist cameras (about 29/35 ms), and servo temperatures at or below 39 C.
- No safe unattended priority remains: the next physical item is attended TCP/contact commissioning and held-out homography validation. The profile stays uncommissioned and the arm stays raised; scored trials, resets and descents remain zero.
- Decision: stop at the morning gate with this checkpoint pushed. Do not issue motion, enable the live runner, change gains/limits/geometry, or alter the preserved concurrent worktree.

## 2026-09-23 07:21 CEST — final morning report

- Watcher reached its 07:20 checkpoint: 193 received samples from 04:04–07:20 CEST, zero alerts, one pose and boot ID, maximum observed servo 40 C, and both camera streams fresh. Two turn-interruption gaps remain explicitly disclosed; no evidence is claimed for those intervals.
- Final read-only state: fault/lease/operator null, `robo-app` and `robo-rerun` active, unchanged boot and raised tip `(0.12425, -0.03768, 0.03118) m`. The last operation remains the earlier failed upward probe with elbow residual 0.848 degrees; no new motion was issued. The empty gripper is visibly raised and the object remains on the mat in the 07:18 workspace JPEG.
- `bench:capture` first refused a stale workspace frame at 07:17; the new 07:18 directory succeeded after three bounded observation retries and preserves original JPEGs/hashes. No guard was relaxed. Report MD/HTML and journal are finalized with this evidence for the morning push; code is green and pushed through `ac75f4b` (262 TypeScript / 112 Python tests). Scored trials, resets and descents remain zero.

- Housekeeping: removed the clean `bench-cliproxy` worktree after verifying all five commits are patch-equivalent on main. `git branch -d` refused its cherry-picked branch, so that branch is retained. The `manip-tools` worktree still has another agent's uncommitted `decision/skills.ts` and `decision/sim-arm.ts`; preserved intact. Both committed manipulation patches are already on main.

## 2026-09-23 06:38 CEST — monitoring remains clean after temperature drift to 40 C

- Combined watcher summary: 151 samples through 06:37 CEST, zero alerts, one observed pose and boot ID, fresh cameras, max servo 40 C. The threshold is 60 C; no cooling pause or intervention is indicated. Both coordinator services are active.
- Decision: preserve the raised hold, continue the persistent watcher to 07:20, then perform the final read-only state check and push the final report/journal before 07:30. Scored trials remain zero.

## 2026-09-23 05:45 CEST — runner race fix pushed; final monitoring window

- `ac75f4b` pushed after the full serialized gate and pre-push: 262 TypeScript tests, 112 Python tests. The offline runner now waits for an in-flight health check before writing a completed artifact; its tenth test covers the late-fault race. No live adapter or physical command was added.
- Report MD/HTML and journal now name `ac75f4b`, preserve zero scored trials, and disclose watcher sampling gaps. Continue the persistent watcher through 07:20; final status/report push remains required before 07:30.

## 2026-09-23 05:37 CEST — offline orchestration pushed; report updated

- `547fff1` pushed after `heavy bun run check` and the serialized pre-push gate: 261 TypeScript tests, 112 Python tests. Nine new tests exercise trial sequencing, exclusive artifacts, model rotation, fresh session/frame identities, uncertain evidence and reset outcomes, STOP/heat/wall cancellation and the three-error cap. It has no live adapter; every result is labelled offline with zero scored trials.
- Updated report MD/HTML and journal with shipped versus deployed state and the two monitoring gaps. Physical commissioning/reset/model smoke remain blocked; no gain, limit, geometry or runtime changes were made.
- Watcher is persistent in tmux. Across three preserved log segments: 90 received samples through 05:36 CEST, zero alerts, unchanged pose/boot, no fault/lease/chat, fresh cameras and max servo 39 C. Continue to 07:20, inspect the complete window, then push final report/journal before 07:30.

## 2026-09-23 05:32 CEST — offline runner validation; monitoring made persistent

- Continuing priority 4 after the renewed instruction: added an offline orchestration fixture for home/capture/chat/judge/reset, append-only artifacts, model rotation with fresh sessions, shared caps and cancellation. It has no installed live adapter and reports zero scored trials. The full serialized gate is running after owned lint/type fixes.
- Correction to the 05:18 decision: commissioning blocks live activation, not implementing and testing offline orchestration. No live motion adapter is being installed, and the uncommissioned profile remains unchanged.
- Turn interruptions ended the first two watcher processes. Logs are preserved separately: `watch-morning.jsonl` ends 05:14:47, `watch-morning-continued.jsonl` spans 05:17:37–05:25:38. Restarted at 05:27:28 in tmux session `so101-bench-watch-20260923`, logging `watch-morning-detached.jsonl` until 07:20. These are sampling gaps, not evidence of a fault. All received samples are clean: same raised pose, no lease/fault/chat, cameras fresh, max servo 39 C.

## 2026-09-23 05:18 CEST — live runner remains gated after offline triage

- Inspected the remaining priority-4 boundary. `bench.ts` is a safe schedule/stop preflight; `bench-reset.ts` is an injected fixture loop; `bench-replay.ts` is offline-only. The missing live adapter would have to admit model chat and motion before TCP/homography/home commissioning, reset smoke and model smoke exist.
- Decision: do not add or activate live orchestration from an uncommissioned profile. This preserves the handoff's fail-closed gate and the arm's raised hold. Continue the separate read-only watcher (`watch-morning-continued.jsonl`) through 07:20; no code or hardware action is justified.

## 2026-09-23 05:10 CEST — first hour of monitoring clear

- 66 read-only samples from 04:04 through 05:09 CEST; zero alerts, unchanged measured pose and boot ID, no fault/lease/chat, fresh cameras, max servo 39 C.
- Both coordinator services remain active. `robo-harness` main matches origin at `8c19f2b`; report/journal checkpoint `5673c49` is pushed. No additional implementation or hardware action; continue the parked-arm watch to 07:20 and final documentation push before 07:30.

## 2026-09-23 04:23 CEST — parked-arm monitoring continues

- Re-read handoff/plan and current commits. Both repositories are clean and pushed. Priority 3 is physically blocked; priority 4 has tested offline components but no live runner/reset/SAM/VLM adapter. Physical smoke and scored trials remain zero.
- Watcher has 18 consecutive clean samples from 04:04 through 04:21 CEST: unchanged pose and boot, no fault/lease/chat, cameras fresh, max servo 39 C. Evidence: `robo-harness/var/bench/2026-09-23/watch-morning.jsonl`.
- Decision: preserve the raised hold and continue read-only monitoring to 07:20, then push the final report/journal update before 07:30. No code, configuration, motion or provider changes are warranted during this window. Corrected report/journal wording: runtime restart was through `e3b28c7`; `8c19f2b` is an offline reset fixture, not live deployment.

## 2026-09-23 04:03 CEST — reset fixture loop green

- `8c19f2b` pushed after the serialized full gate: 252 TypeScript tests, 112 Python tests. The fixture-only reset loop requires commissioned TCP/homography/home, fences source/target, reobserves before contact, requires first-failed-step contact plus independent lift/placement evidence, never advances an unknown outcome, and pauses at three attempts. It is not wired to live hardware or model tools.
- Reset tests cover a successful synthetic pick/place, unknown motion, null contact, failed lift verification, three-attempt cap, commissioning gate, reused frames and pre-abort. No arm command was issued.
- Decision: stop implementation here for the night. The next safe physical step is attended TCP/homography commissioning and reset/model smoke; do not activate the fixture adapter by inference from the current evidence.

## 2026-09-23 03:49 CEST — replay pushed; coordinator runtime restarted safely

- `e3b28c7` pushed to robo-harness main after the serialized gate: 248 TypeScript tests, 112 Python tests. The offline replay validates frame hashes, camera roles, freshness, clock domain and before/lift/after ordering; it never calls providers or motion. Docs record that live runner/reset execution is unfinished.
- `bun run bench:judge` replayed `var/bench/2026-09-23/replay-idle/manifest.json` from two read-only snapshots. Result: `pick_success: null`, `place_error_m: null`, `needs_review: true`, absent SAM/VLM proof retained as null. One accepted CC candidate per workspace frame; no lift frame and no scored trial.
- `heavy bun run build` passed; `robo-app` and `robo-rerun` restarted and are active. Live status after restart: HTTP 200, no run/fault/operator, same tip `(0.1243, -0.0377, 0.0312) m`, cameras 45/27 ms, servos 25/29/39/24/26/26 C. Invalid `wall_ms=999` request returned 400; no chat was started.
- Final physical decision: remain parked. TCP/homography/safe polygon/home and reset/model smoke are still not commissioned; no descent, calibration or benchmark trial is justified overnight.

## 2026-09-23 03:37 CEST — read-only evidence capture and hardware recheck

- New evidence collector saved original JPEGs, metadata and SHA-256 hashes in `robo-harness/var/bench/2026-09-23/safety-0337c/`. Workspace image confirms empty gripper raised and object on the mat. No provider call, motion or lease.
- The first two captures refused HTTP 503 from the coordinator's 250 ms observation freshness guard. Read-only sampling confirmed intermittent cache ages of 159–242 ms and a few refusals, while direct I/O, both cameras and the arm were healthy. Collector now retries only an observation HTTP 503, at most four times, and records retry count; guard thresholds are unchanged. Successful capture used one retry. Failed capture manifests remain intact.
- Latest saved observation: model tip `(0.1243, -0.0377, 0.0312) m`, fault null, operator null, camera ages 31/23 ms, temperatures 25/29/39/24/28/26 C. Pose unchanged; no recovery or cooling intervention needed.
- Evidence collector gate is running. Remaining physical prerequisites are unchanged; no calibration values were filled in from these images.

## 2026-09-23 03:33 CEST — bounded trial chat shipped

- `a8c0743` pushed to robo-harness main. Added coordinator-enforced optional `wall_ms` (1 s–30 min), exposed as `bun run chat --wall-ms`; an expired cap cancels the turn even if its client has gone away. Mock integration verifies a running operation cancels and releases ownership, without a second model step.
- Headless chat now refuses a pre-aborted start, decodes streamed events, skips replay duplicates, closes readers, and bounds cancellation drain. A missing `chat.finished` remains an unverified outcome; it is never automatically retried as a new trial.
- Full gate and serialized pre-push passed: 243 TypeScript tests, 112 Python tests. Runtime activation will happen after the next stable checkpoint while the arm is idle.
- Report/HTML/journal were updated and pushed in lab commit `207605c` with the earlier offline fixture, explicitly distinguishing schedule/judge/reset policy from unfinished live execution. Now adding append-only read-only evidence capture and offline replay. Physical trials remain blocked on commissioning and smoke.

## 2026-09-23 03:11 CEST — offline fixture green; continuing runner work

- Resumed from `90bed02`/`7434fa5` and preserved the uncommissioned geometry. Read-only arm check at 03:07 CEST: same raised tip `(0.1243, -0.0377, 0.0312) m`, no lease/fault, camera ages 43/52 ms, maximum servo 39 C. No motion issued.
- `881cee7` adds deterministic fenced/spaced schedules, fail-closed stop conditions, a recorded-frame judge, and the three-attempt reset policy. Full `heavy bun run check` passed (239 TypeScript tests, 112 Python tests); pushed to origin/main (pre-push gate also green). Corrected camera provenance: wrist recordings cannot establish table position, even when a homography is supplied. Missing SAM/VLM evidence stays unverified.
- `bun run bench` is explicitly schedule preflight only and refuses the current uncommissioned config. Decision: finish runner/reset/evidence orchestration offline before exposing live execution. A successful offline fixture is not the attended calibration/reset/model smoke gate.
- The required report and journal already exist and are pushed. Keep updating them with later green pieces; scored physical trials remain zero.

## 2026-09-23 02:51 CEST — final overnight safety recheck

- Final direct I/O check: tip `(0.1243, -0.0377, 0.0312) m`, fault null, operator/lease null, workspace/wrist ages 15/46 ms, temperatures shoulder 25, lift 28, elbow 38, wrist-flex 24, roll 26, gripper 26 C. `robo-app` and `robo-rerun` remain active.
- No benchmark trial, reset, descent or further calibration command was issued after the prior failed upward step. The report, HTML artifact and journal are pushed in so101-lab commit `217f3ce`; robo-harness manipulation is pushed in `7434fa5`.
- Morning decision is explicit: resume with attended TCP/homography commissioning and held-out validation; keep geometry disabled and do not start the runner until that gate, reset smoke and model smoke pass.

## 2026-09-23 02:45 CEST — manipulation pushed and deployed; report checkpoint

- `7434fa5` pushed after the final gate (230 TypeScript tests, 112 Python tests) and a green pre-push hook. Stage was limited to the 19 owned manipulation paths. The concurrent decision commit was preserved.
- `heavy bun run build` passed; restarted `robo-app` and `robo-rerun`, both active. Backed up the 0600 coordinator environment file and added the three probed cliproxy model/vision aliases. Live `/api/status`: HTTP 200, all three available, no runs, no fault or lease, cameras fresh, servos 24–36 C.
- Config remains uncommissioned. Decision: no more physical calibration attempts tonight after the upward non-settling result; keep the raised park. Continue useful offline fixture work, without silently enabling geometry or admitting benchmark trials.
- Created the required report and dated journal entry, with honest zero trials. HTML companion contains no private room images or fabricated trial frame strips. It is a checkpoint and can be updated with subsequent offline work.

## 2026-09-23 02:38 CEST — raised park and measured residual finding

- First full manipulation gate passed: 229 TypeScript tests and 112 Python tests. A further deadband regression is now added; the final gate is running after waiting for the shared heavy slot.
- Ran bounded, agent-mode vertical raise probes through the existing supervised executor. No takeover, no descent, no object contact, no gain/limit changes. Evidence: `robo-harness/var/bench/2026-09-23/commissioning/` (console, action ledger, measured observations, frames, raise logs).
- The temporary console's 3 mm waypoints plus 0.15-degree joint convergence stalled in the motor completion deadband. General tools now use 0.8-degree joint convergence while retaining the strict 2 mm measured Cartesian success criterion. A simulated 0.6-degree residual test verifies progress without stationary retries and honestly reports a remaining 2.3 mm residual as incomplete.
- A fresh upward plan later stopped on its first failed operation: elbow residual 0.848 degrees, just outside the unchanged 0.8-degree motor limit. A previous raise also stopped on a stale observation before submitting its next step. These are observed safety stops, not pickups or calibration touches.
- Current raised pose: model frame approximately (0.1243, -0.0377, 0.0312) m; 8.5 cm above the mat, approximately 6.2 cm fingertip clearance using the earlier 2.3 cm contact measurement. Workspace image visibly shows the empty gripper raised. No fault, no operator/lease, cameras fresh, servos 24–33 C. Exact TCP remains uncommissioned.
- Decision: preserve all motor guards and inspect failures before any further motion. No benchmark until held-out calibration, home, reset smoke and model smoke pass.

## 2026-09-23 02:22 CEST — manipulation integration and commissioning preparation

- Provider/chat plumbing passed the complete gate (218 TypeScript tests, 112 Python tests) and was pushed through `a7626ff`. A concurrent agent's `dd9057b` decision-layer commit is preserved.
- General manipulation tools, TCP-aware IK, contact stopping, software crop/locate, sequence admission, skills and simulated-arm tests are implemented. Formatting/lint/types/graph/knip pass after fixing owned test issues. The full gate was terminated with SIGTERM during passing tests; it is incomplete and is being retried through `heavy` (75 means wait).
- Current read-only hardware check: no fault, cameras fresh at about 23 ms, servos 24–32 C. Workspace image is clear. Wrist exposure is the locked 221 value, gain 0; its current view is mostly black mat with the object at the bottom. No settings changed and no actuation yet.
- Safety correction before commissioning: the inherited temporary `arm.ts` walker retries failed operations (and acquires with takeover). Do not use it for contact work as-is. Use guarded agent acquisition without takeover and terminate on the first failed/non-settling step. Do not infer a measured TCP from the approximate 2.3 cm vertical offset alone.
- The model-frame height is 6.3 cm above the mat; actual fingertip clearance is lower. Establish a measured raised park during commissioning before declaring the >=5 cm end-state requirement met.

## 2026-09-23 01:50 CEST — model probes and first integration

- Cherry-picked the five provider/chat/client commits onto main (`20f3734`, `eb70da1`, `dceca35`, `ff61e06`, `6ca651a`). While the heavy slot was occupied, also merged the completed detector/config commits (`f321cdf`, `bf7671e`). No unrelated edits staged.
- Fixed imported test typing/lint errors and unused exports; the full gate is now running. Probe credentials are explicitly exported rather than implicitly loaded from secrets.env.
- Read-only arm check: no fault/control, cameras fresh (workspace 47 ms, wrist 23 ms), servos 25–32 C; model tip z 0.009 m (6.3 cm above mat, before subtracting fingertip offset). No motion performed.

| Model | Tool calls | Image input | parallel_tool_calls:false | tool/image/flag latency ms |
| --- | --- | --- | --- | --- |
| gpt-6-astra | pass | pass (Red) | pass | 1676 / 1334 / 2859 |
| grok-4.7 | pass | pass (Red.) | pass | 1245 / 1239 / 1218 |
| qwen3.8-max | pass | pass (Red) | pass | 2559 / 3634 / 2599 |
| claude-opus-5-5 | blocked | blocked | blocked | 406 / 394 / 398 |

Opus was checked after the primary three. All requests returned HTTP 400: the upstream identifies itself as Claude Code 2.1.258, while this model requires 2.1.280+. Decision: do not mutate shared cliproxy/Claude infrastructure during this run; record Opus unavailable and use the three working models. Qwen demonstrated image input through cliproxy; no vision handicap in this probe. Evidence: `robo-harness/var/bench/2026-09-23/probe-{primary,opus}.json`.

## 2026-09-23 01:45 CEST — started

- Read the handoff, `/home/kristjan/.claude/plans/soft-brewing-spring.md`, `~/CLAUDE.md`, lab rules, architecture, and the 2026-09-22/23 journal entry.
- Main `robo-harness` has local commits `fde320a` and `5813f66` ahead of `origin/main`; the Python changes and camera scripts are already deployed per handoff. Preserved unrelated uncommitted edits listed by the handoff.
- Decision: follow the handoff priority order. First merge and validate the cliproxy branch, then manipulation tools/skills, then commissioning, fixture, smoke, and benchmark only if all safety gates pass.
- Decision: no arm actuation until the software gate and coordinator deployment are green. During hardware work use the existing agent guard, stop any descent on the first non-settling step, recover stale cameras only through the documented ladder, pause on any servo over 60 C, and end raised with no lease.
