"""Shared board, piece and tool geometry.

All consumers load ``config/chess_geometry.json`` rather than duplicating
dimensions. The file is deliberately JSON so Blender, Python, shell tooling and
future TypeScript code can consume it without an additional parser dependency.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


FILES = "abcdefgh"
RANKS = "12345678"
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "chess_geometry.json"


@dataclass(frozen=True)
class SquarePose:
    square: str
    x: float
    y: float
    z: float = 0.0

    @property
    def radius(self) -> float:
        return math.hypot(self.x, self.y)

    def xyz(self, z: float | None = None) -> tuple[float, float, float]:
        return self.x, self.y, self.z if z is None else z


class ChessGeometry:
    """Validated view over the machine-readable geometry contract."""

    def __init__(self, raw: dict[str, Any], source: Path = DEFAULT_CONFIG):
        self.raw = raw
        self.source = source
        self._validate()

    @property
    def board(self) -> dict[str, Any]:
        return self.raw["board"]

    @property
    def piece(self) -> dict[str, Any]:
        return self.raw["piece"]

    @property
    def tool(self) -> dict[str, Any]:
        return self.raw["tool"]

    @property
    def robot(self) -> dict[str, Any]:
        return self.raw["robot"]

    @property
    def teleoperation(self) -> dict[str, Any]:
        return self.raw["teleoperation"]

    @property
    def motion_planning(self) -> dict[str, Any]:
        return self.raw["motion_planning"]

    @property
    def square_size(self) -> float:
        return float(self.board["square_size"])

    @property
    def playfield_size(self) -> float:
        return self.square_size * int(self.board["files"])

    def square(self, name: str, z: float = 0.0) -> SquarePose:
        normalized = name.lower()
        if len(normalized) != 2 or normalized[0] not in FILES or normalized[1] not in RANKS:
            raise ValueError(f"invalid chess square: {name!r}")
        file_index = FILES.index(normalized[0])
        rank = int(normalized[1])
        size = self.square_size
        x = float(self.board["playfield_near_x"]) + (rank - 0.5) * size
        # From White's side, a-file is on the robot's left (+Y).
        y_left_edge = float(self.board["playfield_center_y"]) + self.playfield_size / 2
        y = y_left_edge - (file_index + 0.5) * size
        return SquarePose(normalized, x, y, z)

    def squares(self, z: float = 0.0) -> Iterator[SquarePose]:
        for rank in RANKS:
            for file_name in FILES:
                yield self.square(f"{file_name}{rank}", z=z)

    def square_radius_range(self) -> tuple[float, float]:
        radii = [square.radius for square in self.squares()]
        return min(radii), max(radii)

    def capture_bin(self, color: str) -> tuple[float, float]:
        try:
            x, y = self.board["capture_bin_centers"][color.lower()]
        except KeyError as exc:
            raise ValueError(f"capture-bin color must be white or black, got {color!r}") from exc
        return float(x), float(y)

    def discard_slot(self, color: str, index: int) -> tuple[float, float, float]:
        """Resting pose of the ``index``-th captured piece of ``color``.

        Captured pieces are released at the chute mouth — see
        :meth:`capture_bin` — and the fabricated funnel carries them to a tray
        outside the arm's reach. The tray is deliberately unreachable (nearest
        slot ~339 mm against ~306 mm of arm), so however it fills it can never
        obstruct a planned motion, which is the whole reason captures are not
        stacked back inside the workspace.

        Slots are spaced at the tray pitch so pieces never overlap. A game
        produces at most 15 captures per colour and the tray holds 16.
        """

        board = self.board
        try:
            cx, cy = board["discard_tray_centers"][color.lower()]
        except KeyError as exc:
            raise ValueError(
                f"discard tray color must be white or black, got {color!r}"
            ) from exc
        capacity = int(board["discard_tray_capacity"])
        if not 0 <= index < capacity:
            raise ValueError(
                f"discard slot {index} outside tray capacity {capacity}"
            )
        pitch = float(board["discard_tray_pitch"])
        columns = int(board["discard_tray_columns"])
        offset = (columns - 1) / 2
        outward = 1.0 if cy > 0 else -1.0
        x = float(cx) + ((index % columns) - offset) * pitch
        y = float(cy) + ((index // columns) - offset) * pitch * outward
        return x, y, float(board["nominal_top_z"])

    def report(self) -> dict[str, Any]:
        rmin, rmax = self.square_radius_range()
        conditioned_min, conditioned_max = self.robot["conditioned_radius_range"]
        return {
            "schema_version": self.raw["schema_version"],
            "playfield_mm": round(self.playfield_size * 1000, 3),
            "square_mm": round(self.square_size * 1000, 3),
            "carrier_mm": [round(float(v) * 1000, 3) for v in self.board["carrier_size"]],
            "square_center_radius_mm": [round(rmin * 1000, 3), round(rmax * 1000, 3)],
            "inside_conditioned_radial_envelope": (
                rmin >= float(conditioned_min) and rmax <= float(conditioned_max)
            ),
            "piece_pitch_clearance_mm": round(
                (self.square_size - float(self.piece["base_diameter"])) * 1000, 3
            ),
            "tool_open_pitch_clearance_mm": round(
                (self.square_size - float(self.tool["maximum_open_outer_width"])) * 1000, 3
            ),
        }

    def _validate(self) -> None:
        if self.raw.get("schema_version") != 1:
            raise ValueError("unsupported geometry schema_version")
        if self.raw.get("units") != "m":
            raise ValueError("geometry contract must use metres")
        board = self.raw["board"]
        if board["files"] != 8 or board["ranks"] != 8:
            raise ValueError("this system requires an 8x8 chess board")
        if float(board["square_size"]) <= 0:
            raise ValueError("square_size must be positive")
        carrier_x, carrier_y, carrier_z = map(float, board["carrier_size"])
        if min(carrier_x, carrier_y) < self.playfield_size:
            raise ValueError("carrier must contain the playfield")
        if carrier_z <= 0:
            raise ValueError("carrier thickness must be positive")
        piece = self.raw["piece"]
        tool = self.raw["tool"]
        if float(piece["base_diameter"]) >= self.square_size:
            raise ValueError("piece base must be narrower than a square")
        if float(tool["maximum_open_outer_width"]) >= self.square_size:
            raise ValueError("open tool envelope must be narrower than the square pitch")
        mast_top = float(piece["grasp_mast_bottom_z"]) + float(piece["grasp_mast_height"])
        if mast_top > float(piece["total_height"]):
            raise ValueError("grasp mast exceeds total piece height")
        rmin, rmax = self.square_radius_range()
        conditioned_min, conditioned_max = map(float, self.robot["conditioned_radius_range"])
        if rmin < conditioned_min or rmax > conditioned_max:
            raise ValueError(
                f"square centers ({rmin:.3f}-{rmax:.3f} m) exceed conditioned reach "
                f"({conditioned_min:.3f}-{conditioned_max:.3f} m)"
            )
        joints = self.teleoperation["joint_order"]
        if len(joints) != 6 or len(set(joints)) != 6:
            raise ValueError("teleoperation joint_order must contain six unique joints")
        planning = self.motion_planning
        if len(planning["ready_joints_degrees"]) != 5:
            raise ValueError("motion-planning ready pose must contain five arm joints")
        if not 0 < float(planning["goal_bias"]) < 1:
            raise ValueError("motion-planning goal_bias must be between zero and one")


def load_geometry(path: str | Path = DEFAULT_CONFIG) -> ChessGeometry:
    source = Path(path).resolve()
    with source.open(encoding="utf-8") as handle:
        return ChessGeometry(json.load(handle), source=source)


if __name__ == "__main__":
    print(json.dumps(load_geometry().report(), indent=2))
