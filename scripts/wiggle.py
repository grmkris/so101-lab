"""Smoke test: wiggle the SO-101 follower around its current pose.

Run:  cd ~/Code/github-com/LeRobot/lerobot && source .venv/bin/activate
      python ../wiggle.py
"""

import math
import time

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

PORT = "/dev/tty.usbmodem5AE60832001"
ID = "robo_arm_follower"  # must match the --robot.id used in lerobot-calibrate

DURATION_S = 8
HZ = 30
AMPLITUDE = 12  # small, in normalized position units
JOINTS = ["wrist_roll", "wrist_flex", "gripper"]

config = SO101FollowerConfig(port=PORT, id=ID)
robot = SO101Follower(config)
robot.connect(calibrate=False)  # use the calibration you just saved

try:
    home = robot.get_observation()
    center = {j: home[f"{j}.pos"] for j in JOINTS}
    print("start pose:", {k: round(v, 1) for k, v in center.items()})

    t0 = time.perf_counter()
    while (t := time.perf_counter() - t0) < DURATION_S:
        action = {}
        for i, j in enumerate(JOINTS):
            phase = 2 * math.pi * 0.5 * t + i * 2.0  # 0.5 Hz, offset per joint
            action[f"{j}.pos"] = center[j] + AMPLITUDE * math.sin(phase)
        robot.send_action(action)
        time.sleep(1 / HZ)

    # return to start
    robot.send_action({f"{j}.pos": center[j] for j in JOINTS})
    time.sleep(0.5)
    print("wiggle done, back to start pose")
finally:
    robot.disconnect()
