"""Host-portable device resolution.

These scripts were written against the Mac, where the arm is a
`/dev/tty.usbmodem*` path that changes with the USB topology and cameras are
integer indexes that macOS reshuffles on every replug. The room host `lab-pi`
gives every device a stable udev name instead, so resolve once here and let
every script ask by role.

Order for each device: explicit env override -> udev name if present ->
whatever the old Mac default was.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

FOLLOWER = ["/dev/so101_follower", "/dev/tty.usbmodem5AE60832001"]
LEADER = ["/dev/so101_leader", "/dev/tty.usbmodem5AE60538411"]
CAMERA_NODES = {"workspace": "/dev/cam_context", "wrist": "/dev/cam_wrist"}
CAMERA_ALIASES = {"context": "workspace", "cam_context": "workspace",
                  "cam_wrist": "wrist", "0": "workspace", "1": "wrist"}


def _first_present(candidates, env: str) -> str:
    override = os.environ.get(env)
    if override:
        return override
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[-1]


def follower_port() -> str:
    return _first_present(FOLLOWER, "SO101_FOLLOWER_PORT")


def leader_port() -> str:
    return _first_present(LEADER, "SO101_LEADER_PORT")


def named_cameras() -> bool:
    """True on a host where cameras have stable udev names (i.e. `lab-pi`)."""
    return all(os.path.exists(p) for p in CAMERA_NODES.values())


def camera(name) -> str | int:
    """Resolve a camera role to something `cv2.VideoCapture` accepts.

    Returns the udev path where one exists — that is the whole point of the
    room host. Falls back to the legacy integer index from `calib.json` so the
    Mac workflow keeps working unchanged.
    """
    key = CAMERA_ALIASES.get(str(name), str(name))
    env = os.environ.get(f"DESK_CAM_{key.upper()}")
    if env:
        return int(env) if env.isdigit() else env
    node = CAMERA_NODES.get(key)
    if node and os.path.exists(node):
        return node
    return _legacy_index(key)


def _legacy_index(key: str) -> int:
    default = 0 if key == "workspace" else 1
    calib = HERE / "calib.json"
    if not calib.exists():
        return default
    try:
        c = json.loads(calib.read_text())
    except (json.JSONDecodeError, OSError):
        return default
    if key == "workspace":
        return int(c.get("camera_index", default))
    return int(c.get("wrist", {}).get("camera_index", default))


def describe() -> dict:
    return {
        "follower": follower_port(),
        "leader": leader_port(),
        "cameras": {k: camera(k) for k in CAMERA_NODES},
        "named_cameras": named_cameras(),
    }


if __name__ == "__main__":
    print(json.dumps(describe(), indent=2))
