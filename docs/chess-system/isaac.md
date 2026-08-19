# Isaac Sim and Runpod runbook

Isaac provides RTX cameras, PhysX contacts, LeIsaac remote teleoperation, domain randomization, and scalable recording. It remains isolated from the real-arm LeRobot 0.6.0 environments.

## Version matrix

| Component | Pin |
|---|---:|
| LeIsaac | `v0.4.0` |
| Isaac Sim | `5.1.0` |
| Isaac Lab | LeIsaac’s compatible `2.3` submodule |
| Python | `3.11` |
| PyTorch / torchvision | `2.7.0` / `0.22.0`, CUDA 12.8 |
| NumPy | `1.26.0` |

Do not install current LeRobot into this environment. Current LeRobot requires NumPy 2.x, while Isaac/LeIsaac pins NumPy 1.26. Native HDF5 is the boundary.

References: [LeIsaac installation](https://lightwheelai.github.io/leisaac/docs/getting_started/installation/), [custom task tutorial](https://lightwheelai.github.io/leisaac/docs/tutorials/custom_task/), and [remote teleoperation](https://lightwheelai.github.io/leisaac/docs/getting_started/teleoperation/).

## Persistent Runpod layout

```text
/workspace/so101-sim/
  so101-lab/                 repository checkout
  leisaac/                   v0.4.0 source checkout
  generated/                 self-contained PhysX stage + visuals/
  datasets/micro_chess/      native HDF5 recordings
  converter-v042/            disposable Dataset v3 converter
```

The network volume is persistent; GPU pods are disposable.

## Bootstrap

On a compatible Runpod image with Conda and NVIDIA drivers:

```bash
git clone https://github.com/grmkris/so101-lab.git /workspace/so101-lab-bootstrap
bash /workspace/so101-lab-bootstrap/chess_system/isaac/bootstrap_runpod.sh
```

The script:

1. Creates `/workspace/so101-sim`.
2. Clones/updates this repository and LeIsaac `v0.4.0`.
3. Creates the Python 3.11 `leisaac` Conda environment.
4. Installs PyTorch, Isaac Sim, LeIsaac remote support, and NumPy 1.26.
5. Authors a portable `micro_chess_physics.usda` plus sibling `visuals/` from the shared geometry contract.
6. Installs `LeIsaac-SO101-MicroChess-v0` into the source checkout.

The authoring script creates a USD stage with the 204 mm carrier, 23 mm squares, compound rigid-piece colliders, masses, colors, and chess metadata. Blender’s detailed USD is the visual source; PhysX primitives remain the stable collision source.

## Validate the installation

```bash
conda activate leisaac
cd /workspace/so101-sim/leisaac

python scripts/environments/list_envs.py | grep MicroChess

# Stock installation gate
python scripts/environments/teleoperation/teleop_se3_agent.py \
  --task=LeIsaac-SO101-LiftCube-v0 \
  --teleop_device=keyboard --num_envs=1 --device=cuda --enable_cameras

# Custom scene gate
python scripts/environments/teleoperation/teleop_se3_agent.py \
  --task=LeIsaac-SO101-MicroChess-v0 \
  --teleop_device=keyboard --num_envs=1 --device=cuda --enable_cameras
```

Do not troubleshoot the custom task until LiftCube works.

## Remote teleoperation and recording

Join the pod and Mac to the same tailnet. Start the official or repository publisher on the Mac. On Runpod:

```bash
export REMOTE_ENDPOINT=tcp://<mac-tailnet-ip>:5556
bash /workspace/so101-sim/so101-lab/chess_system/isaac/run_remote_teleop.sh
```

In the Isaac window:

- `b`: begin teleoperation.
- `r`: reset and mark attempt failed.
- `n`: reset and mark attempt successful.

Dataset output defaults to `/workspace/so101-sim/datasets/micro_chess/dataset.hdf5`.

Replay before conversion:

```bash
python scripts/environments/teleoperation/replay.py \
  --task=LeIsaac-SO101-MicroChess-v0 \
  --num_envs=1 --device=cuda --enable_cameras \
  --replay_mode=action \
  --dataset_file=/workspace/so101-sim/datasets/micro_chess/dataset.hdf5
```

## Convert to LeRobot Dataset v3

```bash
export REPO_ID=kris0/so101_micro_chess_sim_v1
bash /workspace/so101-sim/so101-lab/chess_system/isaac/convert_dataset_v3.sh
```

The converter creates an isolated LeRobot 0.4.2 environment because that is the version documented for LeIsaac’s Dataset v3 converter. After conversion, load and visualize the result using the production LeRobot 0.6.0 environment. Do not train until joint order, units, FPS, timestamps, task text, and both image keys match the real-arm convention.

## Isaac acceptance gate

- Stock LiftCube launches and resets.
- Custom task appears in the environment list.
- Board dimensions match the generated report within 0.1 mm.
- All pieces are separate rigid bodies with stable compound colliders.
- Leader stream stays active at 30–50 Hz and enters hold on disconnect.
- One episode records, replays, converts, and loads in LeRobot 0.6.0.
- Scripted move coordinates match MuJoCo’s square CSV.
