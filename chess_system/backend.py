"""Common backend interface for MuJoCo, Isaac and the physical arm."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .geometry import SquarePose
from .model import ExecutabilityReport, ManipulationResult, MovePlan


@runtime_checkable
class ChessBackend(Protocol):
    name: str

    def square_pose(self, square: str, phase: str) -> SquarePose:
        """Return the backend pose for hover/grasp/lift/place/retreat."""

    def execute_plan(self, plan: MovePlan) -> ManipulationResult:
        """Execute a prepared physical move without mutating chess-engine state."""

    def can_execute(self, plan: MovePlan) -> ExecutabilityReport:
        """Preflight a legal plan for mechanical reachability, without moving.

        Optional. Backends that cannot answer should report ``executable=True``
        and let ``execute_plan`` fail; the controller treats a missing
        implementation the same way.
        """

    def observe_occupancy(self) -> dict[str, bool]:
        """Return occupancy for all 64 algebraic squares."""

    def board_pose_error(self) -> tuple[float, float]:
        """Return board translation in metres and rotation in degrees."""

    def home(self) -> None:
        """Move to the backend's safe home pose."""

    def hold(self) -> None:
        """Stop advancing targets while maintaining a safe position."""

    def emergency_stop(self) -> None:
        """Immediately enter the backend's safest available stopped state."""
