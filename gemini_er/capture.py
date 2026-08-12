"""Grab one frame from a webcam.

Usage: python capture.py <index> [out.jpg]
"""

import sys

import cv2


def grab(index: int, w: int = 640, h: int = 480, warmup: int = 30):
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    for _ in range(warmup):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"camera {index} gave no frame (in use by another process, or unplugged?)")
    return frame


if __name__ == "__main__":
    idx = int(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else f"cam{idx}.jpg"
    cv2.imwrite(out, grab(idx))
    print(out)
