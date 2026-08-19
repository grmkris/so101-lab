# MuJoCo runbook

MuJoCo is the local engineering loop: seconds to launch, deterministic state inspection, headless tests, and no cloud cost. It is not treated as proof of sim-to-real transfer.

## Environment

The existing gitignored environment is `sim/.venv` with MuJoCo 3.10. Add the chess-only dependencies without modifying either production LeRobot environment:

```bash
uv pip install --python sim/.venv/bin/python -r chess_system/requirements-local.txt
```

## Generate and validate

```bash
sim/.venv/bin/python -m chess_system.mujoco.generate_scene
sim/.venv/bin/python -m chess_system.mujoco.validate_reach
sim/.venv/bin/python -m unittest discover -s chess_system/tests -v
```

Generated files:

- `sim/model/so101_chess.xml`: SO-101 model with conservative open-tool collision boxes, `chess_tcp`, and wrist camera.
- `sim/model/chess_scene.xml`: board, 32 free-joint pieces, capture zones, floor, lighting, and workspace camera.
- `chess_system/mujoco/generated/reach_report.json`: sizing gate.
- `chess_system/mujoco/generated/square_poses.csv`: canonical 64-square coordinates.

## View and render

Interactive viewer:

```bash
sim/.venv/bin/python -m mujoco.viewer --mjcf=sim/model/chess_scene.xml
```

Offscreen workspace render:

```bash
sim/.venv/bin/python -m chess_system.mujoco.render_scene
```

Smoke-test a legal move:

```bash
sim/.venv/bin/python -m chess_system.mujoco.backend --move e2e4
```

The kinematic backend intentionally relocates free-joint pieces. It verifies board mapping, legal move expansion, captures, state observation, and commit-after-verification; it does not claim the simulated jaws physically grasped the piece.

## Remote leader teleoperation

Start a compatible publisher on the Mac as described in [teleoperation.md](teleoperation.md), then:

```bash
sim/.venv/bin/python -m chess_system.mujoco.teleop \
  --connect tcp://127.0.0.1:5556
```

Headless transport test:

```bash
sim/.venv/bin/python -m chess_system.mujoco.teleop \
  --connect tcp://127.0.0.1:5556 --headless --duration 10
```

The publisher emits at 50 Hz; MuJoCo consumes the latest valid sample at 30 Hz. A packet gap over 250 ms enters `HOLD`. Joint units are converted from degrees to radians; gripper `0–100` maps linearly into the model actuator range.

## Vertical-grasp result and required path follow-up

`validate_reach.py` now solves a downward `chess_tcp` grasp at every square with ≤3 mm positional error, ≥5° joint-limit margin, and no board-carrier contact. The 20 mm tool / 24 mm piece geometry is what made the near ranks pass. The squat 24 mm piece (mast centered at 14 mm) replaced the earlier 32 mm design because a 32 mm piece could not be lifted clear of its neighbors from a crowded back-rank square before the arm hit its vertical-lift limit.

Before full-set fabrication, complete the remaining path gate:

1. Implement curved hover-to-grasp continuation; near ranks cannot remain perfectly vertical at the 80 mm hover height.
2. Limit interpolated per-joint steps to 15° and reject branch flips.
3. Disable non-target pieces during IK, then restore them for sampled path contact checks.
4. Reject tool/neighbor and arm/board contacts across the full trajectory.
5. Replace the conservative moving-tool proxy with measured jaw-root geometry after the fit coupon.

MuJoCo’s imported SO-101 meshes report several adjacent-link self-contacts in neutral poses. Do not count those known mesh overlaps as task collisions; create explicit simplified robot collision proxies before treating this as a certified collision gate.

## Playing a full game

```bash
# headless, writes chess_system/mujoco/generated/game_report.json
sim/.venv/bin/python -m chess_system.mujoco.play_game --max-moves 200

# with the native viewer (macOS needs mjpython)
sim/.venv/bin/mjpython -m chess_system.mujoco.play_game --viewer
```

The arm plays both colours — it is the only actuator on the board, so every
ply is a physical transfer it must plan, execute and verify. Each turn runs:

```text
engine ranks every legal move (chess_system/engine.py, deterministic)
        ↓
controller probes the ranked list in order (can_execute)
        ↓
first mechanically reachable move is executed and occupancy-verified
```

`chess_system/engine.py` is a small alpha-beta engine rather than Stockfish for
two reasons: the same position must always produce the same ranked list so a
failed game replays exactly, and the caller needs *all* legal moves ranked, not
one best move, because it walks the list past unreachable ones.

### Legality is not reachability

Some legal moves cannot be executed from the current position. A bishop on `f1`
is legally free to reach `e2` while `f2` is occupied, but every collision-free
grasp branch sweeps a finger extension through that pawn before the arm can
lift. This is a property of the position, not a planner defect.

`ChessBackend.can_execute(plan)` preflights a plan by running the real motion
planner over each step — advancing occupancy step by step, so a capture-then-move
plan is probed the way it will run — without moving anything. Because the
planner caches by occupancy signature, a successful preflight makes the
subsequent execution a cache hit rather than a second search.

Probing is lazy and in rank order: a preflight costs a real planning search
(0.4–6 s), so probing all ~30 legal moves every turn would dominate wall-clock.
A strong engine's top choice is usually reachable, so a turn normally pays for
one probe.

Backends that do not implement `can_execute` are treated as optimistic — the
move is attempted and any obstruction surfaces from `execute_plan`.

When *no* legal move is reachable, the game runner stops with
`no_executable_move` rather than crashing. That state is a real result about the
board design, and it belongs in the report.
