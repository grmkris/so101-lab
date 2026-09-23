# Real-model test preparation — 2026-09-23

Local robo-harness changes are ready: `e2a3d40` adds opt-in passive register readback
through the existing motor owner; `844e7e4` adds a repeatable real-camera/model probe
and an acceptance report. Neither service was restarted or deployed in this work.

The actual workspace/wrist image pair was sent through cliproxy: Astra returned
`reobserve` in 4.828 s, Grok returned `reobserve` in 9.225 s, and Qwen exceeded the
30 s client deadline. The Qwen outcome/billing is unknown. djev was not attempted
because its separate invite credential was unavailable. These are real image-input
adapter checks, not visual-accuracy scores or pickup trials. Zero motor commands,
physical resets or scored pickups were issued. Prices remain unknown.

Intermittent coordinator observation/capture freshness failures prevented some
captures; those attempts sent no model request. Grok and Qwen used the hash-verified
saved real pair from Astra. The source images show the piece and gripper in the
workspace view; the wrist view is usable and shows jaws/mat, with the piece outside
that view at the held pose. No room images are committed to this public repository.

The original boot/epoch/commanded hold was unchanged at subsequent sampled checks,
with no fault/operator and fresh cameras. The 0.808791° elbow residual remains
unresolved. Raw P/I/D/current/load/goal telemetry has not yet been collected.

Engineering validation passed: 305 TypeScript tests, 128 Python tests, final static
checks, build and isolated visual-workbench browser acceptance. These fixture-based
checks are distinct from the real-model requests above.

Next physical step is one attended diagnostic activation and passive trace, not a
pickup attempt. Restarting the motor owner configures torque/gains and rebases the
hold, so it cannot preserve the old failed operation's raw hold evidence. The
attendance/clear-workspace question is pending; no answer has been assumed.
After diagnosis: measured elbow verification, repeatable raised home, measured TCP,
held-out homography error below 1 cm, reviewed safe polygon, watched resets and then
a watched model trial. Existing gains, limits, calibration and completion guards
remain unchanged.

Detailed report: `robo-harness/docs/acceptance-2026-09-23-test-preparation.md`.
Private evidence: `/tmp/so101-real-model-preflight-20260923-02/` and
`/tmp/so101-real-model-preflight-20260923-saved/`. Other failed capture reports are
retained under the same prefix. The diagnosis lane's note/evidence are untouched.
