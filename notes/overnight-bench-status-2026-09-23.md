# Overnight SO-101 benchmark status — 2026-09-23

Newest first. Kris asleep; decisions are made within the approved handoff and plan.

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
