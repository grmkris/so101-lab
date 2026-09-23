# Overnight SO-101 benchmark status — 2026-09-23

Newest first. Kris asleep; decisions are made within the approved handoff and plan.

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
