"""Browser preview for the lab cameras — and the click UI the headless host needs.

Two jobs, one server:

* **Aim the cameras.** `python -m lab_cameras.preview` opens the cameras and
  serves a live MJPEG page, so the C922 can be repositioned while watching the
  frame it will actually record.
* **Click a pixel.** `cv2` on the Pi is the headless build, so `calibrate.py`'s
  click-a-window UI cannot run there. The page reports the pixel you click, in
  full-resolution coordinates, which is all that calibration needs.

During a recording the server does not touch the cameras at all: the recorder
owns them and pushes frames in through `publish()` (see `RecordTee`). A preview
that re-read the hardware would contend with the control loop; a preview that
copies frames already in flight costs one JPEG encode off the loop.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

from lab_cameras.owner import CameraOwner, LabCameraError

PREVIEW_QUALITY = 55
PREVIEW_WIDTH = 480          # 0 = native
TEE_MIN_INTERVAL_S = 0.04    # ~25 preview fps ceiling; the control loop comes first

_FRAMES: dict = {}           # name -> (jpeg bytes, seq, wall_ts, native_size)
_LOCK = threading.Lock()
_CLICKS: list = []


def publish(name: str, bgr, seq: int = 0, ts: float | None = None) -> None:
    """Push one BGR frame into the preview. Never raises — a dead preview must
    never take a recording with it."""
    try:
        native = (bgr.shape[1], bgr.shape[0])
        img = bgr
        if PREVIEW_WIDTH and img.shape[1] > PREVIEW_WIDTH:
            h = max(1, round(img.shape[0] * PREVIEW_WIDTH / img.shape[1]))
            img = cv2.resize(img, (PREVIEW_WIDTH, h), interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_QUALITY])
        if not ok:
            return
        with _LOCK:
            _FRAMES[name] = (jpg.tobytes(), seq, ts or time.time(), native)
    except Exception:
        pass


def clicks() -> list:
    """Drain the pixel clicks recorded since the last call."""
    with _LOCK:
        out, _CLICKS[:] = list(_CLICKS), []
    return out


class RecordTee:
    """`observation_tap` for `lerobot.scripts.lerobot_record.record_loop`.

    Wrapping the observation processor means no lerobot patch: `record_loop`
    only ever *calls* the processor, so a plain function is a valid stand-in.
    Frames are copied out of the control loop and encoded on a worker thread.
    """

    def __init__(self, names: dict | None = None):
        # lerobot hands observations keyed "observation.images.<cam>" as RGB
        self.names = names or {
            "observation.images.workspace_cam": "workspace",
            "observation.images.wrist_cam": "wrist",
        }
        self._mailbox: dict = {}
        self._last: dict = {}
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._n = 0
        self._thread = threading.Thread(target=self._loop, name="record-tee", daemon=True)
        self._thread.start()

    def __call__(self, obs: dict) -> None:
        try:
            now = time.monotonic()
            for key, name in self.names.items():
                frame = obs.get(key)
                if frame is None or now - self._last.get(name, 0.0) < TEE_MIN_INTERVAL_S:
                    continue
                self._last[name] = now
                self._mailbox[name] = frame.copy()  # latest-wins, single slot
            self._wake.set()
        except Exception:
            pass  # a dead preview beats a dead recording

    def _loop(self) -> None:
        while not self._stopping.is_set():
            self._wake.wait(0.5)
            self._wake.clear()
            for name in list(self._mailbox):
                rgb = self._mailbox.pop(name, None)
                if rgb is None:
                    continue
                self._n += 1
                publish(name, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), seq=self._n)

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()


PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>lab cameras</title>
<style>
 body{background:#111;color:#ddd;font:14px/1.4 ui-monospace,monospace;margin:0;padding:12px}
 .row{display:flex;flex-wrap:wrap;gap:12px}
 figure{margin:0}
 img{display:block;max-width:100%;border:1px solid #333;cursor:crosshair}
 figcaption{padding:4px 0;color:#8ab}
 #log{margin-top:12px;white-space:pre-wrap;color:#6c6}
</style>
<div class=row id=cams></div>
<div id=log>click a camera to record a pixel (full-resolution coordinates)</div>
<script>
const cams = __NAMES__;
const root = document.getElementById('cams'), log = document.getElementById('log');
for (const name of cams) {
  const fig = document.createElement('figure');
  fig.innerHTML = `<img src="/cam/${name}" data-name="${name}">
                   <figcaption>${name}</figcaption>`;
  root.appendChild(fig);
}
root.addEventListener('click', async ev => {
  const img = ev.target.closest('img'); if (!img) return;
  const r = img.getBoundingClientRect();
  const body = {name: img.dataset.name,
                x: (ev.clientX - r.left) / r.width,
                y: (ev.clientY - r.top) / r.height};
  const res = await fetch('/click', {method:'POST', body: JSON.stringify(body)});
  const j = await res.json();
  log.textContent = `${j.name}  px=(${j.px}, ${j.py})  of ${j.width}x${j.height}\\n` + log.textContent;
});
</script>
"""


def _handler(cams: CameraOwner | None, names: list):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _pull(self, name: str) -> None:
            """In live mode the server owns the cameras and pulls; in record
            mode frames arrive via publish() and there is nothing to pull."""
            if cams is None:
                return
            try:
                f = cams.latest(name, max_age_ms=2000)
                publish(name, f.bgr, seq=f.seq, ts=f.wall_ts)
            except LabCameraError:
                pass

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                body = PAGE.replace("__NAMES__", json.dumps(names)).encode()
                return self._send(200, "text/html; charset=utf-8", body)
            if path == "/health":
                doc = cams.health() if cams else {n: {"pushed": n in _FRAMES} for n in names}
                return self._send(200, "application/json", json.dumps(doc, indent=2).encode())
            if path.startswith("/snap/"):
                name = path[6:]
                self._pull(name)
                with _LOCK:
                    entry = _FRAMES.get(name)
                if entry is None:
                    return self._send(503, "text/plain", b"no frame yet\n")
                return self._send(200, "image/jpeg", entry[0])
            if path.startswith("/cam/"):
                return self._stream(path[5:])
            return self._send(404, "text/plain", b"not found\n")

        def _stream(self, name: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    self._pull(name)
                    with _LOCK:
                        entry = _FRAMES.get(name)
                    if entry is None or entry[1] == last:
                        time.sleep(0.02)
                        continue
                    jpg, last = entry[0], entry[1]
                    self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\n"
                                     b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n")
                    self.wfile.write(jpg + b"\r\n")
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if self.path != "/click":
                return self._send(404, "text/plain", b"not found\n")
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            name = req.get("name", "")
            with _LOCK:
                entry = _FRAMES.get(name)
            w, h = entry[3] if entry else (0, 0)
            px, py = round(req.get("x", 0) * w), round(req.get("y", 0) * h)
            rec = {"name": name, "px": px, "py": py, "width": w, "height": h, "t": time.time()}
            with _LOCK:
                _CLICKS.append(rec)
            print(f"click {name} px=({px}, {py})", flush=True)
            return self._send(200, "application/json", json.dumps(rec).encode())

    return Handler


def serve(cams: CameraOwner | None, names: list, port: int = 8088) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), _handler(cams, names))
    threading.Thread(target=srv.serve_forever, daemon=True, name="preview").start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(description="Live camera preview + pixel picker")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl-C")
    args = ap.parse_args()

    with CameraOwner(mode="preview") as cams:
        serve(cams, cams.names(), args.port)
        print(f"preview on http://0.0.0.0:{args.port}/  (cameras: {', '.join(cams.names())})",
              flush=True)
        t0 = time.time()
        try:
            while not args.seconds or time.time() - t0 < args.seconds:
                time.sleep(1.0)
                cams.beat()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
