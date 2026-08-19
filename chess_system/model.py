"""Simulator-neutral chess manipulation types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal


class ResultStatus(StrEnum):
    VERIFIED = "verified"
    RETRYABLE = "retryable"
    OPERATOR_REQUIRED = "operator_required"
    FAILED = "failed"
    STOPPED = "stopped"


StepKind = Literal["move", "capture", "castle_rook", "promotion_pause"]


@dataclass(frozen=True)
class MoveStep:
    kind: StepKind
    source: str | None = None
    target: str | None = None
    capture_bin: Literal["white", "black"] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MovePlan:
    move_id: str
    uci: str
    steps: tuple[MoveStep, ...]
    occupancy_before: dict[str, bool]
    occupancy_after: dict[str, bool]
    expected_fen_after: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManipulationResult:
    status: ResultStatus
    move_id: str
    completed_steps: int = 0
    message: str = ""
    observed_occupancy: dict[str, bool] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == ResultStatus.VERIFIED
