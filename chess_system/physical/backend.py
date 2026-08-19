"""Physical backend composed from tested motion and camera providers.

This module contains no serial-port side effects. The coupon-tested hardware
primitive is injected through ``PhysicalMotion`` so importing or testing chess
logic can never energize the arm accidentally.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from chess_system.geometry import SquarePose, load_geometry
from chess_system.model import ManipulationResult, MovePlan, ResultStatus
from chess_system.vision.occupancy import BoardObservation, BoardVerifier


class PhysicalMotion(Protocol):
    def pick_and_place(self, source: str, target: str) -> None: ...

    def capture_to_bin(self, source: str, color: str) -> None: ...

    def home(self) -> None: ...

    def hold(self) -> None: ...

    def emergency_stop(self) -> None: ...


class PhysicalChessBackend:
    name = "physical"

    def __init__(
        self,
        motion: PhysicalMotion,
        verifier: BoardVerifier,
        capture_frame: Callable[[], object],
    ):
        self.geometry = load_geometry()
        self.motion = motion
        self.verifier = verifier
        self.capture_frame = capture_frame
        self._last_observation: BoardObservation | None = None
        self._stopped = False

    def square_pose(self, square: str, phase: str) -> SquarePose:
        top = float(self.geometry.board["nominal_top_z"])
        mast = self.geometry.piece
        grasp = top + float(mast["grasp_mast_bottom_z"]) + float(mast["grasp_mast_height"]) / 2
        z_by_phase = {
            "hover": top + 0.080,
            "grasp": grasp,
            "lift": top + 0.080,
            "place": grasp,
            "retreat": top + 0.080,
        }
        if phase not in z_by_phase:
            raise ValueError(f"unknown motion phase: {phase}")
        return self.geometry.square(square, z=z_by_phase[phase])

    def execute_plan(self, plan: MovePlan) -> ManipulationResult:
        if self._stopped:
            return ManipulationResult(ResultStatus.STOPPED, plan.move_id, message="physical backend stopped")
        completed = 0
        try:
            for step in plan.steps:
                if step.kind == "capture":
                    self.motion.capture_to_bin(step.source or "", step.capture_bin or "black")
                elif step.kind in ("move", "castle_rook"):
                    self.motion.pick_and_place(step.source or "", step.target or "")
                elif step.kind == "promotion_pause":
                    pass
                completed += 1
        except Exception as exc:
            self.motion.hold()
            return ManipulationResult(
                ResultStatus.FAILED,
                plan.move_id,
                completed_steps=completed,
                message=f"physical primitive failed: {exc}",
            )
        return ManipulationResult(
            ResultStatus.VERIFIED,
            plan.move_id,
            completed_steps=completed,
            message="physical primitives complete; awaiting camera verification",
        )

    def _observe(self) -> BoardObservation:
        self._last_observation = self.verifier.observe(self.capture_frame())
        return self._last_observation

    def observe_occupancy(self) -> dict[str, bool]:
        return self._observe().occupancy

    def board_pose_error(self) -> tuple[float, float]:
        observation = self._last_observation or self._observe()
        return observation.translation_error_m, observation.rotation_error_degrees

    def home(self) -> None:
        if self._stopped:
            raise RuntimeError("explicitly reset the hardware stop before homing")
        self.motion.home()

    def hold(self) -> None:
        self.motion.hold()

    def emergency_stop(self) -> None:
        self._stopped = True
        self.motion.emergency_stop()
