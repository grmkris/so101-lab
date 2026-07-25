"""Remote-joints teleop source — joint targets arriving over the hub link.

The operator's machine (controller.py) reads a physical leader arm and ships
its lerobot-space action dict (degrees + gripper 0..100, `<joint>.pos` keys)
through the hub; this source hands the latest one to the teleop loop. No IK,
no remapping — cross-device leader->follower works by construction in lerobot
0.6.0 because each end normalizes through its OWN calibration.

Safety on the wire:
- values are clamped and non-finite ones dropped BEFORE they reach the
  backend (a negative raw tick raises deep inside lerobot's _unnormalize —
  a malformed packet must not kill the loop)
- stale input (no packet for 0.5s) -> hold the last action, i.e. the arm
  freezes where it is; same deadman contract as the browser-keys source
"""

import math
import time

from lerobot.teleoperators.teleoperator import Teleoperator

STALE_INPUT_S = 0.5
BODY_RANGE = (-180.0, 180.0)  # degrees; servo EEPROM limits are the real gate
GRIPPER_RANGE = (0.0, 100.0)


class RemoteJointsConfig:
    id: str | None = "remote"
    calibration_dir = None


class RemoteJoints(Teleoperator):
    name = "remote_joints"
    config_class = RemoteJointsConfig

    def __init__(self, motor_names: list[str], seed_obs: dict[str, float]) -> None:
        self.id = "remote"
        self.calibration_dir = None
        self.calibration = None
        self.motor_names = motor_names
        # hold pose until the first packet lands
        self.action: dict[str, float] = dict(seed_obs)
        self.last_input = 0.0

    def set_joints(self, joints: dict) -> None:
        cleaned: dict[str, float] = {}
        for name in self.motor_names:
            key = f"{name}.pos"
            value = joints.get(key, joints.get(name))
            if value is None:
                continue
            value = float(value)
            if not math.isfinite(value):
                continue
            lo, hi = GRIPPER_RANGE if name == "gripper" else BODY_RANGE
            cleaned[key] = max(lo, min(hi, value))
        if cleaned:
            self.action.update(cleaned)
            self.last_input = time.time()

    def get_action(self) -> dict:
        # stale -> keep returning the last action: the arm holds pose
        return dict(self.action)

    # --- Teleoperator boilerplate ---

    @property
    def action_features(self) -> dict:
        return {f"{name}.pos": float for name in self.motor_names}

    @property
    def feedback_features(self) -> dict:
        return {}

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self, calibrate: bool = True) -> None:  # noqa: ARG002
        pass

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def get_feedback(self) -> dict:
        return {}

    def send_feedback(self, feedback: dict) -> None:
        pass

    def disconnect(self) -> None:
        pass
