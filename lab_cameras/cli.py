"""`python -m lab_cameras <cmd>` — operator tools for the camera layer.

    probe      what the kernel offers, and whether MJPG is really available
    who        who currently owns the cameras
    snap       write a JPEG per camera
    watch      live health counters (fps, repeats, stalls)
    recover    the documented fix after a UVC hang
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from lab_cameras.owner import DEFAULT_CAMERAS, CameraOwner, LabCameraError, who_owns


def _devices(args) -> dict:
    if not args.camera:
        return dict(DEFAULT_CAMERAS)
    return {n: DEFAULT_CAMERAS.get(n, n) for n in args.camera}


def cmd_probe(args) -> int:
    rc = 0
    for name, dev in _devices(args).items():
        print(f"\n=== {name}  {dev}")
        if not os.path.exists(dev):
            print("  MISSING — udev symlink absent; check 99-so101-lab.rules")
            rc = 1
            continue
        print("  ->", os.path.realpath(dev))
        for cmd in (["v4l2-ctl", "-d", dev, "--list-formats-ext"],):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
            except FileNotFoundError:
                print("  (v4l2-ctl not installed)")
                break
            mjpg = "Motion-JPEG" in out or "MJPG" in out
            print(f"  MJPG offered: {'yes' if mjpg else 'NO — this device will hang at 640x480'}")
            if not mjpg:
                rc = 1
    return rc


def cmd_who(args) -> int:
    owner = who_owns()
    print(json.dumps(owner, indent=2) if owner else "cameras are free")
    return 0


def cmd_snap(args) -> int:
    with CameraOwner(_devices(args), mode="snap") as cams:
        for name in cams.names():
            f = cams.latest(name, max_age_ms=None)
            path = os.path.join(args.out, f"{name}.jpg")
            os.makedirs(args.out, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(f.jpeg(quality=args.quality))
            print(f"{name}: seq={f.seq} {f.bgr.shape[1]}x{f.bgr.shape[0]} -> {path}")
    return 0


def cmd_watch(args) -> int:
    with CameraOwner(_devices(args), mode="watch") as cams:
        t0 = time.time()
        try:
            while time.time() - t0 < args.seconds:
                time.sleep(1.0)
                cams.beat()
                row = []
                for name, h in cams.health().items():
                    row.append(
                        f"{name} {h['fps'] or 0:5.1f}fps rep{h['repeat_pct'] or 0:5.1f}% "
                        f"age{h['age_ms'] or 0:6.0f}ms fail{h['read_failures']}"
                    )
                print("  |  ".join(row), flush=True)
        except KeyboardInterrupt:
            pass
        print("\nfinal:", json.dumps(cams.health(), indent=2))
    return 0


def cmd_recover(args) -> int:
    """After a UVC hang the device node stays open in a dead process; the only
    reliable fix measured on this rig is SIGKILL plus a settle."""
    for pat in ("lerobot-record", "lab_cameras", "capture.py", "desk.py"):
        subprocess.run(["pkill", "-9", "-f", pat], capture_output=True)
    time.sleep(5)
    for name, dev in DEFAULT_CAMERAS.items():
        print(f"{name}: {'present' if os.path.exists(dev) else 'MISSING'} -> "
              f"{os.path.realpath(dev) if os.path.exists(dev) else '-'}")
    print("if a device is still missing, replug it — the USB controller needs the reset")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lab_cameras")
    ap.add_argument("-c", "--camera", action="append", help="limit to this camera (repeatable)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe").set_defaults(fn=cmd_probe)
    sub.add_parser("who").set_defaults(fn=cmd_who)
    p = sub.add_parser("snap")
    p.add_argument("--out", default="/tmp/labcam")
    p.add_argument("--quality", type=int, default=90)
    p.set_defaults(fn=cmd_snap)
    p = sub.add_parser("watch")
    p.add_argument("--seconds", type=float, default=30)
    p.set_defaults(fn=cmd_watch)
    sub.add_parser("recover").set_defaults(fn=cmd_recover)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except LabCameraError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
