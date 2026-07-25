#!/usr/bin/env python
"""Leader-over-wire controller: your leader arm drives a remote rig via the hub.

Runs on the OPERATOR's machine (nothing else needed — no console, no driver).
Reads the local leader at ~30 Hz and ships its lerobot-space action dict
(degrees + gripper 0..100) to the hub, which relays it to the rig's
remote-joints teleop source. Cross-device is safe by construction: each arm
normalizes through its OWN calibration; the servo EEPROM limits on the
follower side are the hard stop.

Usage (from app/driver, after `uv sync` and calibrating the leader with id
`arm`):

    .venv/bin/python controller.py \
        --hub https://hub-production-3903.up.railway.app \
        --rig kris-sim \
        --port /dev/tty.usbmodemXXXX

Ctrl-C stops teleop and releases the rig. Losing the network mid-run is safe:
the rig holds pose after 0.5 s without packets.
"""

import argparse
import json
import signal
import sys
import time
import urllib.error
import urllib.request

from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig


def api(hub: str, path: str, payload: dict, timeout: float = 2.0) -> dict:
    req = urllib.request.Request(
        f"{hub}{path}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read() or b"{}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub", required=True, help="hub base URL")
    parser.add_argument("--rig", required=True, help="rig name from the lobby")
    parser.add_argument("--port", required=True, help="leader serial port")
    parser.add_argument("--id", default="arm", help="leader calibration id")
    parser.add_argument("--hz", type=float, default=30.0)
    args = parser.parse_args()

    hub = args.hub.rstrip("/")
    rig = f"/api/hub/rigs/{args.rig}"
    client = {"clientId": f"leader-{int(time.time()) % 100000}"}

    print(f"connecting leader on {args.port} …")
    leader = SO101Leader(SO101LeaderConfig(port=args.port, id=args.id))
    leader.connect()
    print("leader up — claiming the rig")

    try:
        api(hub, f"{rig}/claim", client)
    except urllib.error.HTTPError as err:
        if err.code == 409:
            sys.exit("rig is held by another operator — try again later")
        raise
    api(hub, f"{rig}/command", {**client, "verb": "teleop_start_remote"})
    print("driving — move the leader. Ctrl-C to stop.")

    running = True

    def stop(*_sig) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    sent = dropped = 0
    window = time.time()
    while running:
        tick = time.time()
        action = leader.get_action()  # {"<joint>.pos": deg, "gripper.pos": 0..100}
        try:
            api(hub, f"{rig}/input", {**client, "joints": action}, timeout=0.5)
            sent += 1
        except (urllib.error.URLError, TimeoutError, OSError):
            dropped += 1  # latest-wins on the hub; the next packet corrects
        if time.time() - window >= 5.0:
            rate = sent / (time.time() - window)
            print(f"  {rate:.0f} packets/s up, {dropped} dropped")
            sent = dropped = 0
            window = time.time()
        time.sleep(max(0.0, 1.0 / args.hz - (time.time() - tick)))

    print("\nstopping teleop, releasing the rig")
    for path, payload in (
        (f"{rig}/command", {**client, "verb": "teleop_stop"}),
        (f"{rig}/release", client),
    ):
        try:
            api(hub, path, payload)
        except Exception:  # noqa: BLE001 — best effort on the way out
            pass
    leader.disconnect()


if __name__ == "__main__":
    main()
