# Attended passive elbow readback — 2026-09-23

Kris explicitly confirmed he was beside the arm with the workspace clear and approved
one motor-owner restart followed by passive elbow readback. The diagnosis panel was
notified before activation and after the result. Its reserved diagnosis note and
private evidence were not edited.

## Activation and startup movement

Installed exactly the four Python modules from robo-harness `e2a3d40`, after matching
the deployed baseline, saving a backup and validating the staged hashes. Added
`ROBO_PASSIVE_DIAGNOSTICS=1`; restarted `robo-io` once. Restarted `robo-app` once to
expose the readback endpoint. The coordinator's shutdown Stop/Hold accounts for
control epoch 1. The visual-motion admission switch remains closed.

The profile is unchanged: pan/lift/elbow/wrist-flex/roll/gripper P =
64/128/96/64/32/16, maximum step 2, maximum speed 2. No calibration, trajectory or
completion-guard change. Installed LeRobot remains 0.6.0.

**Startup physically shifted the elbow by 1.318681°**, from measured 55.164835° to
56.483516°. The new commanded hold is 56.131868°. All other measured joints matched
the pre-restart snapshot. No explicit move operation was submitted; startup's
torque/gain initialization and measured-position rebase are physical actions.
These endpoint observations do not measure the startup transient or prove its cause.

The former command was 54.356044° with a persistent 0.808791° residual. That old
raw goal/current/load state was not captured before restart. This new trace cannot
explain that earlier miss or be described as its passive readback.

Old boot: `06506771-83c4-416d-9bd7-e7cd68aa642c`, epoch 30.
New boot: `538bde8f-b498-4f14-aa33-2420334a8a70`, epoch 1 after coordinator activation.

## Actual raw trace

Request `c980ced6-f14a-4d9e-8d73-5f94aed95cc9` completed with **3 sample sets,
42 register reads**, no read errors, and maximum diagnostic read latency 3.240 ms.
Each sample is non-atomic and brackets its fields with two goal reads. All goal
reads matched. Sampling used the existing motor owner and its existing lock;
no second bus owner, retry, gain write, movement or return-to-start was introduced.

| Register | Raw result | Decoded meaning |
| --- | --- | --- |
| Goal_Position | 2663 throughout | 56.131868° |
| Present_Position | 2667 throughout | 56.483516° |
| P / I / D | 96 / 0 / 32 | Confirmed actual coefficients |
| Operating_Mode | 0 | Position mode |
| Torque_Enable | 1 | Enabled |
| Present_Current | 4, 3, 3 | 26, 19.5, 19.5 mA |
| Present_Load | 88 throughout | Signed register units, not calibrated force |
| Present_Voltage | 53 throughout | 5.3 V |
| Present_Temperature | 39, 40, 39 | °C |
| Moving / Status | 0 / 0 | Not moving; no reported status error bits |

The new steady residual is **4 raw counts / 0.351648°**. During the trace all six
measured and commanded joint values stayed constant, including the post-trace
checkpoint. The raw goal decodes exactly to the coordinator command; P96 is applied.
The sampled current is low in this held pose. Load 88 has no calibrated force
interpretation here; this short idle trace cannot rule out friction, load effects,
voltage sag during movement, or earlier command timing effects.

No fault, controller, operation or running chat remained at the post-trace check.
Both cameras were fresh. No new provider call, dataset recording, orientation-policy
trial, pickup, contact or reset was performed. Existing lamp/camera framing was used;
workspace C922 and wrist Innomaker remain 640×480.

After the trace Kris clarified that the lamp had been turned on. I had not announced
or rechecked that state before starting; I did not toggle it. A later read-only image
checkpoint showed the wrist usable but the workspace still dark around the arm. The
current controls were read without writes: workspace manual exposure 329, gain 0,
WB 4000, zoom 150, pan -7200, tilt -14400; wrist manual exposure 330, gain 60,
WB 3108. Private checkpoint: `/tmp/so101-light-on-check/`. This is a visibility
follow-up, not a servo or readback change.

## Evidence and next step

Private evidence and SHA256 manifest:
`robo-harness/var/passive-readback-2026-09-23/c980ced6-f14a-4d9e-8d73-5f94aed95cc9/`.
It contains pre-restart images/observation, post-restart and post-trace observations,
the submitted request, all raw rows and the reduction summary. Room images are not
committed to this public repository.

Pi backup: `/home/kris/robo-harness/var/passive-diagnostics-20260923.before-20260923-222515/`.
Reviewed profile SHA256: `79d19cae64fe0a53139a434dd1c50d2102b3a8ed574dc7598148345933cce658`.

Activation/readback acceptance is complete. The previous under-tracking cause is
still unproven. Before pickup, the next physical diagnostic should be a separately
bounded, watched elbow step with pre/post evidence, stopped on its first failure,
without automatic return or retries. This passive sampler intentionally stops when
control is acquired, so it cannot record that move's raw transient. Any proposed
in-motion instrumentation needs separate design/review. Geometry/home/reset/model
commissioning gates also remain open.
