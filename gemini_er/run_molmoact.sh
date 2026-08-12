#!/bin/bash
# Bounded MolmoAct2 rollout against the remote policy server.
# Usage: SERVER=100.x.y.z:8080 TASK="pick up the white block" DURATION=60 \
#        CAM0_IDX=0 CAM1_IDX=2 ./run_molmoact.sh
set -u
SERVER="${SERVER:?SERVER=host:port required}"
TASK="${TASK:-pick up the white block}"
DURATION="${DURATION:-60}"
CAM0_IDX="${CAM0_IDX:-0}"   # workspace C922
CAM1_IDX="${CAM1_IDX:-2}"   # wrist Innomaker
PY=~/.local/share/uv/tools/lelab/bin/python

$PY -m lerobot.async_inference.robot_client \
  --server_address="$SERVER" \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5AE60832001 \
  --robot.id=arm \
  --robot.max_relative_target=15 \
  --robot.cameras="{ cam0: {type: opencv, index_or_path: $CAM0_IDX, width: 640, height: 480, fps: 30}, cam1: {type: opencv, index_or_path: $CAM1_IDX, width: 640, height: 480, fps: 30}}" \
  --task="$TASK" \
  --policy_type=molmoact2 \
  --pretrained_name_or_path=/content/molmoact2_so101 \
  --policy_device=cuda \
  --client_device=cpu \
  --actions_per_chunk=30 \
  --chunk_size_threshold=0.6 \
  --fps=30 \
  --debug_visualize_queue_size=False &
PID=$!
( sleep "$DURATION" && kill -INT "$PID" 2>/dev/null ) &
WATCHER=$!
wait "$PID"
kill "$WATCHER" 2>/dev/null
echo "rollout ended (max ${DURATION}s)"
