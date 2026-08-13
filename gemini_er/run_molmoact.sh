#!/bin/bash
# Bounded MolmoAct2 rollout against the remote policy server.
# Usage: SERVER=100.x.y.z:8081 TASK="grasp the white cube and lift it off the table" \
#        DURATION=90 CAM0_IDX=0 CAM1_IDX=1 ./run_molmoact.sh
# SCENE_ONLY=1 duplicates the scene cam into both image keys (wrist-OOD fallback).
set -u
SERVER="${SERVER:?SERVER=host:port required}"
TASK="${TASK:-grasp the white cube and lift it off the table}"
DURATION="${DURATION:-90}"
CAM0_IDX="${CAM0_IDX:-0}"   # workspace C922
CAM1_IDX="${CAM1_IDX:-1}"   # wrist Innomaker
FPS="${FPS:-15}"            # 30 starves the queue: chunks (30 acts, ~1s latency) go stale
PY=~/.local/share/uv/tools/lelab/bin/python
DRIVER_PY=/Users/kristjangrm/Code/github-com/eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python

if [ "${SCENE_ONLY:-0}" = "1" ]; then
  CAM1_IDX="$CAM0_IDX"
fi

# park in the checkpoint's ready pose (center of its state-normalization band):
# parked home is quantile-clamped as out-of-band -> "stay" freeze
if [ "${PRE_POSE:-1}" = "1" ]; then
  for i in 1 2 3; do
    if $DRIVER_PY -c "
import numpy as np
import arm
r = arm.connect()
try:
    arm.move_joints(r, np.array([3.3, -34.3, 31.4, 56.0, -11.5, 0.0]), 3.0, gripper=50)
finally:
    r.disconnect()
print('pre-pose set')"; then
      break
    fi
    echo "pre-pose attempt $i failed, retrying in 3s"
    sleep 3
  done
fi

# 320x240: the client ships RAW frames in a blocking call; server resizes to 224x224 anyway
$PY -m lerobot.async_inference.robot_client \
  --server_address="$SERVER" \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5AE60832001 \
  --robot.id=arm \
  --robot.max_relative_target=15 \
  --robot.cameras="{ cam0: {type: opencv, index_or_path: $CAM0_IDX, width: 320, height: 240, fps: 30, warmup_s: 4}, cam1: {type: opencv, index_or_path: $CAM1_IDX, width: 320, height: 240, fps: 30, warmup_s: 6}}" \
  --task="$TASK" \
  --policy_type=molmoact2 \
  --pretrained_name_or_path=/content/molmoact2_so101 \
  --policy_device=cuda \
  --client_device=cpu \
  --actions_per_chunk=30 \
  --chunk_size_threshold=0.6 \
  --aggregate_fn_name=latest_only \
  --fps="$FPS" \
  --debug_visualize_queue_size=False &
PID=$!
( sleep "$DURATION" && kill -INT "$PID" 2>/dev/null && sleep 10 && kill -9 "$PID" 2>/dev/null ) &
WATCHER=$!
wait "$PID"
pkill -P "$WATCHER" 2>/dev/null; kill "$WATCHER" 2>/dev/null
echo "rollout ended (max ${DURATION}s)"
