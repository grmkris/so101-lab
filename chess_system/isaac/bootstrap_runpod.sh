#!/usr/bin/env bash
# Reproducible LeIsaac appliance for the persistent /workspace Runpod volume.
# LeRobot is deliberately excluded: Isaac/LeIsaac requires NumPy 1.26 while the
# production 0.6.0 stack requires NumPy 2.x.
set -euo pipefail

SIM_ROOT="${SIM_ROOT:-/workspace/so101-sim}"
REPO_URL="${SO101_REPO_URL:-https://github.com/grmkris/so101-lab.git}"
LEISAAC_TAG="${LEISAAC_TAG:-v0.4.0}"

mkdir -p "$SIM_ROOT"
cd "$SIM_ROOT"

if [[ ! -d so101-lab/.git ]]; then
  git clone "$REPO_URL" so101-lab
else
  git -C so101-lab pull --ff-only
fi

if [[ ! -d leisaac/.git ]]; then
  git clone --branch "$LEISAAC_TAG" --recurse-submodules https://github.com/LightwheelAI/leisaac.git
else
  git -C leisaac fetch --tags
  git -C leisaac checkout "$LEISAAC_TAG"
  git -C leisaac submodule update --init --recursive
fi

if command -v conda >/dev/null 2>&1; then
  if ! conda env list | awk '{print $1}' | grep -qx leisaac; then
    conda create -y -n leisaac python=3.11
  fi
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate leisaac
else
  echo "ERROR: the Runpod template must provide conda/mamba" >&2
  exit 2
fi

conda install -y -c "nvidia/label/cuda-12.8.1" cuda-toolkit
python -m pip install --upgrade pip
python -m pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
python -m pip install -e "$SIM_ROOT/leisaac/source/leisaac[isaaclab,remote]" --extra-index-url https://pypi.nvidia.com
python -m pip install numpy==1.26.0 pyzmq

python "$SIM_ROOT/so101-lab/chess_system/isaac/author_stage.py" \
  --output "$SIM_ROOT/generated/micro_chess_physics.usda"
bash "$SIM_ROOT/so101-lab/chess_system/isaac/install_leisaac_task.sh" \
  "$SIM_ROOT/leisaac" "$SIM_ROOT/generated/micro_chess_physics.usda"

cat <<EOF
LeIsaac appliance ready.
  environment: conda activate leisaac
  repository:  $SIM_ROOT/so101-lab
  stage:       $SIM_ROOT/generated/micro_chess_physics.usda
  task:        LeIsaac-SO101-MicroChess-v0
  next:        chess_system/isaac/run_remote_teleop.sh
EOF
