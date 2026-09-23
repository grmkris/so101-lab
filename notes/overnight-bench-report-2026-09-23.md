# Overnight SO-101 benchmark — 2026-09-23

Updated 2026-09-23 04:23 CEST; read-only monitoring continues until morning. **0 scored trials. No pickup-rate comparison is available.**

The provider integration and general manipulation tools are green, pushed and deployed. Physical commissioning stopped before calibration touches: upward probes exposed a motor-completion deadband, a transient stale observation and one elbow non-settling step. The arm was left raised with no lease; no descent or pickup was attempted during this continuation. The prior evening's human-directed pickup is not counted as a benchmark trial.

## Per-model results

| Model | Tool / image / flag probe | Scored trials | Pickup rate | Place error | Steps / tool calls / invalid calls | Time / tokens per trial |
| --- | --- | ---: | --- | --- | --- | --- |
| GPT-6 Astra | pass / pass / pass | 0 | N/A | N/A | N/A | N/A |
| Grok 4.7 | pass / pass / pass | 0 | N/A | N/A | N/A | N/A |
| Qwen 3.8 Max | pass / pass / pass | 0 | N/A | N/A | N/A | N/A |
| Claude Opus 5.5 | unavailable / unavailable / unavailable | 0 | N/A | N/A | N/A | N/A |

Probe latencies (tool / image / `parallel_tool_calls:false`, ms): Astra 1676 / 1334 / 2859; Grok 1245 / 1239 / 1218; Qwen 2559 / 3634 / 2599. These are connectivity/capability probes, not manipulation scores. Qwen image input worked. Opus returned HTTP 400 because upstream requires Claude Code 2.1.280+ and the shared proxy reports 2.1.258; shared proxy infrastructure was left unchanged. Opus ran no trials and consumed no trial allocation.

## What shipped

`robo-harness` main is pushed through `8c19f2b`. The latest complete gate passed **252 TypeScript tests and 112 Python tests**; the pre-push hook passed again. Build passed and `robo-app`/`robo-rerun` were restarted at 03:48 CEST from the tree through `e3b28c7`. The later reset fixture in `8c19f2b` has no live adapter and was not activated on hardware. Live HTTP status confirmed the three primary cliproxy vision models, fresh cameras, no fault and no active controller.

- Generic cliproxy provider, chat usage, bounded run overrides, headless chat client and capability probe CLI.
- Connected-component bright-object detector and strictly decoded coordinator manipulation configuration.
- General `move_tcp`, `move_tcp_by`, `descend_until_contact`, `set_wrist_roll`, `gripper`, `home`, `look` with software crop, and `locate` through the existing budgeted SAM-3 path.
- TCP offset applied in the rotating gripper frame; safe-polygon/radius/table fencing; fresh camera and temperature checks; first failed step terminates a motion tool; one shared executor reserves an entire sequence against interleaving.
- General embodiment/manipulation skill documents, simulated-arm and HTTP integration tests, and decision 0013. The tools and model skills contain no benchmark-object instructions.

The inherited Python speed/temperature fix and camera scripts were already deployed by the previous session; they were included in the earlier green push through `a7626ff`. No Python service restart, motor recalibration, gain change, limit change or camera recovery was performed in this continuation.

## Why physical trials did not start

The manipulation config remains uncommissioned: TCP lateral offset, held-out homography, reliable safe polygon and home pose are absent. The previous approximately 2.3 cm fingertip extension is useful for a conservative raised park, but is not a full TCP calibration. A numeric homography was not invented from one touch.

A bounded upward probe showed that demanding 0.15-degree convergence repeats goals inside the motor owner's normal completion tolerance. The helper now accepts the reviewed 0.8-degree joint convergence and still judges Cartesian success from its measured 2 mm residual. The regression test verifies it does not hammer stationary sub-deadband commands or report a 2.3 mm miss as success.

Later upward steps stopped at a stale observation and at elbow residual **0.848 degrees**, outside the unchanged 0.8-degree limit. Both stops were inspected before any further action. The empty gripper is raised; descending for nine touches and then repeated resets without reliable return-to-home validation was not justified. Commissioning and real-arm smoke remain required before a scored run.

## Failure and intervention breakdown

- Model alignment / reach / pushing / false-success / misuse failures: **not measured** (no trials).
- Hardware observations: one stale-observation refusal before submission; one non-settling upward elbow step; no latched fault. Camera recovery count: 0. Servo cooling pauses: 0.
- Reset-operator attempts/interventions: 0. Reset smoke: not run. Model manipulation smoke: not run.
- Offline benchmark fixture shipped in `881cee7`; hashed evidence capture in `e9440d4`; replay and provenance validation in `e3b28c7`: seeded model rotation, >=3 cm target spacing inside the reviewed polygon/radius, fail-closed STOP/fault/camera/temperature checks, saved-frame judge and three-attempt reset decision policy. Camera provenance is enforced; absent SAM/VLM evidence remains unverified. `bun run bench` only produces a schedule and refuses the current uncommissioned config. Live runner execution and automated SAM/VLM judge integration remain unfinished; the fixture reset loop is tested but not wired to hardware; no offline check is counted as a physical smoke or scored trial.
- Initial full gate was externally terminated during passing tests; it was retried. `heavy` exit 75 was treated as contention and retried, never reported as a pass.

## Arm end state and evidence

Read-only monitoring began at **04:04 CEST** and remains active until 07:20 CEST. Through 04:21 there are 18 consecutive samples, no alerts, no pose/boot change, no fault or lease, fresh cameras, and a maximum servo temperature of 39 C. The JSONL log is local at `var/bench/2026-09-23/watch-morning.jsonl`. This is a parked-arm observation window, not a motion or reliability benchmark.

At the 2026-09-23 03:49 CEST post-restart recheck: fault null, operator null, workspace/wrist camera ages about 45/27 ms, servos 25–39 C; the measured pose was unchanged. Recorded raised model-frame position is **(0.1243, −0.0377, 0.0312) m**: 8.5 cm above the mat, approximately **6.2 cm fingertip clearance** using the earlier contact-height measurement. This clearance is approximate pending TCP commissioning; workspace imagery independently shows the empty gripper raised. Torque remains enabled, holding the pose.

Evidence on netcup: `robo-harness/var/bench/2026-09-23/`: `probe-primary.json`, `probe-opus.json`, and `commissioning/` (guarded console, action ledger, measured observations, raw camera frames, raise logs). There is no trial frame strip because there are no trials. Private room images remain local and are not copied into this public lab repository.

Next physical gate: an operator-reviewed return-to-home and TCP/contact session, nine distributed mat points with a held-out error within about 1 cm, then three reset pick-and-places and one trial per available model. Keep the motor limits and first-contact stop in force.
