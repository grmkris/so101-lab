"""Shared driver state: frame buffers for the MJPEG server + protocol emit."""

import json
import sys
import threading

FRAMES: dict[str, bytes] = {}
BRIGHTNESS: dict[str, float] = {}
LOCK = threading.Lock()

_EMIT_LOCK = threading.Lock()  # emit happens from worker threads too


def emit(obj) -> None:
    with _EMIT_LOCK:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def log(msg: str) -> None:
    print(f"[driver] {msg}", file=sys.stderr, flush=True)
