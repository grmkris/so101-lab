"""Browser-keyboard teleop source — lerobot-native EE control.

lerobot's KeyboardEndEffectorTeleop with ONLY the input layer swapped: axis
state arrives from the browser via the driver's `teleop_input` RPC instead of
pynput (which needs macOS Accessibility permission). Everything downstream is
lerobot's own chain: EEReferenceAndDelta -> EEBoundsAndSafety ->
GripperVelocityToJoint -> InverseKinematicsEEToJoints (Placo IK).

Runs open-loop: the joint observation fed to the chain is the last action this
source emitted (seeded from the backend's measured joints at start) — the
standard way to run these steps without holding a robot handle.
"""

import time
from dataclasses import dataclass
from pathlib import Path

from lerobot.model.kinematics import RobotKinematics
from lerobot.processor import (
    RobotProcessorPipeline,
    robot_action_observation_to_transition,
    transition_to_robot_action,
)
from lerobot.robots.so_follower.robot_kinematic_processor import (
    EEBoundsAndSafety,
    EEReferenceAndDelta,
    GripperVelocityToJoint,
    InverseKinematicsEEToJoints,
)
from lerobot.teleoperators.teleoperator import Teleoperator
from lerobot.types import RobotAction, RobotObservation

STALE_INPUT_S = 0.5  # deadman: browser silent for this long -> hold pose


@dataclass
class BrowserKeysConfig:
    id: str | None = "browser"
    calibration_dir: Path | None = None


class BrowserKeys(Teleoperator):
    name = "browser_keys"
    config_class = BrowserKeysConfig

    def __init__(self, urdf_path: str, motor_names: list[str], seed_obs: dict[str, float]) -> None:
        self.id = "browser"
        self.calibration_dir = None
        self.calibration = None
        self.motor_names = motor_names

        kinematics = RobotKinematics(
            urdf_path=urdf_path,
            target_frame_name="gripper_frame_link",
            joint_names=motor_names,
        )
        self.pipeline = RobotProcessorPipeline[tuple[RobotAction, RobotObservation], RobotAction](
            steps=[
                EEReferenceAndDelta(
                    kinematics=kinematics,
                    # per-frame jog step at 30 fps: 0.0025 m -> ~0.075 m/s at full deflection
                    end_effector_step_sizes={"x": 0.0025, "y": 0.0025, "z": 0.0025},
                    motor_names=motor_names,
                    use_latched_reference=False,  # continuous jog against current pose
                ),
                EEBoundsAndSafety(
                    end_effector_bounds={"min": [-0.5, -0.5, -0.1], "max": [0.5, 0.5, 0.5]},
                    max_ee_step_m=0.08,
                ),
                GripperVelocityToJoint(speed_factor=30.0),
                InverseKinematicsEEToJoints(
                    kinematics=kinematics,
                    motor_names=motor_names,
                    initial_guess_current_joints=True,
                ),
            ],
            to_transition=robot_action_observation_to_transition,
            to_output=transition_to_robot_action,
        )

        self.axes = {"x": 0.0, "y": 0.0, "z": 0.0, "gripper": 0.0}
        self.last_input = 0.0
        self.obs: dict[str, float] = dict(seed_obs)

    def set_input(self, axes: dict) -> None:
        for key in self.axes:
            if key in axes:
                self.axes[key] = max(-1.0, min(1.0, float(axes[key])))
        self.last_input = time.time()

    def get_action(self) -> dict:
        stale = time.time() - self.last_input > STALE_INPUT_S
        ax = dict.fromkeys(self.axes, 0.0) if stale else self.axes
        active = any(abs(v) > 1e-6 for v in ax.values())

        raw = {
            "enabled": active,
            "target_x": ax["x"],
            "target_y": ax["y"],
            "target_z": ax["z"],
            "target_wx": 0.0,
            "target_wy": 0.0,
            "target_wz": 0.0,
            "gripper_vel": ax["gripper"],
        }
        joint_action = self.pipeline((raw, self.obs))
        self.obs = dict(joint_action)  # open-loop feedback for FK/IK seeding
        return joint_action

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

    def send_feedback(self, feedback: dict) -> None:
        pass

    def disconnect(self) -> None:
        pass
