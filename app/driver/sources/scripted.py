"""Scripted keyframe choreography as a Teleoperator (sim-only source).

Takes the backend (for unit conversion) and keyframes at construction so this
module imports nothing from backends (no cycles).
"""

import time
from dataclasses import dataclass
from pathlib import Path

from lerobot.teleoperators.teleoperator import Teleoperator


@dataclass
class ScriptedExpertConfig:
    id: str | None = "sim"
    calibration_dir: Path | None = None


class ScriptedExpert(Teleoperator):
    """Loops keyframe interpolation; emits lerobot-unit joint targets."""

    name = "sim_expert"
    config_class = ScriptedExpertConfig

    def __init__(self, backend, keyframes) -> None:
        self.b = backend
        self.keyframes = keyframes
        self.id = "sim"
        self.calibration_dir = None
        self.calibration = None
        self._t0 = time.time()

    def reset(self) -> None:
        self._t0 = time.time()

    @property
    def action_features(self) -> dict:
        return {f"{name}.pos": float for name in self.b.lerobot_joint_names}

    @property
    def feedback_features(self) -> dict:
        return {}

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:  # noqa: ARG002
        self._t0 = time.time()

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def get_action(self) -> dict:
        t = (time.time() - self._t0) % sum(d for _, d in self.keyframes)
        prev = self.keyframes[0][0]
        for target, dur in self.keyframes:
            if t <= dur:
                alpha = t / dur if dur > 0 else 1.0
                rad = [p + (q - p) * alpha for p, q in zip(prev, target)]
                return self.b.rad_to_lerobot(rad)
            t -= dur
            prev = target
        return self.b.rad_to_lerobot(self.keyframes[-1][0])

    def send_feedback(self, feedback: dict) -> None:
        pass

    def disconnect(self) -> None:
        pass
