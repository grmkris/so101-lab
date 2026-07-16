# Eval checklist (before blaming the model)

1. Same lerobot version as training? (`pip show lerobot` / check the train notebook)
2. Lights on, same as recording? (policy works ~120 brightness, dies ~50–60)
3. Camera untouched since recording? Index still right? (`python scripts/camview.py 0`)
4. Arm base hasn't shifted? Bowl/target in the recorded spot?
5. `rm -rf ~/.cache/huggingface/lerobot/kris0/eval_*` (FileExistsError otherwise)
6. Still broken → `lerobot-replay` one episode FIRST. Replay perfect = policy/pipeline problem. Replay broken = hardware/calibration problem.

# Record checklist

- Task variation: random POSITION, consistent ORIENTATION (until dataset > ~100 eps).
- Consistent grasp style, slow-ish smooth motions, redo fumbled episodes.
- 60–80 episodes minimum for reliability.
- Record and eval in the same session — nothing moves in between.
- Log the run in journal.md (version, lighting, dataset) BEFORE moving on.
