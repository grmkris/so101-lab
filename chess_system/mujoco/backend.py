"""Kinematic MuJoCo backend for chess orchestration and scene validation.

The backend intentionally moves free-joint pieces kinematically. Robot grasp
dynamics and learned-policy execution are separate validation layers; this
backend proves coordinates, game mechanics, rendering and occupancy handling.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from chess_system.geometry import FILES, RANKS, SquarePose, load_geometry
from chess_system.model import ManipulationResult, MovePlan, ResultStatus
from chess_system.verification import ALL_SQUARES

try:
    import mujoco
except ImportError:  # pragma: no cover
    mujoco = None


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENE = ROOT / "sim" / "model" / "chess_scene.xml"


class MujocoChessBackend:
    name = "mujoco"

    def __init__(self, scene: str | Path = DEFAULT_SCENE):
        if mujoco is None:
            raise RuntimeError("MuJoCo is required; use sim/.venv/bin/python")
        self.geometry = load_geometry()
        self.model = mujoco.MjModel.from_xml_path(str(Path(scene).resolve()))
        self.data = mujoco.MjData(self.model)
        self._square_piece: dict[str, str] = {}
        self._piece_square: dict[str, str | None] = {}
        self._captures = defaultdict(int)
        self._stopped = False
        self._index_starting_position()
        mujoco.mj_forward(self.model, self.data)

    def _index_starting_position(self) -> None:
        back = ("rook", "knight", "bishop", "queen", "king", "bishop", "knight", "rook")
        for color, pawn_rank, home_rank in (("white", "2", "1"), ("black", "7", "8")):
            for file_name in FILES:
                self._register(f"piece_{color}_pawn_{file_name}", f"{file_name}{pawn_rank}")
            for file_name, piece_type in zip(FILES, back, strict=True):
                self._register(f"piece_{color}_{piece_type}_{file_name}", f"{file_name}{home_rank}")

    def _register(self, piece: str, square: str) -> None:
        if mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, piece) < 0:
            raise RuntimeError(f"piece body missing from scene: {piece}")
        self._square_piece[square] = piece
        self._piece_square[piece] = square

    def _qpos_address(self, piece: str) -> int:
        body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, piece)
        joint_id = int(self.model.body_jntadr[body_id])
        if joint_id < 0 or int(self.model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
            raise RuntimeError(f"piece {piece} does not have a free joint")
        return int(self.model.jnt_qposadr[joint_id])

    def _set_piece_xyz(self, piece: str, xyz: tuple[float, float, float]) -> None:
        address = self._qpos_address(piece)
        self.data.qpos[address : address + 3] = xyz
        self.data.qpos[address + 3 : address + 7] = (1, 0, 0, 0)
        self.data.qvel[int(self.model.jnt_dofadr[int(self.model.body_jntadr[mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, piece)])]) :][:6] = 0
        mujoco.mj_forward(self.model, self.data)

    def _move_square(self, source: str, target: str) -> None:
        if source not in self._square_piece:
            raise RuntimeError(f"source square is empty: {source}")
        if target in self._square_piece:
            raise RuntimeError(f"target square is occupied: {target}")
        piece = self._square_piece.pop(source)
        board_z = float(self.geometry.board["nominal_top_z"])
        pose = self.geometry.square(target, z=board_z)
        self._set_piece_xyz(piece, pose.xyz())
        self._square_piece[target] = piece
        self._piece_square[piece] = target

    def _capture(self, source: str, bin_color: str) -> None:
        if source not in self._square_piece:
            raise RuntimeError(f"capture square is empty: {source}")
        piece = self._square_piece.pop(source)
        self._piece_square[piece] = None
        x, y = self.geometry.capture_bin(bin_color)
        index = self._captures[bin_color]
        # Spread captures in a deterministic 3xN grid within the cup.
        x += ((index % 3) - 1) * 0.010
        y += ((index // 3) % 3 - 1) * 0.010
        z = float(self.geometry.board["nominal_top_z"]) + 0.006 + (index // 9) * 0.044
        self._captures[bin_color] += 1
        self._set_piece_xyz(piece, (x, y, z))

    def square_pose(self, square: str, phase: str) -> SquarePose:
        board_z = float(self.geometry.board["nominal_top_z"])
        mast = self.geometry.piece
        grasp_z = board_z + float(mast["grasp_mast_bottom_z"]) + float(mast["grasp_mast_height"]) / 2
        offsets = {
            "hover": 0.080,
            "grasp": grasp_z - board_z,
            "lift": 0.080,
            "place": grasp_z - board_z,
            "retreat": 0.080,
        }
        if phase not in offsets:
            raise ValueError(f"unknown motion phase: {phase}")
        return self.geometry.square(square, z=board_z + offsets[phase])

    def execute_plan(self, plan: MovePlan) -> ManipulationResult:
        if self._stopped:
            return ManipulationResult(ResultStatus.STOPPED, plan.move_id, message="backend is stopped")
        completed = 0
        try:
            for step in plan.steps:
                if step.kind == "capture":
                    self._capture(step.source or "", step.capture_bin or "black")
                elif step.kind in ("move", "castle_rook"):
                    self._move_square(step.source or "", step.target or "")
                elif step.kind == "promotion_pause":
                    # The controller owns the operator interaction.
                    pass
                completed += 1
        except Exception as exc:
            return ManipulationResult(
                ResultStatus.FAILED,
                plan.move_id,
                completed_steps=completed,
                message=str(exc),
            )
        return ManipulationResult(
            ResultStatus.VERIFIED,
            plan.move_id,
            completed_steps=completed,
            message="kinematic MuJoCo plan complete",
        )

    def observe_occupancy(self) -> dict[str, bool]:
        return {square: square in self._square_piece for square in ALL_SQUARES}

    def board_pose_error(self) -> tuple[float, float]:
        return 0.0, 0.0

    def home(self) -> None:
        self._stopped = False

    def hold(self) -> None:
        # Kinematic backend has no active targets; the state is already held.
        return None

    def emergency_stop(self) -> None:
        self._stopped = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", default=str(DEFAULT_SCENE))
    parser.add_argument("--move", default="e2e4")
    args = parser.parse_args()
    from chess_system.controller import ChessController

    backend = MujocoChessBackend(args.scene)
    controller = ChessController(backend)
    result = controller.execute_uci(args.move)
    print(result)


if __name__ == "__main__":
    main()
