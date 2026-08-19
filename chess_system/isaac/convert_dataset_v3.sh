#!/usr/bin/env bash
# Convert native LeIsaac HDF5 in an isolated legacy converter environment.
set -euo pipefail

SIM_ROOT="${SIM_ROOT:-/workspace/so101-sim}"
HDF5_ROOT="${HDF5_ROOT:-$SIM_ROOT/datasets/micro_chess}"
REPO_ID="${REPO_ID:?set REPO_ID=user/dataset_name}"
ENV_DIR="$SIM_ROOT/converter-v042"

python3.11 -m venv "$ENV_DIR"
"$ENV_DIR/bin/pip" install --upgrade pip
"$ENV_DIR/bin/pip" install "lerobot==0.4.2" "numpy==1.26.0"

cd "$SIM_ROOT/leisaac"
"$ENV_DIR/bin/python" scripts/convert/isaaclab2lerobotv3.py \
  --task_name=SO101MicroChess \
  --repo_id="$REPO_ID" \
  --hdf5_root="$HDF5_ROOT" \
  --hdf5_files=dataset.hdf5 \
  --fps=30 \
  --task_description="Move the chess piece from its source square to its legal destination"

echo "Conversion complete. Validate this Dataset v3 with the production LeRobot 0.6.0 environment before training."
