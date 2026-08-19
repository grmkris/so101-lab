"""Monitor the canonical remote-leader stream and enforce its deadman timer."""

from __future__ import annotations

import argparse
import time

from chess_system.teleop.protocol import JointStatePacket, LatestJointState


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--connect", default="tcp://127.0.0.1:5556")
    args = parser.parse_args()
    try:
        import zmq
    except ImportError as exc:
        raise SystemExit("requires pyzmq") from exc
    context = zmq.Context.instance()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.setsockopt(zmq.RCVHWM, 1)
    socket.connect(args.connect)
    latest = LatestJointState()
    last_state = None
    while True:
        if socket.poll(50):
            packet = JointStatePacket.from_bytes(socket.recv())
            latest.accept(packet)
        active = latest.latest()
        state = "ACTIVE" if active else "HOLD"
        if state != last_state:
            age = latest.age_seconds()
            print(f"{state}: age={age if age is not None else 'never'}")
            last_state = state
        if active:
            print(active.sequence, active.joints, end="\r", flush=True)
        time.sleep(0.01)


if __name__ == "__main__":
    main()
