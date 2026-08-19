# Fabrication runbook

## Do not print the full set first

The safe sequence is:

1. Print the two finger-extension prototypes.
2. Print the 3×3 crowded-clearance coupon.
3. Print five pawns and add their base weights.
4. Fit, calibrate, and run the 30-trial gate.
5. Revise only the keyed extension roots if necessary.
6. Print the remaining 27 pieces only after the gate passes.

## Generated files

Regenerate with:

```bash
/Users/kristjangrm/Code/github-com/eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python \
  chess_system/fabrication/generate_board.py

/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python chess_system/assets/blender/generate_assets.py
```

Outputs:

- `fabrication/generated/micro_chess_board.svg`
- `fabrication/generated/DIMENSIONS.md`
- `assets/generated/stl/{pawn,rook,knight,bishop,queen,king}.stl`
- `assets/generated/stl/{fixed,moving}_finger_extension.stl`
- `assets/generated/stl/crowded_clearance_coupon.stl`
- `assets/generated/stl/pivot_to_board_gauge.stl`
- `assets/generated/micro_chess.blend`

## Board

1. Print the SVG at exactly 100%; disable “fit to page”.
2. Measure the 100 mm scale bar. Reject the print if error exceeds 0.5 mm.
3. Bond the 204 mm carrier artwork to flat 3–4 mm card, foam board, acrylic, or MDF.
4. Keep total bow below 1 mm corner-to-corner.
5. Cut the four fiducial tabs separately and mount them rigidly:
   - ID 0: near-left, `(75,+119) mm` from pivot.
   - ID 1: far-left, `(279,+119) mm`.
   - ID 2: far-right, `(279,-119) mm`.
   - ID 3: near-right, `(75,-119) mm`.
6. Center the carrier on the arm and place its near edge 75 mm from the pan pivot.
7. Add rigid stops or corner brackets so removal/reinstallation repeats within 1 mm.

## Pieces

Recommended first print:

- PLA is acceptable for fit checks.
- PETG is preferred for the final pieces and extensions.
- 0.2 mm layers, at least three walls.
- Pieces: 20–30% infill; pause near the base to insert an appropriately sized steel washer.
- Extensions: 100% infill, print orientation chosen so layer lines do not split across the long axis.
- Deburr the 7 mm grasp mast; its diameter must be consistent across every piece.
- Target total mass: 9–16 g, clustered within ±1.5 g across the set.
- Add a thin high-friction/felt underside without increasing the 14 mm base envelope.

The body silhouettes intentionally differ while every grasp mast and total height remain common. White and black use separate filament colors. Add a top glyph or paint mark only if it does not exceed the 10 mm upper-body envelope.

## Finger extensions

The generated root dimensions are prototypes, not certified final mounts.

1. With power disconnected, measure both jaw-tip interfaces using calipers.
2. Compare the measurements with the generated Blender root blocks.
3. Change only root channel/fastener geometry in the Blender generator.
4. Preserve:
   - 20 mm nominal reach.
   - 2.5 × 4 mm tips.
   - ≤14 mm closed envelope around the 7 mm mast.
   - ≤19 mm maximum-open envelope.
5. Use keyed geometry and an M3 fastener. Do not rely on a friction snap alone.
6. Add replaceable 0.5–0.8 mm TPU/rubber pads.
7. Confirm combined tool mass stays below 20 g.
8. Mark the left and right parts so they cannot be swapped.

## Crowded-clearance gate

Place a target piece in the coupon center and four neighbors at north, south, east, and west positions. Run:

- 10 transfers at a near-center board location.
- 10 at the board center.
- 10 at a far corner.

Pass criteria:

- At least 29/30 successful pick-and-replace cycles.
- Zero tool or wrist contact with a neighbor.
- No root movement or screw loosening.
- Reinstalled TCP repeatability within 1 mm.
- No visible servo oscillation, overload, or persistent sag.

If it fails, revise the extension root, tip taper, pads, or mast tolerance. Do not enlarge the board: larger pitch would move the far squares outside the reliable envelope.

## Capture chute and discard tray

Required parts, not optional. Without the chute, a released piece stays at the
mouth and the next capture into the same colour lands on top of it — the
failure that retired the original capture cups.

Per colour:

- **Chute mouth** — 40 × 40 mm opening centred at `(150, ±128) mm` from the pan
  pivot, top edge flush with the board surface. These coordinates are load
  bearing: the validated `capture_bin:<colour>` routes target them, so moving
  the mouth invalidates the route library.
- **Funnel** — passive slope from the mouth outward in ±Y to the tray. Steep
  enough that a 24 mm piece released at the mouth clears it under gravity
  without help; verify by hand before trusting a game.
- **Discard tray** — centred at `(90, ±360) mm`, 4 × 4 slots at 18 mm pitch,
  10 mm walls. Holds 16; a game produces at most 15 per colour.

The tray must stay **outside the arm's reach** (its nearest slot is 339 mm
against roughly 306 mm of arm). That margin is what lets the planner ignore
captured pieces entirely. If you relocate the tray closer for convenience, the
planner becomes wrong rather than merely inconvenient.
