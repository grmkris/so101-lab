# Teleoperation runbook

## Safety invariant

Teleoperation never broadens authority: the operator remains beside the physical arm with an accessible power cutoff. Network loss, stale packets, an invalid value, or an unexpected board observation enters hold/stop rather than extrapolating motion.

## Canonical packet

The versioned packet in `chess_system.teleop.protocol` contains:

```json
{
  "version": 1,
  "sequence": 42,
  "monotonic_ns": 123456789,
  "source": "so101_leader",
  "joints": {
    "shoulder_pan": 0.0,
    "shoulder_lift": 0.0,
    "elbow_flex": 0.0,
    "wrist_flex": 0.0,
    "wrist_roll": 0.0,
    "gripper": 50.0
  }
}
```

Arm joints use degrees; gripper uses `0–100`. Publisher rate is 50 Hz, consumer control cadence is 30 Hz, and the watchdog is 250 ms. Consumers reject repeated/out-of-order sequence numbers and use only the newest packet.

## Preflight

1. Clear the arm and cable sweep volume.
2. Put the follower and board against their keyed stops.
3. Verify follower and leader serial ports; macOS indices can change after reconnect.
4. Check that the correct leader calibration ID is loaded.
5. Fit and tighten both marked finger extensions.
6. Run the TCP calibration fixture.
7. Start with follower torque disabled and compare leader/follower neutral frames.
8. Verify the power cutoff and software stop.
9. Start at reduced velocity with an empty board.

Known local ports at the time this artifact was generated:

```text
follower /dev/tty.usbmodem5AE60832001
leader   /dev/tty.usbmodem5AE60538411
id       arm
```

Always rediscover rather than assuming these are unchanged.

## Repository publisher

Install `pyzmq` into a LeRobot-capable environment, then:

```bash
python -m chess_system.teleop.leader_publisher \
  --port /dev/tty.usbmodem5AE60538411 \
  --id arm \
  --bind tcp://0.0.0.0:5556
```

Monitor locally:

```bash
python -m chess_system.teleop.subscriber_monitor \
  --connect tcp://127.0.0.1:5556
```

## Official LeIsaac publisher

For Isaac, the official server is preferred because it feeds `SO101LeaderRemote` directly:

```bash
cd /path/to/leisaac
python scripts/environments/teleoperation/so101_joint_state_server.py \
  --port /dev/tty.usbmodem5AE60538411 --id arm --rate 50
```

Runpod connects to `tcp://<mac-tailnet-ip>:5556`. If direct tailnet reachability is unavailable, use the documented SSH reverse tunnel and connect the pod to `tcp://localhost:5556`.

## MuJoCo

```bash
sim/.venv/bin/python -m chess_system.mujoco.teleop \
  --connect tcp://127.0.0.1:5556
```

The custom MuJoCo adapter uses the same scene and actuator mapping as the test backend. Confirm the console prints `ACTIVE`; stop the publisher and confirm it prints `HOLD` within 250 ms.

## Physical follower

Use the pinned LeRobot 0.6.0 environment and existing calibration. First perform empty-board direct teleoperation using the commands in `notes/crib-sheet.md`. The chess tool requires a separate recorded TCP/tool profile; do not overwrite the stock-tool calibration.

For DAgger collection, use `lerobot-rollout --strategy.type=dagger` with the SO-101 leader. `tab` takes and releases operator control. Record slow, deliberate motions; teleoperation speed is part of the demonstrated policy.

## Shutdown

1. Stop recording and mark the episode success/failure.
2. Return to a collision-free home pose.
3. Stop consumer, then publisher.
4. Disable follower torque.
5. Disconnect USB.
6. Remove and inspect the extensions.
7. Log version, board/tool calibration hashes, camera identities, lighting, and result.
