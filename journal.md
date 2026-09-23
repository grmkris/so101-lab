# Run log

Newest on top. Template:

## 2026-09-23 (overnight) — manipulation tools deployed; benchmark stopped before commissioning

lerobot 0.6.0; lab-pi `robo-io`; lamp on; workspace C922 `/dev/cam_context`, wrist Innomaker `/dev/cam_wrist`, 640×480. Camera settings remained locked (workspace focus 10 / exposure 330 / WB 4000; wrist exposure 221 / WB 3108). No dataset recorded. No object orientation policy evaluated: **0 scored trials, 0 resets, no pickup or descent** in this continuation.

`robo-harness` pushed and deployed through `7434fa5`: generic cliproxy chat, usage/probe CLI, CC detector, TCP-aware general manipulation tools, first-failed-step stopping, geometry/camera/temperature guards, sequence admission and general skills. Full gate: 230 TypeScript tests + 112 Python tests; build and coordinator restart passed. Astra / Grok / Qwen tool and vision probes passed. Opus unavailable (proxy Claude Code version below upstream minimum), no trials attempted.

Bounded upward agent-mode probes exposed a joint completion deadband, one stale-observation refusal, and a non-settling elbow residual of 0.848 degrees against the unchanged 0.8-degree guard. Every failed operation stopped its sequence; no takeover, recalibration, gain/limit change or camera recovery. TCP, homography and home remain uncommissioned, so no benchmark motion was admitted. Arm left holding with no lease, no fault, fresh cameras, servos 24–36 C; model tip z 0.0312 m, approximately 6.2 cm fingertip clearance using the prior contact measurement. Exact TCP clearance remains unverified.

[Report](notes/overnight-bench-report-2026-09-23.md) · [Running status](notes/overnight-bench-status-2026-09-23.md). Evidence local under `robo-harness/var/bench/2026-09-23/`; room images not published to the public lab repository.

## 2026-09-22/23 (night) — first real pickup of the white block, driven by hand from Claude

Continued from the previous session's handoff (`/tmp/so101-session/HANDOFF.md`, tool
`/tmp/so101-session/arm.ts`: IK on netcup, joint walks of ≤1.6°, lease renewed per step).
lerobot 0.6.0, lab-pi `robo-io`, lamp on, overhead C922 = `cam_context`, wrist Innomaker = `cam_wrist`,
gains pan 64 / lift 128 / elbow 96 / wrist_flex 64 / roll 32 / gripper 16, max_speed 2.

**Result: block grasped and lifted ~6 cm** (gripper stalled at 11.1% on it, block rides with the jaws
in both cameras, mat spot empty). Two misses first, each nudging the block 1.4–2 cm.

What made it work — all four contradict assumptions the handoff was working from:
1. **The gripper closes onto its FIXED finger** (the +y one, image-right in the overhead). The
   block must sit against that finger's inner face, not mid-gap. At 86–90% open the moving jaw swings
   nearly level and sweeps a wide area into the fixed finger — a forgiving push-grasp.
2. **The overhead barely sees y.** Collating fingertip pixels over ~10 poses: its image-x hardly
   changes with y; image-y tracks reach (~12.5 px/cm). The handoff's "16 px/cm of y" was a pan/reach
   confound. Overhead is a reach/height gauge, not a y gauge. Wrist image-vertical ≈ y (~45–65 px/cm
   at 3–4 cm), wrist image-x ≈ reach (weak, ~15–25 px/cm).
3. **Model "tip" ≠ fingertip.** With the pose the walker reached, the fixed finger was on the mat
   while `tip` read 2.5 cm; "did not settle" on every step meant the finger was pressing on the mat.
   Earlier the table-clearance guard stopped descent at a model 1.8 cm. Trust the cameras for contact.
4. **The wrist-camera dropout was electrical, not lamp glare.** When a finger landed on the block
   both cameras reset in the same second on the Pi's hub; the Innomaker then failed to re-enumerate
   (`port4: Cannot enable. Maybe the USB cable is bad?`) until Pi + arm USB were replugged. After
   that, wrist frames were clean at 2.2 cm with the same lamp. The prior "truncates below 4 cm"
   correlates with arm load as much as with distance. Fix candidate: cameras on a powered hub with a
   supply separate from the servos.

Other: robo-io refuses an agent lease while any camera is stale — with the wrist camera dead at 2 cm
the arm is stuck in place (human-mode leases skip the guard; not used). The follower boards came back
behind a Genesys hub (05e3:0610) after the replug. The walker moves joints independently, so a long
Cartesian target can wander to a different IK branch — drive to a recorded joint pose instead.

## 2026-09-21 (night) — desk work, no arm: the model fails exactly the cases critic hides from it

Lights off, Kris asleep, **nothing actuated**: no observe, no dry-run, no gain change, no camera
touched. `robo-io` left running and untouched on lab-pi the whole night (74 °C at the end).
robo-harness `8c215cc` → `d7df153`, gate green before each push. Live Jev spend for the night
**$0.0028** (155 cumulative calls, $0.0062 all-time) against a nightly cap of $2.

**Decider comparison (11 offline fixtures, identical observations and candidates).** Gateway
smoke passed live at 973 ms, `reobserve` p=0.98.

| strategy | passed | p50 | p95 | cost | model calls |
| --- | --- | --- | --- | --- | --- |
| rules | 11/11 | 0 ms | 0 ms | $0 | none |
| choice | 10/11 | 308 ms | 388 ms | $0.000442 | all 11 |
| parallel | 8/11 | 302 ms | 374 ms | $0.000455 | all 11 |
| critic | 11/11 | 0 ms | 383 ms | $0.000139 | 4 of 11 |

Three repetitions of `choice` and `parallel` gave **identical pass counts, identical failing
fixtures and identical cost to six decimals** — systematic, not sampling. Every failure is a
case where the right move is *not to move*: both model strategies **re-pick a step that just
failed to move** (the 09-17 `repeated_failures` signature), and `parallel` reaches for `stop`
on a stale frame and on another owner's running operation.

**`critic` wins on accuracy and cost for the same reason:** it is rules-first, model-for-approval.
Seven fixtures report `no review needed` and resolve in 0 ms with no call; every fixture the
model gets wrong is in that set. The model never gets a vote on the cases it fails. Run `critic`
on hardware; `parallel` should not drive an arm. Detail: `robo-harness/docs/decider-comparison-2026-09-21.md`.

**Coverage bar, fixed (`ce35b44`).** `overhead_calibration.py` measured axis-aligned extents,
which measure the camera's heading as much as the sweep's reach: the 0.2 m / 90° arc the search
actually sweeps reads span_x 0.059 / span_y 0.283 at heading 0° but 0.200 / 0.200 at 45° — the
same arc passing or failing a 0.15 m bar on orientation alone, so every real recording was
rejected by construction. Coverage is now extent along the points' own principal axes (0.283
major, 0.059 minor, at any heading), with a separate smaller bar on the minor axis because
collinear points fix no plane however far apart they are. `scripts` is on the pytest path now.

**Raster footprint, asserted (`d7df153`).** "3 degrees — far less than the camera's footprint"
was a comment and nothing else. `rasterCoverage` now measures both gap directions against the
footprint — 0.05 m radially between arcs, 0.012 m along the widest arc between looks, against
~0.208 m of visible mat at the 0.1 m scan height — and the scan skill vetoes **before its first
move** instead of sweeping rings it never looks at. **The footprint ratio itself is an unverified
assumption**: the wrist Innomaker's field of view is recorded nowhere in the lab, and it looks
along the jaws rather than straight down. A test halves it to prove it is load-bearing. Point the
wrist at a ruler at a known height and replace the number.

**Discrepancy for the record:** the brief stated the lab-pi profile is lift **P96**; the live
profile on the Pi reads **P128** (`shoulder_lift`), set 09-18 after the second trace at working
reach. Nothing on the arm was changed. `~/briefs/so101-lab-overnight.md` corrected 09-21.

**PENDING FOR KRIS — two edits to myplan `SO-101 Lab/00 Overview` (`doc_QblnKgCzgiEdmZmR`).**
The connector was not authorised in that session and the login was deferred, so the Overview
still says:
1. **lift P96** — should read **pan 64 / lift 128 / elbow 96 / wrist_flex 64 / roll 32 /
   gripper 16**, the live lab-pi profile.
2. **"next session starts with a P sweep"** — stale; that blocker was resolved 09-18. The
   current blocker is the **unverified wrist-camera footprint ratio** (`wristFootprintRatio`,
   2.08, in `decision/skills.ts`): the three-arc raster's sufficiency rests on it and the
   Innomaker's field of view is recorded nowhere.

**MORNING TASK FOR KRIS — measure the wrist camera footprint.** It is the one unverified number
the search now depends on, and it needs a person, not a run. Lay a ruler across the mat, put the
tip a known height above it (the scan height, 0.10 m, is the case that matters), and read off how
much of the ruler the wrist frame spans. That width divided by the height is `wristFootprintRatio`
in `apps/server/src/decision/skills.ts`, currently the assumed **2.08** (≈0.21 m of mat at 0.10 m).
No arm motion is required — park the tip by hand with `robo-io` stopped, or read it off a frame
from any recording where the tip height is known. If the real ratio is much below ~1.0 the shipped
three-arc raster no longer tiles and the scan will now say so instead of sweeping blind. Note the
camera looks *along* the jaws rather than straight down, so the footprint is a skewed quad: record
the across-jaw width and say which it is.

## 2026-09-21 — first daylight-less run: the detector was blind because the lights were off

robo-harness `main` `b24228d` (+ a staged, uncommitted grok-4.7 capability change, gate green),
lab-pi `robo-io` up 3d21h, profile P: pan 64, **lift 128**, elbow 96, wrist_flex 64, roll 32,
gripper 16. Jev spend $0 (rules tactician only).

**Run #1 `14e7ea15` (recorded `23b4a572`, 4752 samples at 9.83 Hz, `captured`):** 186 moves,
113 completed / 71 failed / 2 cancelled, ended `max_seconds` after 480 s still inside
`scan_for_piece`. Arm swept pan −32.2° to +46.8°, lift −53.9° to −19.9°, gripper untouched at
62.3%. **Zero piece sightings in 4484 wrist frames.**

**Cause: the room was dark.** The run started at 22:33 local with the lights off. Overhead
frame mean brightness **5.6/255** during the run against **84.8** the same afternoon; the wrist
frames are **1.0** against 95.9, with a maximum pixel value of **1**. The piece detector
thresholds at >170, so nothing in the wrist image could ever qualify — the sweep was
mechanically perfect and optically blind. CLAUDE.md lever 2 (lock the lighting) applies to the
agent stack too, and nothing in the runner checks it.

**Also measured:** 71 failed moves were `shoulder_pan` short by 1.37° mean / 1.60° max while
lift (0.27° mean at P128), wrist_flex (0.16°) and elbow (0.74°) stayed inside tolerance —
the opposite joint from every previous session. Worth a trace before blaming the sweep.

**Before the run, unrelated:** `robo-app`/`robo-rerun` restarted onto the staged grok-4.7
change; live catalog now reports xai `grok-4.7` vision true (`source: configured`, not
`documented` — the live host does not match the gateway rule the staged test asserts).
Repo gate green (100 python tests + typecheck) on that staged tree.

**Next:** lights on, repeat the identical run. Then add a frame-brightness gate to the scene so
a dark room aborts in one move instead of 480 s.

## 2026-09-18 (overnight) — the arm climbs; six infrastructure bugs, each of which looked like "the model can't do it"

Free-rein night (Kris: lights on, mat clear, P ceiling 128 trace-gated, place-back allowed).
robo-harness `main` `de427bd`…`5d9d1ad`, lab-pi profile + engine redeployed several times
(backups in `var/backup-2026-09-18-pgain/`), Jev spend $0 — every attempt ran the rules
tactician, because none of the failures were decisions.

**Gain, resolved.** `servo_step_trace.py` (now reads `Present_Temperature` and samples rest
jitter) in the forward-leaning hover pose: raising `shoulder_lift` 1.8° moved 0.61° at P48,
1.32° at P64, **1.85° at P96** (403 mA), 1.76° at P128 (566 mA); `shoulder_pan` residual
0.39° at 32 → 0.05° at 64; `wrist_flex` return residual 0.79° at 32 → 0.26° at 64. Zero rest
jitter anywhere, servos ≤41 °C. Profile: **pan 64, lift 96, elbow 96, wrist 64, roll 32,
gripper 16**. The climb that failed 17/17 moves on 09-17 now completes 14/14 and the tip goes
3.5 → 9.7 cm. Control smoke `done`, residuals 0.22–0.30.

**Then five more, each found by reading a recording against FK:**
1. `moveTip` solved once and walked the goal in joint space — the tip's path between two joint
   poses is not a straight line: a "7 cm outward" step **lost 6 cm of height**. Now waypointed
   (≤3 cm), re-solved from measured, judged on where the tip ended up.
2. The wrist Innomaker **re-enumerates under arm motion** (`/dev/cam_wrist` → a new `videoN`);
   the stale handle reads nothing forever. It refused all 312 moves of one run. `lab_cameras`
   now reopens a device that has delivered nothing for 1 s.
3. A **wedge of white table** at the mat edge passed the background rule and the arm went to
   centre on it. Bright regions touching the frame edge or >12 % of it are background now; a
   real piece between the jaws (0.7 % of frame) still detects.
4. The motor owner planned every operation **from the measured pose**, so a pan-only move
   re-commanded the other joints to wherever gravity had let them sag — a ratchet that sank the
   raised arm 4 cm over thirty *completed* moves. Unmentioned joints hold their command now…
5. …which then failed every move, because the completion check still judged those held joints,
   and a loaded joint sits ~1.3° below its command. A move is judged on the joints it asked to
   move.
Plus: a camera stall no longer ends a run (it waits, up to 15 s, six times), skills respect the
run's wall clock, `joint_health` is in the scene so a stalled joint stops a run, and a `place`
skill puts the piece back for repeat attempts.

**How it ended (attempt #11):** 233 moves, **zero failures**, recording `captured`
(2710 samples, 5.6 Hz, 32 MB MP4 `13e53f58`), arm sweeping three arcs at 9.6 cm from
r = 0.20 m in to r = 0.10 m, lift residuals 0.63–0.72°, no stall and no abort. It found
nothing — and two frames from that recording say why: with the tip at r = 0.147 m the **wrist
camera is looking at the mat's edge and the white table**, because the gripper is still over
the table, while the overhead frame shows the piece far out on the mat. **The mat itself
starts beyond the arm's usable reach.** Next session's first move is physical: slide the mat
toward the arm so the piece sits 15–20 cm from the base, then `bun run jev --observe --task
pickup-skills` to confirm the wrist sees it before spending a run.

**The wall we hit: torque, not kinematics.** With the arm extended at r ≈ 0.27 the lift is
1.2–1.4° short at P96; re-tracing there, P128 moved it 2.2° but drew **1.5 A and took the servo
from 52 °C to 88 °C** in one step — the trace's own guard stopped it (transient; back to 51 °C a
minute later, status clean). So the workspace is capped at **0.22 m** — the radius where the
arm's own moves complete — not at the 0.35 m the solver will happily return. Re-traced at
working reach afterwards, **P128 is the right lift gain there**: residual 0.39° at 949 mA with
the servo flat at 51 °C (the 1.5 A / 88 °C spike was only at full extension, which the cap now
refuses). With that, multi-joint transit went from failing every move to 8/8, then 233/233. Next session's first move is physical: put it 15–20 cm from the
base, then rerun `bun run jev --execute --supervised --task pickup-skills --record`.

Also caught by the gate: the repo's "a live smoke without a key is blocked" test inherited this
host's real `AI_GATEWAY_API_KEY` through the spawned app and made a **billed** Gateway call.
The harness hands tests no ambient credential now.

## 2026-09-17 (night) — skill-level tactician, two recorded pickup attempts, stream mode; blocker is gain under load

robo-harness `main` (`de427bd`…`bc94ca7`), lab-pi `robo-io` restarted twice (stream deploy, backups
`var/backup-2026-09-17-lazyjpeg` / `-stream`), lerobot 0.6.0, both cameras fresh, white piece on the open mat
~20 cm out, lighting unchanged. Jev spend for the day $0.0033 total (both attempts ran the rules tactician).

**Rebuilt the decision layer as jev-drone does it** — model picks *skills*, code owns the loops and the veto
(`decision/skills.ts`, `scene-state.ts`, `tactics.ts`, `skill-loop.ts`, DR 0011). Two skills had to change
before a real run could work: the search now **rises to a vantage height and sweeps a serpentine raster**
(a 5 cm hover sees about a hand's width of mat, so no pan sweep could ever find a piece 20 cm away), and
centring **takes a step and keeps it only if the piece measurably moved closer in the image** — the estimated
image Jacobian was the fragile part, one wrong sign pushed the piece out of frame. Simulated arm now does
scan → centre → open → descend → re-centre → close → lift in 209 moves (was: four stalls and a lucky back_off).

**Attempt 1** died after 5 moves: `Control loop deadline missed`. The Pi was at 81.3 °C, `throttled=0x80008`,
and `robo-io` was JPEG+base64-encoding **every** frame of both cameras at 30 fps — 7.3 ms per `imencode`
measured, about half the process's CPU, in the same process as the 30 Hz motor loop, for frames nobody asked
for (consumers pull at ≤10 Hz). Encoding is now lazy (83 % → 64 % of a core) and the runner caps wrist
captures at one per 400 ms. After that: `/observe` age 16.8 ms p50 / 42.6 ms worst against a 250 ms deadline,
idle and while recording.

**Attempt 2** (recorded, 438 s, 2355 samples at 4.85 Hz, 27 MB MP4): swept all three arcs, never saw the piece.
Both cameras stayed fresh the whole run, so it was **blind, not broken** — `shoulder_lift` is unresolved in
30 of 34 multi-joint moves, including the first 17 (the climb), so the sweep ran at 3.5 cm. Under that, every
joint settles ~0.7° short of a 1.6° step (152 of 209 pan moves "failed" at the 0.8° tolerance while still
moving ~0.9°).

**Stream mode** (DR 0012) shipped for exactly this: a command that *leads* the measured position accumulates
the error a re-planned bounded step never can, bounded to one `max_step` so a joint breaking free cannot
lurch. Deployed and measured at 10.07 Hz on the Pi (5.2 ms round trip): against a −3° setpoint `wrist_flex`
travelled 1.58° and `shoulder_lift` 1.32° — the lift moved at all, which stepped commands never achieved —
then both sat ~1.5° short, while the unloaded return landed within 0.09°. Two degrees of lead at P=48 is all
the torque there is.

Also fixed three recording faults that made every recording useless: one transient stale observation ended the
whole recording (223 ms p95 age against a 250 ms gate — that is why attempt 1 kept 39 frames), every
overlapping poll counted as a missed deadline (160 ms round trip under a 100 ms poll), and starting a recording
demanded a motion-grade observation. Recordings now report `captured` with `sampling_fps_achieved`; ~6 Hz is
the ceiling, one sample per round trip. MP4 export is fine at that rate; LeRobot **dataset** export is not
(it refuses gaps over 250 ms).

**Blocker, measured, for the next session:** gain, not geometry (top-down solutions exist from 0.10 to 0.35 m
radius), not the control path, not the model. Next: `servo_step_trace.py` on `shoulder_lift`/`elbow_flex` at
P 48/64/96 under load, then a profile change — needs a human, P gains are not changed unattended. Third
attempt deliberately unused: same configuration, same failure.

## 2026-09-17 (evening) — weak joints were LeRobot's P=16 dead band; P=32 makes the control smoke pass

robo-harness `scripts/servo_step_trace.py` (robo-io stopped, one joint, ≤1.8° steps, ~470 Hz register reads):
wrist_flex lifting against gravity moved **0.00°** of 1.8° at P=16 (32 mA) vs **1.41°** at P=32 (143 mA);
shoulder_pan/lift residuals 0.44–0.75° at 16 vs 0.00–0.48° at 32. Supply 5.3 V at rest, sags to 4.7 V under
load (not the main cause). LeRobot writes P=16 "to avoid shakiness" on every connect — hidden under teleop and
policies (moving targets, no per-step settle check), exposed by bounded agent steps with 0.8° completion.
robo-harness profile now sets `p_coefficients` 32 on the five arm joints, gripper 16 (deployed to lab-pi,
backup in `var/backup-2026-09-17-pgain`). Pose: upright neutral, tub removed, piece on open mat.

Control smoke rerun (gripper +4, wrist_flex +2, back), same limits/candidates:
- rules: **done**, 4/4 moves completed, 8.6 s
- Jev choice: **done**, 5/5 completed, 14.2 s, $0.00028
- Jev critic: **done**, 5 completed + 1 failed (residual 0.92 > 0.8) → reobserve → corrective −1.06° → done, 17.2 s
Before the gain change the same three runs all ended `repeated_failures` on the wrist return.
Also 09-17: follower USB board stopped enumerating after a power pull (`device not accepting address`);
only a full power cycle of Pi + arms recovered it — watch that cable/hub port.

## 2026-09-17 — Jev decision runner on the real arm: first supervised runs

robo-harness `main` (decision runner `6a5c51d`…`goal syntax fix`), lab-pi `robo-io` restarted 13:51 after a full
replug (boot `b3f28111`, 09-09 table-clearance fault cleared), lerobot 0.6.0, cameras workspace+wrist fresh
(~50 ms). Jev = `typesafe-ai/jev` via Vercel AI Gateway, `ai@7.0.105`, ZDR off (Hobby plan). Total model spend
$0.0018. Arm leaning forward with the jaw near the mat, white piece and tub right in front (not moved).

- **Gateway:** needed card + a *paid* top-up (free credits exclude Jev). Smoke 479 ms, `reobserve` p=0.97.
- **Fixtures (11) with live Jev:** critic 11/11, choice 10/11, parallel 8/11 (parallel says `stop` where
  reobserve/wait is right). p50 ≈ 300 ms.
- **Joint baseline (≤1.8° steps, measured change of commanded):** gripper 1.2/1.8 and 0.96 back ·
  wrist_roll 1.1–1.7 (all completed) · wrist_flex 1.5 and 0.9 back · elbow_flex 1.2, then 2 of 3 failed to
  settle (0.7–0.8) · **shoulder_lift 0.26 · shoulder_pan 0.09–0.26 — both failed**. Same weak-shoulder
  signature as 09-09. Hypothesis to test: P=16 static-friction deadband (lerobot #3400) and/or supply sag.
- **Bug found live:** a signed goal after `=` meant relative, so a return to `wrist_roll=-8.48` moved another
  −8.5° (away from the table). Goals are now `joint+=N` relative, `joint=-N` absolute. Also full 2% steps were
  refused by ~0.1 sensor jitter at the exact max_step; candidates now keep 0.2 headroom.
- **Control smoke (gripper +4, wrist_flex +2, back), same limits/candidates:** rules 3 moves ok then 2
  wrist_flex failures · Jev choice 2 ok, 2 failures · Jev critic 3 ok, 2 failures. All stopped on
  `repeated_failures` at wrist_flex +1.8 (residual 0.9–1.6). Gripper ended at 47% open; the opened jaw sits
  close to the mat, so likely contact rather than a decision problem. No fault latched.

Next: raise the arm (shoulders don't respond, so by hand with robo-io stopped, or re-probe after a P/power
check), clear the tub, rerun the smoke from a pose with clearance; then pickup.

## 2026-09-07 — robo-harness drove the real SO-101 (agent-workbench powered runs, 09-06/07)

`~/code/robo-harness` — the standalone SO-101 agent workbench (Bun/TS coordinator on the
netcup box + a Python FastAPI motor-owner and Rerun worker on `lab-pi`) — was powered against
the real arm on 2026-09-06 and 2026-09-07. It uses `lab_cameras.CameraOwner` for capture, so
so101-lab stays the camera source of record. The lab-pi profile records the activation:
"2026-09-06: user confirmed clear workspace and powered activation … initial joint control
only, ≤2 deg/percent and ≤2 units/s; Cartesian geometry not commissioned."

- **Powered motion verified, measured.** Bounded gripper opens (+2 pts over 1.5 s) complete
  with measured deltas ~1.2–1.6, residual 0 on the untouched joints and ≤0.5 on the moved
  one; `stop` releases control and holds the commanded pose (operator → null, no fault
  latched). Short runs record ~45–47 frames / 2.8–4.4 MB Rerun replay.
- **Cameras healthy through the lab owner.** workspace + wrist both fresh (age ~30–50 ms),
  MJPG 640×480. robo-harness's own dormant `devices` capture path now asserts the MJPG fourcc
  took (it did not before) and recovers from a read error instead of dying — matching the lab
  rule that only `lab_cameras/` owns `/dev/cam_*`.
- **Two LLM providers verified read-only on the arm** (Alibaba qwen3.8-max, xAI grok-4.6):
  each observed the arm and reported joint state with no motion. Agent control uses 3 s
  leases, bounded moves checked against the commissioned limits, and measured completion; a
  lost lease cancels motion (the safe direction).
- **Software:** robo-harness was brought onto the house Effect/Bun conventions this window
  (Effect Schema contracts, Config, a decoded I/O boundary, the house chat loop with
  stop-conditions + a stall watchdog). It runs from `main` via systemd (`robo-app`,
  `robo-rerun`); config and provider keys live outside the repo.

Open items for the lab: `joint_offsets_deg` are still all 0 (`cartesian_reviewed: false`
unresolved); robo-harness's `assets/so101.urdf` is a verbatim copy of
`phone_teleop/SO101/so101_kinematics.urdf`, now labelled as such at both ends.

## 2026-08-23 — room host `lab-pi` built; camera layer done; thermal limit found

lerobot 0.6.0 (`~/lab/.venv`, torch 2.11.0+cpu, aarch64), no dataset recorded yet.
Full detail: `notes/lab-setup-2026-08.md`. Headlines:

- **`lab-pi` is live**: Pi 4B 4GB, 916 GB SSD at `/data`, udev-stable device names, LCD
  status display, calibration imported, first commanded motion verified (±5° pan, return
  drift 0.26°).
- **`lab_cameras/` built and verified.** Dual MJPG 640×480 for 20 s: C922 **30.87 fps**,
  Innomaker **29.53 fps**, **0 read failures, 0 repeated frames** — the pairing that was
  unreliable for a year on macOS is clean here. `flock` ownership verified across `kill -9`.
- **`CAP_PROP_BUFFERSIZE=1` is the bug** that made the Innomaker look dead again (1916
  failed reads, opened as MJPG, no error). It halves that camera and starves it entirely
  when the C922 is streaming. Never set it.
- **Snap latency 1839 ms → 5.3 ms** (347×) by owning the cameras in-process instead of
  shelling out to `capture.py` per snap.
- **Health gate baselines**: `so101_pickplace_wall_v1_20260722_174720` and
  `so101_blue_pegs_v1_20260723_171824` both show **0 frozen runs, cross-camera MAD ~86**.
  The Innomaker's known frame loss did not corrupt either dataset we trained on.
- **`placo` installs on aarch64** and `arm.ik_to_xyz` solves in 1–6 ms on the Pi — with cv2
  4.13 already there, the whole perceive→IK→command loop can run on the room host. No Mac
  relay needed.
- ⚠ **Thermal**: 4 busy threads → throttling at 40 s, steady state **84.7 °C / 1231 MHz
  (−18%)**. The encoder benchmark (h264 ultrafast, 2.88× realtime cold) is really ~2.4×
  throttled, i.e. **~1.2× for two cameras**. Streaming encoding still keeps up, but the Pi
  needs a fan before long sessions.
- `gemini_er/` is now host-portable (`devices.py` resolves arm + cameras by role on either
  host); `lab_cameras/preview.py` serves a live browser preview and a pixel picker, which is
  how calibration will click points on a host whose cv2 has no GUI.

Next: reposition + lock the C922 (40–50 cm, 45°, manual exposure/WB/focus, 50 Hz), then the
first real recording, then re-fit the calibration chain on the new geometry.

## 2026-08-21 — desk CLI live: tub-in/out blocked by piece-on-rim

lerobot 0.6.0, driver venv, C922=0 / Innomaker=1. Scripted `gemini_er/desk.py serve` (no ACT).
- Pickup of the white block **beside the tub** failed: two closes latched the **tub rim** (wrist confirmed; opened immediately). Piece never left the mat.
- Wrist cam hang froze serve twice (Innomaker). Patched: snap via `capture.py` subprocess timeout; hold **commanded** pose not measured (gravity droop).
- Arm left hovering (pan ~−5, lift ~2.5, gripper open). Piece still against tub wall.
- Next: nudge piece ~3 cm off the rim, then pick in open space → over-mouth place → extract.

## 2026-08-13 (afternoon close) — v2 mission complete: cube placed in box autonomously

Session wrap after ~22h total. Afternoon highlights:
- **The headline**: the v2 stack completed "put the white cube in the plastic
  box" fully autonomously — ER 2 cycled run_task episodes (~65 s cadence, 5 s
  between), verified from camera each cycle under an anti-give-up mission, and
  one cycle nailed the drop. Camera-confirmed. Zero human hands.
- Box→mat extraction resisted round 2 (~25 episodes) — in-box grasping is the
  model's hardest skill; landed twice earlier in the day, dice didn't repeat.
  The fix is fine-tuning, not retries.
- Hardening shipped during the grind (all committed): anti-hallucination
  `gripper_state` in arm_status (model kept imagining held cubes; the servo's
  position sensor + our measured signatures — empty≈1, held 7-22, open 45+ —
  now overrule its vision); **mission-aware heartbeat** (reconnect amnesia made
  the model forget missions; every heartbeat now restates the active mission);
  camera watchdog VALIDATED in production (caught an Innomaker death in 13 s,
  parked the arm safely).
- **Innomaker wrist cam: condemned.** 5 deaths across 3 port arrangements,
  including on a dedicated port — dies under sustained streaming, refuses
  15 fps, renegotiates modes randomly. BUY A REPLACEMENT (any fixed-focus UVC;
  even a second C922). Note: the day's 4/4 grasp streak RAN with the wrist cam
  (320²+640² @ fps15) — dual-view is worth restoring once hardware exists.
- C922 quirk discovered: renegotiates 16:9 modes (640×360/320×180) after hub
  re-cabling — always verify delivered frame size, not just open success.
- Colab shut down by user at session end. Tailscale keys were 1-day ephemeral.

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
