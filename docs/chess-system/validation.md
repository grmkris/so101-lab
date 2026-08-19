# Calibration, validation, and recovery

## Calibration layers

Keep these artifacts separate and versioned:

1. Leader motor calibration.
2. Follower motor calibration.
3. Stock-gripper kinematic frame.
4. Chess-extension TCP offset and reinstall fixture result.
5. Board carrier pose relative to pan pivot.
6. Workspace camera intrinsics and fiducial homography.
7. Wrist camera intrinsics/extrinsics when a reliable replacement exists.
8. Simulator actuator and camera parameters.

Changing any physical mount invalidates every downstream calibration that depends on it.

## Empty-board vision calibration

Mount the printed fiducial tabs and remove every piece. With the pinned driver environment:

```bash
DRIVER=/Users/kristjangrm/Code/github-com/eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python

$DRIVER -m chess_system.vision.occupancy \
  --calibration-dir chess_system/.local/board-calibration \
  --camera 0 --calibrate-empty
```

Observe a populated board:

```bash
$DRIVER -m chess_system.vision.occupancy \
  --calibration-dir chess_system/.local/board-calibration \
  --camera 0 \
  --output chess_system/.local/rectified.png
```

The verifier detects marker IDs 0–3, fits image-to-board homography, rectifies the 8×8 playfield, and compares each square with the empty reference. Tune the occupancy threshold using labeled empty/occupied frames; do not tune it during a game.

Abort thresholds:

- Board translation above 2 mm.
- Board rotation above 0.5°.
- Missing fiducial.
- Any unexplained occupancy change.

## Automated tests

```bash
sim/.venv/bin/python -m unittest discover -s chess_system/tests -v
```

Coverage includes:

- Geometry, axes, reach envelope, capture zones, and clearances.
- Packet serialization, joint validation, ordering, and watchdog expiry.
- Normal legal moves and illegal-move rejection.
- Captures, castling, and en passant step expansion.
- Operator-assisted promotion.
- Visual mismatch preventing engine-state commit.
- MuJoCo opening and capture integration.

## Simulation gates

### Sizing and vertical-grasp gate

`validate_reach.py` certifies the deterministic radial envelope, pitch clearances, and a downward `chess_tcp` grasp on all 64 squares. It enforces ≤3 mm Cartesian error, ≥5° joint-limit margin, and no board-carrier contact.

### Required curved-path/contact gate

Before printing all pieces, add and pass:

- Hover/grasp/lift/retreat continuation paths.
- ≤3 mm Cartesian error.
- ≥5° joint-limit margin.
- ≤15° maximum per-joint path step.
- No arm/board or tool/neighbor collision.
- Separate checks at empty-board and fully populated initial positions.

### Cross-simulator parity

For every square, compare MuJoCo and Isaac:

- World coordinate.
- Board-top height.
- Piece dimensions and mass.
- Joint order and action units.
- Workspace/wrist camera image size and nominal pose.

Physics trajectories need not be numerically identical; coordinate and observation contracts must be.

## Move acceptance scenarios

Run at minimum:

- `e2e4` ordinary move.
- `e4d5` capture after a legal setup.
- White and black king/queen-side castling.
- En passant.
- Promotion to queen, rook, bishop, and knight through the operator pause.
- Attempted illegal move.
- Dropped piece.
- Piece lands across two squares.
- Board bumped beyond tolerance.
- Camera/fiducial loss.
- Leader packet loss.
- Emergency stop during hover, grasp, lift, and translate.

## Recovery policy

- **Before grasp:** stop and re-observe; no state change.
- **Piece held:** move only to the configured safe hover, then request operator assistance.
- **After release with mismatch:** hold, capture one new observation, and request manual correction.
- **Board moved:** disable autonomous motion until the keyed board pose and empty/reference calibration are restored.
- **Network loss:** consumers hold after 250 ms; they never extrapolate.
- **Promotion:** engine state remains uncommitted until the operator confirms the physical replacement and occupancy passes.
- **Emergency stop:** consider calibration suspect if the arm or tool contacted anything; rerun the relevant preflight.

## Physical reliability gate

The crowded coupon is the bridge from a plausible CAD design to permission to fabricate the full set:

- 30 trials across near, center, and far placements.
- At least 29 successes.
- Zero neighbor contacts.
- Tool mount and TCP repeat within 1 mm.
- No servo overload or progressive loosening.

Record every attempt, including failures. A failed gate changes the extension/tool design—not the acceptance threshold.
