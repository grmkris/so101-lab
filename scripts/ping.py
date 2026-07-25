"""Ping every follower motor and report which respond.

Run (from repo root, uses the driver's pinned lerobot env):
      app/driver/.venv/bin/python scripts/ping.py
Port defaults to Kristjan's follower — edit PORT below for another arm.
"""

from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

PORT = "/dev/tty.usbmodem5AE60832001"
ID = "robo_arm_follower"

robot = SO101Follower(SO101FollowerConfig(port=PORT, id=ID))
robot.bus.connect(handshake=False)  # open the port, don't enable torque
try:
    found = robot.bus.broadcast_ping() or {}
    print("responding motor ids:", sorted(found))
    for name, motor in robot.bus.motors.items():
        ok = motor.id in found
        print(f"  id={motor.id} {name:14} {'OK' if ok else 'NO RESPONSE'}")
finally:
    robot.bus.disconnect()
