"""Serializable trajectory contracts for MuJoCo and the physical backend seam."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any


class MotionMode(StrEnum):
    PICKUP_EXIT = "pickup_exit"
    PLACEMENT_ENTRY = "placement_entry"
    CAPTURE_BIN_ENTRY = "capture_bin_entry"


@dataclass(frozen=True)
class TrajectoryMetrics:
    planning_attempt: int
    planning_iterations: int
    raw_waypoints: int
    final_waypoints: int
    duration_seconds: float
    minimum_joint_margin_degrees: float
    nominal_clearance_m: float
    tolerance_replays: int = 0
    tolerance_failures: int = 0


@dataclass(frozen=True)
class JointTrajectory:
    trajectory_id: str
    mode: MotionMode
    target: str
    scenario: str
    joint_names: tuple[str, ...]
    waypoints_degrees: tuple[tuple[float, ...], ...]
    timestamps_seconds: tuple[float, ...]
    gripper_normalized: tuple[float, ...]
    attachment_enabled: tuple[bool, ...]
    metrics: TrajectoryMetrics
    checksum: str = ""

    def with_checksum(self) -> "JointTrajectory":
        payload = self.to_dict(include_checksum=False)
        checksum = hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return replace(self, checksum=checksum)

    def to_dict(self, *, include_checksum: bool = True) -> dict[str, Any]:
        raw = asdict(self)
        raw["mode"] = self.mode.value
        if not include_checksum:
            raw.pop("checksum", None)
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "JointTrajectory":
        return cls(
            trajectory_id=raw["trajectory_id"],
            mode=MotionMode(raw["mode"]),
            target=raw["target"],
            scenario=raw["scenario"],
            joint_names=tuple(raw["joint_names"]),
            waypoints_degrees=tuple(tuple(float(v) for v in row) for row in raw["waypoints_degrees"]),
            timestamps_seconds=tuple(float(v) for v in raw["timestamps_seconds"]),
            gripper_normalized=tuple(float(v) for v in raw["gripper_normalized"]),
            attachment_enabled=tuple(bool(v) for v in raw["attachment_enabled"]),
            metrics=TrajectoryMetrics(**raw["metrics"]),
            checksum=raw["checksum"],
        )

    def reversed_for_placement(self) -> "JointTrajectory":
        if self.mode != MotionMode.PICKUP_EXIT:
            raise ValueError("only pickup exits can be reversed into placement entries")
        waypoints = tuple(reversed(self.waypoints_degrees))
        duration = self.timestamps_seconds[-1]
        timestamps = tuple(duration - t for t in reversed(self.timestamps_seconds))
        trajectory = JointTrajectory(
            trajectory_id=f"entry:{self.target}",
            mode=MotionMode.PLACEMENT_ENTRY,
            target=self.target,
            scenario=self.scenario,
            joint_names=self.joint_names,
            waypoints_degrees=waypoints,
            timestamps_seconds=timestamps,
            gripper_normalized=tuple(reversed(self.gripper_normalized)),
            attachment_enabled=tuple(reversed(self.attachment_enabled)),
            metrics=self.metrics,
        )
        return trajectory.with_checksum()


@dataclass
class TrajectoryLibrary:
    schema_version: int = 1
    geometry_schema_version: int = 1
    trajectories: dict[str, JointTrajectory] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)

    def add(self, trajectory: JointTrajectory) -> None:
        checked = trajectory if trajectory.checksum else trajectory.with_checksum()
        self.trajectories[checked.trajectory_id] = checked

    def require(self, trajectory_id: str) -> JointTrajectory:
        try:
            return self.trajectories[trajectory_id]
        except KeyError as exc:
            raise KeyError(f"trajectory missing from library: {trajectory_id}") from exc

    def save(self, path: str | Path) -> None:
        payload = {
            "schema_version": self.schema_version,
            "geometry_schema_version": self.geometry_schema_version,
            "generation": self.generation,
            "trajectories": {
                key: trajectory.to_dict() for key, trajectory in sorted(self.trajectories.items())
            },
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "TrajectoryLibrary":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        library = cls(
            schema_version=int(raw["schema_version"]),
            geometry_schema_version=int(raw["geometry_schema_version"]),
            generation=dict(raw.get("generation", {})),
        )
        for key, value in raw["trajectories"].items():
            trajectory = JointTrajectory.from_dict(value)
            expected = trajectory.with_checksum().checksum
            if trajectory.checksum != expected:
                raise ValueError(f"trajectory checksum mismatch: {key}")
            library.trajectories[key] = trajectory
        return library
