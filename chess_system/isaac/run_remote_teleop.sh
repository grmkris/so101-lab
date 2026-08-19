#!/usr/bin/env bash
# Run on the Runpod instance after bootstrap_runpod.sh.
set -euo pipefail

SIM_ROOT="${SIM_ROOT:-/workspace/so101-sim}"
REMOTE_ENDPOINT="${REMOTE_ENDPOINT:?set REMOTE_ENDPOINT=tcp://<leader-tailnet-ip>:5556}"
TASK="${LEISAAC_TASK:-LeIsaac-SO101-MicroChess-v0}"
DATASET_DIR="${DATASET_DIR:-$SIM_ROOT/datasets/micro_chess}"

cd "$SIM_ROOT/leisaac"
python scripts/environments/teleoperation/teleop_se3_agent.py \
  --task="$TASK" \
  --teleop_device=so101leader \
  --remote_endpoint="$REMOTE_ENDPOINT" \
  --num_envs=1 \
  --device=cuda \
  --enable_cameras \
  --record \
  --dataset_file="$DATASET_DIR/dataset.hdf5"
