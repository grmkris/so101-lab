"""Helpers for driving the SO-101 MuJoCo model with the same position-dict
interface the real arm uses (degrees, gripper 0-100). Ported from the
ECE 4560 SO-101 lab (maegantucker.com/ECE4560/assignment4-so101/).

MuJoCo works in radians; the real SO-101 stack works in degrees with the
gripper normalized 0-100. These converters keep sim code looking like
hardware code.
"""
import math
import time

import mujoco

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]


def convert_to_dictionary(qpos):
    d = {j: qpos[i] * 180.0 / math.pi for i, j in enumerate(JOINTS)}
    d["gripper"] = qpos[5] * 100.0 / math.pi  # 0-100 range
    return d


def convert_to_list(dictionary):
    pos = [dictionary[j] * math.pi / 180.0 for j in JOINTS]
    pos.append(dictionary["gripper"] * math.pi / 100.0)
    return pos


def set_initial_pose(d, position_dict):
    """Write joint positions directly into the sim state (teleport, no physics)."""
    d.qpos = convert_to_list(position_dict)


def send_position_command(d, position_dict):
    """Set position targets; MuJoCo's built-in PD actuators (gains from the XML)
    track them — same idea as the real servos' position mode."""
    d.ctrl = convert_to_list(position_dict)


def move_to_pose(m, d, viewer, desired_position, duration):
    """Linearly interpolate from the current pose to desired_position over
    `duration` seconds, stepping physics along the way. viewer=None runs headless."""
    start_time = time.time()
    starting_pose = convert_to_dictionary(d.qpos.copy())

    while True:
        t = time.time() - start_time
        if t > duration:
            break
        alpha = min(t / duration, 1)
        position_dict = {
            joint: (1 - alpha) * starting_pose[joint] + alpha * desired_position[joint]
            for joint in desired_position
        }
        send_position_command(d, position_dict)
        mujoco.mj_step(m, d)
        if viewer is not None:
            viewer.sync()


def hold_position(m, d, viewer, duration):
    """Hold the current pose for `duration` seconds. viewer=None runs headless."""
    current_pos_dict = convert_to_dictionary(d.qpos.copy())
    start_time = time.time()
    while True:
        t = time.time() - start_time
        if t > duration:
            break
        send_position_command(d, current_pos_dict)
        mujoco.mj_step(m, d)
        if viewer is not None:
            viewer.sync()
