"""Drive the generated MuJoCo SO-101 from the canonical ZMQ leader stream."""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import mujoco

from chess_system.geometry import load_geometry
from chess_system.mujoco.backend import DEFAULT_SCENE
from chess_system.teleop.protocol import JointStatePacket, LatestJointState


def packet_to_controls(model: mujoco.MjModel, packet: JointStatePacket) -> list[float]:
    controls = []
    for actuator_id in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator_id)
        if name not in packet.joints:
            # Non-arm actuator: hold its neutral midpoint.
            low, high = model.actuator_ctrlrange[actuator_id]
            controls.append(float((low + high) / 2))
            continue
        value = packet.joints[name]
        low, high = map(float, model.actuator_ctrlrange[actuator_id])
        if name == "gripper":
            command = low + (high - low) * (value / 100.0)
        else:
            command = math.radians(value)
        controls.append(min(high, max(low, command)))
    return controls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--connect", default="tcp://127.0.0.1:5556")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--duration", type=float, default=0.0, help="0 means run until interrupted")
    args = parser.parse_args()
    try:
        import zmq
    except ImportError as exc:
        raise SystemExit("install pyzmq in sim/.venv before running remote teleoperation") from exc

    geometry = load_geometry()
    model = mujoco.MjModel.from_xml_path(str(args.scene.resolve()))
    data = mujoco.MjData(model)
    context = zmq.Context.instance()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.setsockopt(zmq.RCVHWM, 1)
    socket.connect(args.connect)
    latest = LatestJointState()
    viewer = None
    if not args.headless:
        from mujoco import viewer as mj_viewer

        viewer = mj_viewer.launch_passive(model, data)
    t0 = time.monotonic()
    next_control = t0
    control_period = 1.0 / float(geometry.teleoperation["control_hz"])
    last_state = None
    try:
        while args.duration <= 0 or time.monotonic() - t0 < args.duration:
            while socket.poll(0):
                latest.accept(JointStatePacket.from_bytes(socket.recv()))
            packet = latest.latest()
            state = "ACTIVE" if packet else "HOLD"
            if state != last_state:
                print(state)
                last_state = state
            if packet:
                data.ctrl[:] = packet_to_controls(model, packet)
            else:
                # Position actuators hold the most recently commanded targets.
                data.ctrl[:] = data.ctrl
            target = next_control + control_period
            while data.time < target - t0:
                mujoco.mj_step(model, data)
            next_control = target
            if viewer:
                viewer.sync()
            time.sleep(max(0.0, next_control - time.monotonic()))
    finally:
        if viewer:
            viewer.close()
        socket.close(linger=0)


if __name__ == "__main__":
    main()
