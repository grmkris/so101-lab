"""Record the simulated arm playing chess to an MP4.

Frames are rendered offscreen from the executor's own ``frame_callback``, so
the video shows the same physics-stepped trajectories the acceptance gates run
— not a separate animation. Raw RGB is piped straight into ffmpeg; the
simulation venv deliberately carries no image or video libraries.

    sim/.venv/bin/python -m chess_system.mujoco.record_game --plies 8

Use ``--camera`` to pick a scene camera (``overhead``, ``wrist``) or omit it for
a free perspective view of the whole rig.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import mujoco
import numpy as np

from chess_system.mujoco.backend import DEFAULT_SCENE
from chess_system.mujoco.play_game import play_game
from chess_system.mujoco.trajectory_executor import (
    DEFAULT_LIBRARY,
    PlannedMujocoChessBackend,
)


ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "chess_system" / "mujoco" / "generated"
DEFAULT_OUTPUT = GENERATED / "game_recording.mp4"


class FrameRecorder:
    """Offscreen renderer that samples frames at a fixed video rate."""

    def __init__(
        self,
        model,
        data,
        *,
        width: int,
        height: int,
        fps: int,
        camera: str | None,
        output: Path,
    ):
        self.model = model
        self.data = data
        self.fps = fps
        self.interval = 1.0 / fps
        self.renderer = mujoco.Renderer(model, height=height, width=width)
        self.camera = camera
        self.frames = 0
        self._next_sample = 0.0

        if camera is None:
            # Free look at the board from the operator's side of the rig.
            self.view = mujoco.MjvCamera()
            mujoco.mjv_defaultCamera(self.view)
            self.view.lookat[:] = (0.15, 0.0, 0.06)
            self.view.distance = 0.80
            self.view.azimuth = 135.0
            self.view.elevation = -24.0
        else:
            self.view = camera

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required to record; brew install ffmpeg")
        output.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{width}x{height}", "-r", str(fps),
                "-i", "-",
                "-an", "-vcodec", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "20", str(output),
            ],
            stdin=subprocess.PIPE,
        )

    def capture(self) -> None:
        """Sample a frame if enough simulated time has passed since the last one."""

        now = float(self.data.time)
        if now < self._next_sample:
            return
        self._next_sample = now + self.interval
        self.renderer.update_scene(self.data, camera=self.view)
        pixels = self.renderer.render()
        self.process.stdin.write(np.ascontiguousarray(pixels, dtype=np.uint8).tobytes())
        self.frames += 1

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait()
        self.renderer.close()


def record(
    *,
    plies: int,
    output: Path,
    width: int,
    height: int,
    fps: int,
    camera: str | None,
    depth: int,
    scene: str | Path,
    library: str | Path,
    cache_path: str | Path | None,
) -> dict:
    backend = PlannedMujocoChessBackend(scene, library, cache_path=cache_path)
    recorder = FrameRecorder(
        backend.model,
        backend.data,
        width=width,
        height=height,
        fps=fps,
        camera=camera,
        output=output,
    )
    backend.executor.frame_callback = recorder.capture

    started = time.time()
    try:
        report = play_game(max_moves=plies, depth=depth, backend=backend)
    finally:
        recorder.close()

    payload = report.to_dict()
    payload["recording"] = {
        "path": str(output),
        "frames": recorder.frames,
        "fps": fps,
        "seconds": round(recorder.frames / fps, 2),
        "camera": camera or "free",
        "wall_clock_seconds": round(time.time() - started, 1),
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plies", type=int, default=8)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--camera",
        default=None,
        help="scene camera name (overhead, wrist); omit for a free view",
    )
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--scene", default=str(DEFAULT_SCENE))
    parser.add_argument("--library", default=str(DEFAULT_LIBRARY))
    parser.add_argument(
        "--cache",
        default=None,
        help="runtime planner cache path; use a scratch file to avoid "
        "racing another running game",
    )
    args = parser.parse_args()

    output = Path(args.output)
    payload = record(
        plies=args.plies,
        output=output,
        width=args.width,
        height=args.height,
        fps=args.fps,
        camera=args.camera,
        depth=args.depth,
        scene=args.scene,
        library=args.library,
        cache_path=args.cache,
    )
    report_path = output.with_suffix(".json")
    report_path.write_text(json.dumps(payload, indent=2))
    info = payload["recording"]
    print(
        f"{payload['plies']} plies -> {info['frames']} frames "
        f"({info['seconds']}s at {info['fps']} fps) in "
        f"{info['wall_clock_seconds']}s wall clock"
    )
    print(f"video:  {output}")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
