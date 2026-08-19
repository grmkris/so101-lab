"""Versioned, simulator-neutral leader-arm packet format."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import asdict, dataclass
from typing import Mapping

from chess_system.geometry import load_geometry


PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class JointStatePacket:
    version: int
    sequence: int
    monotonic_ns: int
    source: str
    joints: dict[str, float]

    @classmethod
    def create(cls, sequence: int, source: str, joints: Mapping[str, float]) -> "JointStatePacket":
        geometry = load_geometry()
        ordered = geometry.teleoperation["joint_order"]
        missing = [name for name in ordered if name not in joints]
        if missing:
            raise ValueError(f"joint packet missing: {', '.join(missing)}")
        values = {name: float(joints[name]) for name in ordered}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("joint packet contains non-finite values")
        low, high = geometry.teleoperation["gripper_range"]
        if not float(low) <= values["gripper"] <= float(high):
            raise ValueError(f"gripper outside {low}-{high}: {values['gripper']}")
        return cls(PROTOCOL_VERSION, int(sequence), time.monotonic_ns(), source, values)

    def to_bytes(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, payload: bytes) -> "JointStatePacket":
        raw = json.loads(payload.decode("utf-8"))
        if raw.get("version") != PROTOCOL_VERSION:
            raise ValueError(f"unsupported teleop protocol: {raw.get('version')}")
        packet = cls(
            version=raw["version"],
            sequence=int(raw["sequence"]),
            monotonic_ns=int(raw["monotonic_ns"]),
            source=str(raw["source"]),
            joints={key: float(value) for key, value in raw["joints"].items()},
        )
        # Reuse create's schema checks without replacing the transmitted clock.
        cls.create(packet.sequence, packet.source, packet.joints)
        return packet


class LatestJointState:
    """Thread-safe latest-only buffer with ordering and deadman semantics."""

    def __init__(self, watchdog_seconds: float | None = None):
        geometry = load_geometry()
        self.watchdog_seconds = float(
            geometry.teleoperation["watchdog_seconds"] if watchdog_seconds is None else watchdog_seconds
        )
        self._packet: JointStatePacket | None = None
        self._received_ns: int | None = None
        self._lock = threading.Lock()

    def accept(self, packet: JointStatePacket, *, received_ns: int | None = None) -> bool:
        now = time.monotonic_ns() if received_ns is None else int(received_ns)
        with self._lock:
            if self._packet is not None and packet.sequence <= self._packet.sequence:
                return False
            self._packet = packet
            self._received_ns = now
            return True

    def latest(self, *, now_ns: int | None = None) -> JointStatePacket | None:
        now = time.monotonic_ns() if now_ns is None else int(now_ns)
        with self._lock:
            if self._packet is None or self._received_ns is None:
                return None
            age = (now - self._received_ns) / 1_000_000_000
            return self._packet if age <= self.watchdog_seconds else None

    def age_seconds(self, *, now_ns: int | None = None) -> float | None:
        now = time.monotonic_ns() if now_ns is None else int(now_ns)
        with self._lock:
            if self._received_ns is None:
                return None
            return max(0.0, (now - self._received_ns) / 1_000_000_000)
