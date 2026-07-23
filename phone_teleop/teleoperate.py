# !/usr/bin/env python

# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specif

import time

from lerobot.model.kinematics import RobotKinematics
from lerobot.processor import (
    RobotProcessorPipeline,
    robot_action_observation_to_transition,
    transition_to_robot_action,
)
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
from lerobot.robots.so_follower.robot_kinematic_processor import (
    EEBoundsAndSafety,
    EEReferenceAndDelta,
    GripperVelocityToJoint,
    InverseKinematicsEEToJoints,
)
from lerobot.teleoperators.phone import Phone, PhoneConfig
from lerobot.teleoperators.phone.config_phone import PhoneOS
from lerobot.teleoperators.phone.phone_processor import MapPhoneActionToRobotAction
from lerobot.types import RobotAction, RobotObservation
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.visualization_utils import init_rerun, log_rerun_data

FPS = 30


def main():
    # Initialize the robot and teleoperator
    robot_config = SO101FollowerConfig(
        port="/dev/tty.usbmodem5AE60832001", id="arm", use_degrees=True
    )
    teleop_config = PhoneConfig(phone_os=PhoneOS.IOS)  # or PhoneOS.ANDROID

    # Initialize the robot and teleoperator
    robot = SO101Follower(robot_config)
    teleop_device = Phone(teleop_config)

    # NOTE: It is highly recommended to use the urdf in the SO-ARM100 repo: https://github.com/TheRobotStudio/SO-ARM100/blob/main/Simulation/SO101/so101_new_calib.urdf
    kinematics_solver = RobotKinematics(
        urdf_path="./SO101/so101_new_calib.urdf",
        target_frame_name="gripper_frame_link",
        joint_names=list(robot.bus.motors.keys()),
    )

    # Build pipeline to convert phone action to ee pose action to joint action
    phone_to_robot_joints_processor = RobotProcessorPipeline[
        tuple[RobotAction, RobotObservation], RobotAction
    ](
        steps=[
            MapPhoneActionToRobotAction(platform=teleop_config.phone_os),
            EEReferenceAndDelta(
                kinematics=kinematics_solver,
                # gentler mapping: phone motion -> smaller arm motion (less lunging)
                end_effector_step_sizes={"x": 0.3, "y": 0.3, "z": 0.3},
                motor_names=list(robot.bus.motors.keys()),
                use_latched_reference=True,
            ),
            EEBoundsAndSafety(
                end_effector_bounds={"min": [-0.5, -0.5, -0.1], "max": [0.5, 0.5, 0.5]},
                max_ee_step_m=0.08,  # cap per-frame jump; fast phone moves get skipped, not lunged
            ),
            GripperVelocityToJoint(
                speed_factor=20.0,
            ),
            InverseKinematicsEEToJoints(
                kinematics=kinematics_solver,
                motor_names=list(robot.bus.motors.keys()),
                initial_guess_current_joints=True,
            ),
        ],
        to_transition=robot_action_observation_to_transition,
        to_output=transition_to_robot_action,
    )

    # Connect to the robot and teleoperator (retry phone discovery — the app
    # backgrounding / screen-lock drops it off the network intermittently).
    robot.connect()
    for attempt in range(10):
        try:
            teleop_device.connect()
            break
        except RuntimeError as e:
            print(f"[phone connect retry {attempt + 1}/10] {e}\n  -> keep HEBI app foreground, screen on, on the hotspot.")
            time.sleep(2.0)
    else:
        raise RuntimeError("Could not connect to phone after retries. Check app/network/firewall.")

    # Init rerun viewer
    init_rerun(session_name="phone_so100_teleop")

    if not robot.is_connected or not teleop_device.is_connected:
        raise ValueError("Robot or teleop is not connected!")

    print("Starting teleop loop. Hold B1 + move the phone. Ctrl+C to STOP (arm goes safe).")
    try:
        while True:
            t0 = time.perf_counter()
            try:
                robot_obs = robot.get_observation()
                phone_obs = teleop_device.get_action()
                joint_action = phone_to_robot_joints_processor((phone_obs, robot_obs))
                _ = robot.send_action(joint_action)
                log_rerun_data(observation=phone_obs, action=joint_action)
            except ValueError as e:
                # EE-jump safety trip on a fast phone move — skip this frame
                # instead of crashing (and instead of lunging).
                print(f"[skip frame] {e}")
            precise_sleep(max(1.0 / FPS - (time.perf_counter() - t0), 0.0))
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        # CRITICAL: always disconnect so torque is disabled and the arm goes
        # limp/safe. Without this, Ctrl+C leaves the arm powered and holding.
        try:
            teleop_device.disconnect()
        except Exception:
            pass
        robot.disconnect()  # disable_torque_on_disconnect=True -> arm relaxes
        print("Robot disconnected, torque disabled. Safe.")


if __name__ == "__main__":
    main()
