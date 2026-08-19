"""Publish a physical SO-101 leader arm over the canonical ZMQ protocol.

Install ``pyzmq`` in the LeRobot environment first. This is intentionally a
small alternative to LeIsaac's own publisher: both transports use latest-only
PUB/SUB semantics, while this one makes the packet format explicit and testable.
"""

from __future__ import annotations

import argparse
import signal
import time

from chess_system.geometry import load_geometry
from chess_system.teleop.protocol import JointStatePacket


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="SO-101 leader serial port")
    parser.add_argument("--id", default="arm")
    parser.add_argument("--bind", default="tcp://0.0.0.0:5556")
    parser.add_argument("--source", default="so101_leader")
    args = parser.parse_args()

    try:
        import zmq
        from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
    except ImportError as exc:
        raise SystemExit("requires pyzmq and the pinned LeRobot hardware environment") from exc

    geometry = load_geometry()
    period = 1.0 / float(geometry.teleoperation["publish_hz"])
    context = zmq.Context.instance()
    socket = context.socket(zmq.PUB)
    socket.setsockopt(zmq.SNDHWM, 1)
    socket.bind(args.bind)
    leader = SO101Leader(SO101LeaderConfig(port=args.port, id=args.id, use_degrees=True))
    leader.connect(calibrate=False)
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    sequence = 0
    next_tick = time.perf_counter()
    try:
        while running:
            action = leader.get_action()
            joints = {name: action[f"{name}.pos"] for name in geometry.teleoperation["joint_order"]}
            packet = JointStatePacket.create(sequence, args.source, joints)
            socket.send(packet.to_bytes(), flags=zmq.NOBLOCK)
            sequence += 1
            next_tick += period
            time.sleep(max(0.0, next_tick - time.perf_counter()))
    finally:
        leader.disconnect()
        socket.close(linger=0)


if __name__ == "__main__":
    main()
