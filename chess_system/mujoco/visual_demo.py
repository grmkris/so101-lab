"""Native MuJoCo visual demonstration for the engineered chess scene.

This is intentionally kinematic: it visualizes the validated endpoint poses,
piece coordinates, captures, and legal move planning without claiming that a
learned grasp policy or collision-certified carry path already exists.
"""

from __future__ import annotations

import argparse
import csv
import math
import time
from pathlib import Path

import chess
import mujoco
import numpy as np

from chess_system.controller import plan_move
from chess_system.geometry import load_geometry
from chess_system.mujoco.backend import DEFAULT_SCENE, MujocoChessBackend
from chess_system.mujoco.trajectory_executor import PlannedMujocoChessBackend


ROOT = Path(__file__).resolve().parents[2]
REACH_CSV = ROOT / "chess_system" / "mujoco" / "generated" / "square_poses.csv"
ARM_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
DEMO_MOVES = ("e2e4", "d7d5", "e4d5", "g8f6", "g1f3", "f6d5")


def run_planned_demo(args) -> None:
    from chess_system.controller import ChessController

    backend = PlannedMujocoChessBackend(args.scene)
    viewer = None
    if not args.headless:
        from mujoco import viewer as mj_viewer

        viewer = mj_viewer.launch_passive(
            backend.model,
            backend.data,
            show_left_ui=False,
            show_right_ui=True,
        )
        viewer.cam.lookat[:] = (0.17, 0.0, 0.055)
        viewer.cam.distance = 0.52
        viewer.cam.azimuth = 155
        viewer.cam.elevation = -28

        def sync_visible():
            if viewer.is_running():
                viewer.sync()
                time.sleep(1 / 30)

        backend.executor.frame_callback = sync_visible
    try:
        while viewer is None or viewer.is_running():
            backend.executor.reset_ready(settle_seconds=0.2)
            backend._square_piece.clear()
            backend._piece_square.clear()
            backend._captures.clear()
            backend._index_starting_position()
            controller = ChessController(backend)
            if viewer:
                time.sleep(1.2)
            for uci in DEMO_MOVES:
                result = controller.execute_uci(uci)
                if not result.ok:
                    raise RuntimeError(f"planned demo failed at {uci}: {result.message}")
                if viewer:
                    time.sleep(0.35)
            if args.once or viewer is None:
                if viewer:
                    time.sleep(2.0)
                return
            time.sleep(2.0)
    finally:
        if viewer is not None:
            viewer.close()


def load_joint_solutions() -> dict[str, np.ndarray]:
    with REACH_CSV.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return {
            row["square"]: np.asarray([float(row[f"{name}_degrees"]) for name in ARM_JOINTS])
            for row in rows
        }


class Demo:
    def __init__(self, scene: Path, viewer, fps: int = 60):
        self.backend = MujocoChessBackend(scene)
        self.model = self.backend.model
        self.data = self.backend.data
        self.viewer = viewer
        self.fps = fps
        self.geometry = load_geometry()
        self.solutions = load_joint_solutions()
        self.arm_qpos = np.asarray(
            [
                self.model.jnt_qposadr[
                    mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
                ]
                for name in ARM_JOINTS
            ]
        )

    def sync(self, seconds: float = 0.0) -> bool:
        mujoco.mj_forward(self.model, self.data)
        if self.viewer is not None:
            if not self.viewer.is_running():
                return False
            self.viewer.sync()
        if seconds:
            time.sleep(seconds)
        return True

    def interpolate_arm(self, target_degrees: np.ndarray, seconds: float = 0.8) -> bool:
        start = self.data.qpos[self.arm_qpos].copy()
        target = np.radians(target_degrees)
        frames = max(2, round(seconds * self.fps))
        for frame in range(1, frames + 1):
            alpha = 0.5 - 0.5 * math.cos(math.pi * frame / frames)
            self.data.qpos[self.arm_qpos] = start + (target - start) * alpha
            if not self.sync(1 / self.fps):
                return False
        return True

    def set_gripper(self, normalized: float, seconds: float = 0.3) -> bool:
        joint_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "gripper")
        address = int(self.model.jnt_qposadr[joint_id])
        low, high = self.model.jnt_range[joint_id]
        start = float(self.data.qpos[address])
        target = float(low + (high - low) * normalized / 100.0)
        frames = max(2, round(seconds * self.fps))
        for frame in range(1, frames + 1):
            self.data.qpos[address] = start + (target - start) * frame / frames
            if not self.sync(1 / self.fps):
                return False
        return True

    def animate_piece(self, piece: str, start_xyz, end_xyz, seconds: float = 1.1) -> bool:
        frames = max(2, round(seconds * self.fps))
        start = np.asarray(start_xyz, dtype=float)
        end = np.asarray(end_xyz, dtype=float)
        for frame in range(1, frames + 1):
            alpha = frame / frames
            xyz = start + (end - start) * alpha
            xyz[2] += 0.055 * math.sin(math.pi * alpha)
            self.backend._set_piece_xyz(piece, tuple(xyz))
            if not self.sync(1 / self.fps):
                return False
        return True

    def move_piece(self, source: str, target: str) -> bool:
        piece = self.backend._square_piece[source]
        board_z = float(self.geometry.board["nominal_top_z"])
        start = self.geometry.square(source, z=board_z).xyz()
        end = self.geometry.square(target, z=board_z).xyz()
        if not self.interpolate_arm(self.solutions[source]):
            return False
        if not self.set_gripper(20):
            return False
        if not self.animate_piece(piece, start, end):
            return False
        self.backend._square_piece.pop(source)
        self.backend._square_piece[target] = piece
        self.backend._piece_square[piece] = target
        if not self.interpolate_arm(self.solutions[target]):
            return False
        return self.set_gripper(75)

    def capture_piece(self, source: str, color: str) -> bool:
        piece = self.backend._square_piece[source]
        board_z = float(self.geometry.board["nominal_top_z"])
        start = self.geometry.square(source, z=board_z).xyz()
        bin_x, bin_y = self.geometry.capture_bin(color)
        end = (bin_x, bin_y, board_z + 0.006)
        if not self.interpolate_arm(self.solutions[source], 0.65):
            return False
        if not self.animate_piece(piece, start, end, 0.9):
            return False
        self.backend._square_piece.pop(source)
        self.backend._piece_square[piece] = None
        return True

    def execute(self, board: chess.Board, uci: str) -> bool:
        move = chess.Move.from_uci(uci)
        plan = plan_move(board, move)
        for step in plan.steps:
            if step.kind == "capture":
                if not self.capture_piece(step.source or "", step.capture_bin or "black"):
                    return False
            elif step.kind in ("move", "castle_rook"):
                if not self.move_piece(step.source or "", step.target or ""):
                    return False
        board.push(move)
        return self.sync(0.55)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--kinematic",
        action="store_true",
        help="use the legacy endpoint/independent-piece animation",
    )
    args = parser.parse_args()

    if not args.kinematic:
        run_planned_demo(args)
        return

    first = MujocoChessBackend(args.scene)
    viewer = None
    if not args.headless:
        from mujoco import viewer as mj_viewer

        viewer = mj_viewer.launch_passive(first.model, first.data, show_left_ui=False, show_right_ui=True)
        viewer.cam.lookat[:] = (0.17, 0.0, 0.055)
        viewer.cam.distance = 0.52
        viewer.cam.azimuth = 155
        viewer.cam.elevation = -28
    demo = Demo.__new__(Demo)
    # Reuse the exact model/data owned by the visible viewer.
    demo.backend = first
    demo.model = first.model
    demo.data = first.data
    demo.viewer = viewer
    demo.fps = 60
    demo.geometry = load_geometry()
    demo.solutions = load_joint_solutions()
    demo.arm_qpos = np.asarray(
        [demo.model.jnt_qposadr[mujoco.mj_name2id(demo.model, mujoco.mjtObj.mjOBJ_JOINT, name)] for name in ARM_JOINTS]
    )

    try:
        while viewer is None or viewer.is_running():
            mujoco.mj_resetData(demo.model, demo.data)
            demo.backend._square_piece.clear()
            demo.backend._piece_square.clear()
            demo.backend._captures.clear()
            demo.backend._index_starting_position()
            board = chess.Board()
            demo.sync(1.5)
            for uci in DEMO_MOVES:
                if not demo.execute(board, uci):
                    return
            if args.once or viewer is None:
                demo.sync(2.0)
                return
            demo.sync(2.5)
    finally:
        if viewer is not None:
            viewer.close()


if __name__ == "__main__":
    main()
