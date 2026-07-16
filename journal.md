# Run log

Newest on top. Template:

```
## YYYY-MM-DD — <what>
- lerobot: <version/commit> (record) / <version/commit> (train) / <version/commit> (infer)
- dataset: <repo_id> (<n> eps, placement policy, orientation policy)
- lighting: <locked? brightness?>
- result: <what happened>
```

---

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
