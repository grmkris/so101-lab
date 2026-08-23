"""Single-owner camera access for the lab host.

Why this exists
---------------
Two cameras, three consumers (lerobot recording, the vision loop, previews) and
exactly one kernel owner per V4L2 device.  Everything that touches `/dev/cam_*`
goes through `CameraOwner` so that:

* the MJPG pixel format is **asserted**, not requested.  A silent fall back to
  YUYV is what hangs the Innomaker outright (0/1800 frames, kernel EPROTO) and
  drags the healthy C922 through a USB reset with it.
* ownership is advisory-locked with `flock`, which the kernel releases on
  `kill -9`.  A PID file does not.
* every frame carries a real capture timestamp and a **monotonic per-camera
  sequence number**, so a camera that dies quietly can be detected instead of
  silently repeating its last frame into a dataset.

Nothing outside this package may call `cv2.VideoCapture` on `/dev/cam_*`.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

import cv2
import numpy as np

LOCK_PATH = os.environ.get("LAB_CAMS_LOCK", "/run/lock/lab-cams.lock")
SESSION_PATH = os.environ.get("LAB_SESSION_PATH", "/data/session.json")

DEFAULT_CAMERAS = {
    "workspace": "/dev/cam_context",
    "wrist": "/dev/cam_wrist",
}


class LabCameraError(RuntimeError):
    """Raised for anything that must never be papered over: a busy device, a
    format that did not take, a camera that never produced a frame."""


class CamerasBusy(LabCameraError):
    pass


def _fourcc(code: str) -> int:
    fn = getattr(cv2, "VideoWriter_fourcc", None) or cv2.VideoWriter.fourcc
    return int(fn(*code))


def _fourcc_str(value: float) -> str:
    v = int(value)
    if v <= 0:
        return "----"
    return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))


@dataclass
class Frame:
    """One captured frame plus the provenance needed to distrust it."""

    name: str
    seq: int
    mono_ts: float       # time.monotonic() at retrieve()
    wall_ts: float       # time.time() at retrieve()
    bgr: np.ndarray
    repeat: bool = False  # byte-identical to the previous frame from this camera

    @property
    def age_ms(self) -> float:
        return (time.monotonic() - self.mono_ts) * 1000.0

    def jpeg(self, quality: int = 80, width: int | None = None) -> bytes:
        img = self.bgr
        if width and img.shape[1] != width:
            h = max(1, round(img.shape[0] * width / img.shape[1]))
            img = cv2.resize(img, (width, h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise LabCameraError(f"jpeg encode failed for {self.name}")
        return buf.tobytes()


@dataclass
class CameraStats:
    frames: int = 0
    repeats: int = 0          # byte-identical consecutive frames (a frozen sensor)
    read_failures: int = 0
    stale_reads: int = 0      # latest() calls that exceeded max_age_ms
    last_seq: int = 0
    last_mono: float = 0.0
    fourcc: str = ""
    size: tuple = ()

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["size"] = list(self.size)
        return d


class _Reader(threading.Thread):
    """One thread per camera.  Grabs as fast as the device delivers and keeps
    only the newest frame — a slow consumer must never back-pressure capture."""

    daemon = True

    def __init__(self, name: str, cap: "cv2.VideoCapture", stats: CameraStats):
        super().__init__(name=f"labcam-{name}")
        self.cam_name = name
        self.cap = cap
        self.stats = stats
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._stopping = threading.Event()
        self._last_digest = b""
        self._first = threading.Event()

    def run(self) -> None:
        while not self._stopping.is_set():
            ok, img = self.cap.read()
            if not ok or img is None:
                self.stats.read_failures += 1
                time.sleep(0.005)
                continue
            mono, wall = time.monotonic(), time.time()
            # subsampled digest: 40x30x3 bytes, cheap enough to run every frame
            digest = hashlib.blake2b(img[::16, ::16].tobytes(), digest_size=8).digest()
            repeat = digest == self._last_digest
            self._last_digest = digest
            self.stats.frames += 1
            self.stats.repeats += int(repeat)
            self.stats.last_seq = self.stats.frames
            self.stats.last_mono = mono
            frame = Frame(self.cam_name, self.stats.frames, mono, wall, img, repeat)
            with self._lock:
                self._frame = frame
            self._first.set()

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    def wait_first(self, timeout: float) -> bool:
        return self._first.wait(timeout)

    def stop(self) -> None:
        self._stopping.set()


class CameraOwner:
    """Context manager holding exclusive ownership of the lab cameras.

        with CameraOwner(mode="vision") as cams:
            f = cams.latest("workspace", max_age_ms=500)

    `cameras` maps a logical name to a device path (or an int index for a dev
    box).  Logical names are what everything downstream uses; integer camera
    indexes are a macOS-era wart and do not appear anywhere else.
    """

    def __init__(
        self,
        cameras: dict | None = None,
        *,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        mode: str = "unknown",
        owner: str | None = None,
        require_mjpg: bool = True,
        first_frame_timeout: float = 10.0,
        session_path: str | None = SESSION_PATH,
        blocking: bool = False,
    ):
        self.cameras = dict(cameras or DEFAULT_CAMERAS)
        self.width, self.height, self.fps = width, height, fps
        self.mode = mode
        self.owner = owner or f"{os.path.basename(os.sys.argv[0]) or 'python'}[{os.getpid()}]"
        self.require_mjpg = require_mjpg
        self.first_frame_timeout = first_frame_timeout
        self.session_path = session_path
        self.blocking = blocking

        self.stats: dict[str, CameraStats] = {}
        self._caps: dict[str, cv2.VideoCapture] = {}
        self._readers: dict[str, _Reader] = {}
        self._lock_fd: int | None = None
        self._started_at = 0.0
        self._last_beat = 0.0
        self._extra: dict = {}

    # ---- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "CameraOwner":
        self._acquire_lock()
        try:
            for name, dev in self.cameras.items():
                self._open_one(name, dev)
            self._started_at = time.time()
            self._write_session()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _acquire_lock(self) -> None:
        os.makedirs(os.path.dirname(LOCK_PATH) or "/", exist_ok=True)
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
        flags = fcntl.LOCK_EX if self.blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, flags)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EACCES, errno.EAGAIN):
                raise CamerasBusy(
                    f"cameras are owned by another process ({LOCK_PATH}); "
                    f"current session: {read_session()}"
                ) from None
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {self.owner}\n".encode())
        self._lock_fd = fd

    def _open_one(self, name: str, dev) -> None:
        # CAP_V4L2 explicitly: the default backend probe is slow and has picked
        # GStreamer on some builds, which ignores CAP_PROP_FOURCC entirely.
        backend = cv2.CAP_V4L2 if os.name == "posix" and os.uname().sysname == "Linux" else cv2.CAP_ANY
        cap = cv2.VideoCapture(dev, backend)
        if not cap.isOpened():
            raise LabCameraError(f"{name}: cannot open {dev} (in use, or udev symlink missing)")
        self._caps[name] = cap

        # ORDER MATTERS: fourcc before size.  Setting size first makes some UVC
        # drivers pick a YUYV mode that then refuses the MJPG switch.
        cap.set(cv2.CAP_PROP_FOURCC, _fourcc("MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        # Deliberately NOT CAP_PROP_BUFFERSIZE=1: measured on this rig it halves the
        # Innomaker (74 -> 37 frames/3s) while doing nothing for the C922.  The reader
        # thread already drains the queue continuously, so latest-wins comes from the
        # loop, not from starving the driver.

        got = _fourcc_str(cap.get(cv2.CAP_PROP_FOURCC))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if self.require_mjpg and got != "MJPG":
            raise LabCameraError(
                f"{name} ({dev}) is {got}, not MJPG. Refusing to continue: YUYV at "
                f"{w}x{h} exceeds the USB 2.0 isochronous budget and hangs the device."
            )

        st = CameraStats(fourcc=got, size=(w, h))
        self.stats[name] = st
        reader = _Reader(name, cap, st)
        self._readers[name] = reader
        reader.start()
        if not reader.wait_first(self.first_frame_timeout):
            raise LabCameraError(
                f"{name} ({dev}) opened as {got} {w}x{h} but produced no frame in "
                f"{self.first_frame_timeout:.0f}s — {st.read_failures} failed reads"
            )

    def close(self) -> None:
        for r in self._readers.values():
            r.stop()
        for r in self._readers.values():
            r.join(timeout=2.0)
        for cap in self._caps.values():
            try:
                cap.release()
            except Exception:
                pass
        self._readers.clear()
        self._caps.clear()
        self._clear_session()
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    # ---- frames ------------------------------------------------------------

    def names(self) -> list:
        return list(self.cameras)

    def latest(self, name: str, max_age_ms: float | None = 500.0) -> Frame:
        """Newest frame from `name`.

        Raises if it is older than `max_age_ms` — a stale frame is exactly the
        failure this module exists to surface, so it is never returned quietly.
        Pass `max_age_ms=None` to accept whatever is there.
        """
        try:
            reader = self._readers[name]
        except KeyError:
            raise LabCameraError(f"unknown camera {name!r}; have {self.names()}") from None
        frame = reader.latest()
        if frame is None:
            raise LabCameraError(f"{name}: no frame captured yet")
        if max_age_ms is not None and frame.age_ms > max_age_ms:
            self.stats[name].stale_reads += 1
            raise LabCameraError(
                f"{name}: newest frame is {frame.age_ms:.0f}ms old (limit {max_age_ms:.0f}ms) "
                f"— camera stalled after {self.stats[name].frames} frames"
            )
        return frame

    def snap(self, name: str, max_age_ms: float | None = 500.0) -> np.ndarray:
        return self.latest(name, max_age_ms).bgr

    def all_latest(self, max_age_ms: float | None = 500.0) -> dict:
        return {n: self.latest(n, max_age_ms) for n in self.cameras}

    def health(self) -> dict:
        """Snapshot of every counter that indicates a camera is going bad."""
        now = time.monotonic()
        out = {}
        for name, st in self.stats.items():
            d = st.as_dict()
            d["age_ms"] = round((now - st.last_mono) * 1000.0, 1) if st.last_mono else None
            d["repeat_pct"] = round(100.0 * st.repeats / st.frames, 2) if st.frames else None
            elapsed = time.time() - self._started_at if self._started_at else 0
            d["fps"] = round(st.frames / elapsed, 2) if elapsed > 0.5 else None
            out[name] = d
        return out

    # ---- session file (the LCD reads this) ---------------------------------

    def set_session(self, **kw) -> None:
        """Merge extra fields (episode, total, task, repo_id) into session.json."""
        self._extra.update({k: v for k, v in kw.items() if v is not None})
        self._write_session(force=True)

    def beat(self) -> None:
        """Refresh the heartbeat; cheap enough to call from a control loop."""
        self._write_session()

    def _write_session(self, force: bool = False) -> None:
        if not self.session_path:
            return
        now = time.time()
        if not force and now - self._last_beat < 1.0:
            return
        self._last_beat = now
        doc = {
            "owner": self.owner,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "mode": self.mode,
            "cameras": {n: str(d) for n, d in self.cameras.items()},
            "resolution": [self.width, self.height],
            "started_at": self._started_at,
            "heartbeat": now,
            "health": self.health(),
        }
        doc.update(self._extra)
        _atomic_write_json(self.session_path, doc)

    def _clear_session(self) -> None:
        if not self.session_path:
            return
        try:
            doc = read_session() or {}
            if doc.get("pid") == os.getpid():
                os.unlink(self.session_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass


def _atomic_write_json(path: str, doc: dict) -> None:
    d = os.path.dirname(path) or "."
    try:
        os.makedirs(d, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, path)
    except OSError:
        pass  # a missing /data must never take down a recording


def read_session() -> dict | None:
    try:
        with open(SESSION_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def who_owns() -> dict | None:
    """Who currently holds the camera lock, or None if it is free."""
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    except OSError:
        return read_session() or {"owner": "unknown", "note": "lock held, no session.json"}
    finally:
        os.close(fd)
