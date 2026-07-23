# Lab Console — UX spec

Companion to SPEC.md. The CLI problem: every intent ("record 10 more eps") requires re-stating the whole rig (ports, ids, cameras, paths). The UI inverts this: rig stated once, intents are 1–3 fields.

## Principles
1. **Rig profile kills the flags** — ports/ids/cameras/brightness band/HF user stored once, verified by preflight, inherited everywhere. Forms only contain per-session deltas.
2. **Intents, not commands** — IA organized by practitioner intent (collect / extend / train / eval / correct), never by lerobot binary.
3. **Show the command** — every action has a fold revealing the exact CLI it runs/generates. Trust + escape hatch.
4. **Guardrails are UI** — preflight gates recording; `save_checkpoint_to_hub` always on; no deletes (exclude lists only); `rollout_*` naming automatic; journal draft every session.
5. **Convention over configuration** — names auto-suggested (`act_<dataset>_vN`), defaults from crib-sheet (40k/16/5k, transforms on, wandb on), advanced flags behind a fold.
6. **Restart-safe** — all state derived from disk/Hub, never from app memory. Kill the app mid-anything, reopen, continue.

## Information architecture
- **Dashboard** — rig status, HF auth, in-flight work (training progress from Hub ckpts), suggested next action derived from state (e.g. eval notes say "weak ±45°" → suggest DAgger session).
- **Robot** — connect/disconnect, calibrate (with staleness), teleop toggle, home / torque / E-stop (always visible), camera panel + verify.
- **Datasets** — merged local+Hub list, sync badges (local-only / hub-only / synced). Detail: episode grid (thumbnails, per-ep stats), report card, exclude-builder (ticks → `--dataset.episodes` string), actions: Extend · Replay ep · Push/Pull · Train on this.
- **Trainings** — run list (Hub `kris0/*` models auto-imported as past runs). Detail: lineage (dataset + excludes + warm-start parent), Hub checkpoint timeline as progress, wandb link, eval notes, actions: Rollout this ckpt · DAgger · Continue training.
- **Rollouts** — episodic eval or DAgger correction sessions bound to a checkpoint; per-episode success/fail + condition tags (position bin × orientation) → eval matrix → coach targets.
- **Settings** — rig profile, HF auth, journal path, workspace/coach config.

## Record flow
1. Entry: "New dataset" (auto-named `<task>_<ts>`) or "Extend" from a dataset (resume flags invisible).
2. Form: task string (remembered per dataset), n episodes, ep length, reset time. Everything else from rig profile.
3. Preflight (auto): arm connected · calibration fresh · cams verified via thumbnails ("this is workspace?") · brightness in band · disk. All green → Start.
4. HUD: live cams, episode counter + phase (REC/reset), coach target overlay when enabled, controls mirroring CLI keys — keep✓ / re-record↺ / discard✗ / finish■ — running tally, brightness live, per-ep quick note.
5. Exit summary: kept/redone counts, brightness stats, coverage delta → actions: Push to Hub · Journal draft · Record more · Train on this.

## Train flow
The app **prepares, registers, tracks — never executes** (training happens on Colab / HF Jobs).
1. Form (prefilled from dataset): name (auto vN), excludes (from episode grid), init = from-scratch (default at our scale) | continue-from-ckpt (picker over a run's Hub ckpt timeline), steps/batch/save_freq, transforms/wandb toggles. `save_checkpoint_to_hub` locked on.
2. Target: **Colab** → generated version-matched cell (git checkout v0.6.0 … full crib-sheet convention) + copy button; **HF Jobs** → one-click (greyed until HF Pro); **local MPS** → allowed with "slow" warning.
3. Run registered `launched`; **progress = polling Hub model repo for `checkpoints/NNNNNN/`** — no agent inside Colab, survives restarts. Status: draft → launched → training (first ckpt seen) → complete (target step reached / final push) → evaluated (eval notes added). Stalled = no new ckpt for > save_freq-equivalent time → surfaced on dashboard.
4. Run detail: lineage graph, ckpt timeline, wandb loss link, eval notes; Continue-training creates a child run pre-wired to the chosen ckpt.

## Rollout / eval flow
1. Pick ckpt (from run) → mode: episodic | DAgger.
2. Conditions plan (optional): grid of position bins × orientation buckets to cover; each episode tagged, success/fail one-tap during reset phase.
3. DAgger: intervention indicator (tab), intervention count per ep; corrections accumulate as new episodes → "add to dataset & retrain" action creating the child training run.
4. Output: eval matrix on the run page; failures feed coach targets for the next record session. `rollout_*` naming automatic.

## CLI → UI mapping
| CLI today | UI |
|---|---|
| cam-index verify snippet | Preflight thumbnails + confirm |
| lerobot-calibrate ×2 | Robot page button + staleness badge |
| lerobot-teleoperate (5 lines) | Teleop toggle |
| lerobot-record (10 lines) | Record wizard |
| --resume --dataset.root | "Extend" button |
| lerobot-replay | "Replay" on episode row |
| lerobot-rollout episodic/dagger | Rollout wizard |
| Colab cell assembly | Train form → generated cell |
| push_to_hub snippet | "Push" button |
| --dataset.episodes crafting | Episode grid ticks |
| manual journal entry | Auto-draft + one-click append |

## Wireframes (indicative)
```
┌ Recording: so101_puzzle_v1 ─ ep 12/30 ─ ● REC 0:43/1:00 ─┐
│ [workspace cam]              [wrist cam]                  │
│ coach target: cell C2, rotate +45°                        │
│ [✓ keep & next] [↺ re-record] [✗ discard] [■ finish]     │
│ kept 11 · redone 2 · brightness 121 ✓                     │
└───────────────────────────────────────────────────────────┘

New training (from kris0/so101_pickplace_wall_v1…)
name  [act_wall_v4]   data 57 eps · excl [57]
init  (•) scratch  ( ) continue from ckpt…
steps [40000] batch [16] save/[5000]   transforms✓ wandb✓ ckpt→Hub✓(locked)
target (•) Colab cell → copy  ( ) HF Jobs (Pro)  ( ) local ⚠slow
▸ show generated command

act_wall_v3_final · training
lineage: wall_v1 (57 eps, −[57]) ← warm-start act_wall_v3@10k
ckpts: 5k 10k 15k 20k 25k ▮▮▮▮▮░░░ 25k/40k   wandb: 0.113 ↓
eval: strong center/90° · weak edges + ±45°
[rollout ckpt] [DAgger] [continue training]
```

## Open UX questions
- Episode thumbnails: worth extracting first-frames at record time (cheap) vs on-demand (slow page)? Leaning record-time.
- Dashboard "suggested next action": rule-based from state (v1) vs LLM-composed (later).
- Eval matrix in v1 or after coach? Leaning: tags + tally in v1, matrix visualization with coach.
