# SO-101 micro-chess implementation

This directory is the executable companion to the [micro-chess system specification](../docs/chess-system/README.md). One JSON contract drives physical dimensions, board coordinates, Blender exports, MuJoCo, Isaac, teleoperation, and validation.

## Current verified state

- 23 mm squares, 184 mm playfield, 204 mm carrier.
- All 64 square centers are 97–270 mm from the pan pivot and pass the model-based vertical-grasp gate: ≤3 mm error, ≥5° joint margin, downward TCP, and no board contact.
- Blender generator produces printable lollipop pieces (14 mm × 8 mm stump + 7 mm mast), leftover fit-check finger-extension STLs, a crowded-clearance coupon, OBJ assets, a `.blend` source, USD, and a preview. Stock jaws, no pads.
- MuJoCo scene loads with the SO-101, tool-clearance model, board, 32 dynamic pieces, capture zones, and two cameras.
- Python Chess orchestration handles moves, captures, castling, en passant, illegal moves, operator-assisted promotion, and commit-after-verification.
- ZMQ leader packets are versioned, ordered, latest-only, and protected by a 250 ms watchdog.
- Runpod scripts pin and isolate the LeIsaac/Isaac stack and install a repository-owned custom task.
- Twenty-three automated tests cover dimensions, all-square vertical IK, generated meshes, legal mechanics, simulator integration, physical-backend safety, and transport watchdog behavior.

Physical clearance and curved hover/transition paths are deliberately not marked complete. Print the five-piece coupon—not all 32 pieces—until the physical test in [fabrication.md](../docs/chess-system/fabrication.md) passes.

## Regenerate and test

From the repository root:

```bash
# Board artwork and dimension report
/Users/kristjangrm/Code/github-com/eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python \
  chess_system/fabrication/generate_board.py

# Printable/visual assets
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python chess_system/assets/blender/generate_assets.py

# MuJoCo model and sizing report
sim/.venv/bin/python -m chess_system.mujoco.generate_scene
sim/.venv/bin/python -m chess_system.mujoco.validate_reach

# Legal-move and contract tests
sim/.venv/bin/python -m unittest discover -s chess_system/tests -v

# Kinematic orchestration smoke test
sim/.venv/bin/python -m chess_system.mujoco.backend --move e2e4
```

The Mac graphics context is required for preview rendering:

```bash
sim/.venv/bin/python -m chess_system.mujoco.render_scene
```

## Key paths

- `config/chess_geometry.json` — authoritative dimensions and tolerances.
- `assets/generated/` — Blender, STL, OBJ, USD, and preview outputs.
- `fabrication/generated/` — print artwork and dimensions.
- `mujoco/` — scene generation, backend, teleoperation, render, and reach report.
- `isaac/` — Runpod bootstrap, USD/PhysX authoring, custom LeIsaac task, teleoperation, and data conversion.
- `controller.py` — full legal-move expansion and verified state commit.
- `vision/occupancy.py` — fiducial registration and occupancy-only checking.
