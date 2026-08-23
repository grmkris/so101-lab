"""Grab one frame from a camera.

Usage: python capture.py <workspace|wrist|/dev/path|index> [out.jpg]

Kept as a standalone one-shot on purpose: it is what `desk.py` shells out to on
hosts without `lab_cameras`, and process isolation is what stops a hung UVC
device from taking the caller down with it.
"""

import sys
import time

import cv2

import devices


def grab(cam, w: int = 640, h: int = 480, warmup: int = 30, retries: int = 3):
    """`cam` is a role name ("workspace"/"wrist"), a device path, or an index.

    Legacy integer indexes are routed through the resolver too, so every caller
    that still reads `calib["camera_index"]` lands on the right udev name on the
    room host without being touched.
    """
    dev = cam if isinstance(cam, str) and cam.startswith("/") else devices.camera(cam)
    for attempt in range(retries):
        cap = cv2.VideoCapture(dev)
        # MJPG first, then size: some UVC drivers latch a YUYV mode from the
        # size and then refuse the format switch. YUYV at 640x480 is what hangs
        # the Innomaker when two cameras share a controller.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        for _ in range(warmup):
            cap.read()
        ok, frame = cap.read()
        cap.release()
        if ok:
            return frame
        time.sleep(1.0 + attempt)  # macOS device handoff needs a beat sometimes
    raise RuntimeError(f"camera {cam} ({dev}) gave no frame after {retries} tries (in use, or unplugged?)")


if __name__ == "__main__":
    which = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"cam_{which.strip('/').replace('/', '_')}.jpg"
    cv2.imwrite(out, grab(int(which) if which.isdigit() else which))
    print(out)
