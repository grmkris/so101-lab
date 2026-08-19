#!/usr/bin/env bash
# Install the repository-owned task extension into a LeIsaac source checkout.
set -euo pipefail

LEISAAC_ROOT="${1:?usage: install_leisaac_task.sh LEISAAC_ROOT SCENE_USD}"
SCENE_USD="${2:?usage: install_leisaac_task.sh LEISAAC_ROOT SCENE_USD}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGE_ROOT="$LEISAAC_ROOT/source/leisaac/leisaac"

mkdir -p "$PACKAGE_ROOT/assets/scenes/micro_chess"
mkdir -p "$PACKAGE_ROOT/tasks/micro_chess"
cp "$SCENE_USD" "$PACKAGE_ROOT/assets/scenes/micro_chess/scene.usda"
rm -rf "$PACKAGE_ROOT/assets/scenes/micro_chess/visuals"
cp -R "$(dirname "$SCENE_USD")/visuals" "$PACKAGE_ROOT/assets/scenes/micro_chess/visuals"
cp "$SCRIPT_DIR/leisaac_extension/micro_chess_scene.py" "$PACKAGE_ROOT/assets/scenes/micro_chess.py"
cp "$SCRIPT_DIR/leisaac_extension/micro_chess_env_cfg.py" "$PACKAGE_ROOT/tasks/micro_chess/micro_chess_env_cfg.py"
cp "$SCRIPT_DIR/leisaac_extension/__init__.py" "$PACKAGE_ROOT/tasks/micro_chess/__init__.py"

echo "installed LeIsaac-SO101-MicroChess-v0 into $LEISAAC_ROOT"
