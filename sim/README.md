# sim/ — MuJoCo learning track for the SO-101

**Purpose: learning + prototyping (RL mechanics, IK, reward design). NOT a sim2real path** —
ggando's pixel-RL agent hit 100% in sim and completely failed on the real arm
(see journal.md 2026-07-24). Real-world reliability work stays on the IL track.

## Setup (done)
```bash
uv venv --python 3.12 sim/.venv
uv pip install --python sim/.venv/bin/python mujoco so101-nexus
```
Model: `model/scene.xml` + `model/so101_new_calib.xml` from TheRobotStudio/SO-ARM100
`Simulation/SO101`; `model/assets/` (13 STLs, gitignored) copied from `phone_teleop/SO101/assets/`.

## Run
```bash
cd sim
.venv/bin/python -m mujoco.viewer --mjcf=model/scene.xml   # interactive viewer, sliders = radians
.venv/bin/python run_sim.py                                 # ECE4560 lab-4 motion (viewer)
.venv/bin/python run_sim.py --headless                      # smoke test, no window
```
`so101_mujoco_utils.py` gives the hardware-style interface (degrees dict, gripper 0-100).

## so101-nexus (installed, envs verified headless)
5 gym tasks (register on `import so101_nexus.mujoco`): `MuJoCoPickLift-v1`,
`MuJoCoPickAndPlace-v1`, `MuJoCoTouch-v1`, `MuJoCoLookAt-v1`, `MuJoCoMove-v1`.
Default obs is 24-dim **state** (not pixels); action = 6 joint targets (radians).

**Leader-teleop-into-sim** (UNTESTED — arms were disconnected on setup day):
```bash
.venv/bin/so101-nexus teleop --leader-port /dev/tty.usbmodem5AE60538411 --leader-id arm
```
Uses the existing lerobot calibration for id `arm`. Docs: so101-nexus.com/docs.
`[warp]` extra skipped (CUDA-only; Mac). RL training later goes to Colab.

## Curriculum (follow-on)
1. ECE 4560 labs (maegantucker.com/ECE4560): joint space ✅ → IK → trajectories.
2. Crib from ggand0/pick-101: damped-least-squares IK, 4-step pick sequence,
   fingertip box-collision-pad fix (mesh-mesh contacts are unstable for grasping).
3. Camera rendering verified working (`mujoco.Renderer`, offscreen 640×480 OK on Mac) —
   the door to vision policies in sim when we get there.
