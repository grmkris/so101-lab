"""Render the generated MuJoCo chess scene without image-library dependencies."""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

import mujoco

from chess_system.mujoco.backend import DEFAULT_SCENE


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "chess_system" / "mujoco" / "generated" / "workspace_preview.png"


def write_png(path: Path, rgb) -> None:
    height, width, channels = rgb.shape
    if channels != 3 or rgb.dtype.name != "uint8":
        raise ValueError("expected uint8 RGB image")

    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    scanlines = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(scanlines, 9))
    payload += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--camera", default="workspace_cam")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()
    model = mujoco.MjModel.from_xml_path(str(args.scene.resolve()))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    with mujoco.Renderer(model, height=args.height, width=args.width) as renderer:
        renderer.update_scene(data, camera=args.camera)
        write_png(args.output, renderer.render())
    print(f"rendered {args.output}")


if __name__ == "__main__":
    main()
