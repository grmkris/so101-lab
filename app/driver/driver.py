#!/usr/bin/env python
"""Lab Console robot driver.

Protocol: ndjson-RPC over stdio. stdout carries ONLY protocol lines
(responses + events); all logging goes to stderr. Frames are served over a
localhost MJPEG HTTP port (binary over stdio is misery).

Commands (request: {"id": int, "cmd": str, ...}):
  hello                          -> {driver, version, backend}
  list_cameras                   -> probe indexes 0..5, return [{index,width,height}]
  preview_start {cameras:[{name,index,width,height,fps}]} -> {started:[names]}
  preview_stop                   -> {stopped: true}

Events (no id): {"event": "ready", ...} on boot,
                {"event": "brightness", "values": {name: mean_gray}} 1/s while previewing.

Robot commands (connect/teleop/record) arrive in later milestones; `backend`
is reserved for 'real' | 'sim'.
"""

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

FRAMES: dict[str, bytes] = {}
BRIGHTNESS: dict[str, float] = {}
LOCK = threading.Lock()
STOP_FLAGS: list[threading.Event] = []


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def log(msg: str) -> None:
    print(f"[driver] {msg}", file=sys.stderr, flush=True)


def capture_loop(name: str, index: int, width: int, height: int, fps: int, stop: threading.Event) -> None:
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    log(f"capture {name} (index {index}) started")
    n = 0
    while not stop.is_set():
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue
        n += 1
        if n % 15 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            with LOCK:
                BRIGHTNESS[name] = round(float(gray.mean()), 1)
        ok2, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok2:
            with LOCK:
                FRAMES[name] = jpg.tobytes()
    cap.release()
    with LOCK:
        FRAMES.pop(name, None)
        BRIGHTNESS.pop(name, None)
    log(f"capture {name} stopped")


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep HTTP noise off stderr
        pass

    def do_GET(self) -> None:
        if self.path.startswith("/cam/"):
            name = self.path.rsplit("/", 1)[-1]
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    with LOCK:
                        data = FRAMES.get(name)
                    if data:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                        )
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self.send_response(404)
            self.end_headers()


# ---------- robot (crib: lelab/teleoperate.py — worker owns disconnect) ----------

ROBOT: dict = {"robot": None, "teleop": None, "state": "disconnected", "teleop_active": False}
JOINTS: dict[str, float] = {}


def _emit_robot_state() -> None:
    emit({"event": "robot_state", "state": ROBOT["state"]})


def _safe_disconnect(device) -> None:
    if device is None:
        return
    try:
        device.disconnect()
    except Exception as exc:  # noqa: BLE001
        log(f"disconnect error (ignored): {exc}")


def cmd_connect(req: dict) -> dict:
    if ROBOT["state"] != "disconnected":
        raise ValueError(f"already {ROBOT['state']} — disconnect first")

    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    robot_id = req.get("robotId", "arm")
    robot = None
    teleop = None
    try:
        robot = SO101Follower(SO101FollowerConfig(port=req["followerPort"], id=robot_id))
        try:
            robot.bus.connect()
        except Exception as exc:
            raise RuntimeError(
                f"Could not connect to the follower arm on {req['followerPort']}. "
                "Plugged in, powered, and not held by LeLab/CLI?"
            ) from exc
        robot.bus.write_calibration(robot.calibration)
        robot.configure()

        if req.get("leaderPort"):
            teleop = SO101Leader(SO101LeaderConfig(port=req["leaderPort"], id=robot_id))
            try:
                teleop.bus.connect()
            except Exception as exc:
                raise RuntimeError(
                    f"Could not connect to the leader arm on {req['leaderPort']}. "
                    "Plugged in, powered, and not held by LeLab/CLI?"
                ) from exc
            teleop.bus.write_calibration(teleop.calibration)
            teleop.configure()

        ROBOT.update(robot=robot, teleop=teleop, state="connected")
        _emit_robot_state()
        return {"state": "connected", "leader": teleop is not None}
    except Exception:
        _safe_disconnect(robot)
        _safe_disconnect(teleop)
        ROBOT.update(robot=None, teleop=None, state="disconnected")
        raise


def cmd_disconnect() -> dict:
    ROBOT["teleop_active"] = False
    time.sleep(0.1)
    _safe_disconnect(ROBOT["robot"])
    _safe_disconnect(ROBOT["teleop"])
    ROBOT.update(robot=None, teleop=None, state="disconnected")
    JOINTS.clear()
    _emit_robot_state()
    return {"state": "disconnected"}


def cmd_torque(on: bool) -> dict:
    robot = ROBOT["robot"]
    if robot is None:
        raise ValueError("not connected")
    if on:
        robot.bus.enable_torque()
    else:
        robot.bus.disable_torque()
    return {"torque": on}


def cmd_estop() -> dict:
    """Torque kill. Arm goes limp — hold it if it's raised."""
    ROBOT["teleop_active"] = False
    robot = ROBOT["robot"]
    if robot is not None:
        try:
            robot.bus.disable_torque()
        except Exception as exc:  # noqa: BLE001
            log(f"estop disable_torque error: {exc}")
    ROBOT["state"] = "connected" if robot is not None else "disconnected"
    _emit_robot_state()
    return {"estopped": True}


def _read_joints(robot) -> dict[str, float]:
    obs = robot.get_observation()
    return {k.removesuffix(".pos"): round(float(v), 2) for k, v in obs.items() if k.endswith(".pos")}


def cmd_get_joints() -> dict:
    robot = ROBOT["robot"]
    if robot is None:
        raise ValueError("not connected")
    return _read_joints(robot)


def teleop_worker() -> None:
    robot, teleop = ROBOT["robot"], ROBOT["teleop"]
    last_emit = 0.0
    try:
        while ROBOT["teleop_active"]:
            action = teleop.get_action()
            robot.send_action(action)
            now = time.time()
            if now - last_emit >= 0.1:
                JOINTS.update(_read_joints(robot))
                emit({"event": "joints", "values": dict(JOINTS)})
                last_emit = now
            time.sleep(0.001)
    except Exception as exc:  # noqa: BLE001
        log(f"teleop loop error: {exc}")
        emit({"event": "error", "where": "teleop", "error": str(exc)})
    finally:
        ROBOT["teleop_active"] = False
        ROBOT["state"] = "connected"
        _emit_robot_state()


def cmd_teleop_start() -> dict:
    if ROBOT["robot"] is None or ROBOT["teleop"] is None:
        raise ValueError("connect with a leader arm first")
    if ROBOT["teleop_active"]:
        raise ValueError("teleop already active")
    ROBOT["teleop_active"] = True
    ROBOT["state"] = "teleop"
    threading.Thread(target=teleop_worker, name="teleop-worker", daemon=True).start()
    _emit_robot_state()
    return {"state": "teleop"}


def cmd_teleop_stop() -> dict:
    ROBOT["teleop_active"] = False
    return {"state": "connected"}


def cmd_list_cameras() -> list[dict]:
    stop_previews()  # macOS: only one owner per device
    found = []
    for idx in range(6):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok:
                h, w = frame.shape[:2]
                found.append({"index": idx, "width": w, "height": h})
        cap.release()
    return found


def cmd_preview_start(cameras: list[dict]) -> dict:
    stop_previews()
    started = []
    for cam in cameras:
        stop = threading.Event()
        STOP_FLAGS.append(stop)
        threading.Thread(
            target=capture_loop,
            args=(
                cam["name"],
                cam["index"],
                cam.get("width", 640),
                cam.get("height", 480),
                cam.get("fps", 30),
                stop,
            ),
            daemon=True,
        ).start()
        started.append(cam["name"])
    return {"started": started}


def stop_previews() -> None:
    for flag in STOP_FLAGS:
        flag.set()
    STOP_FLAGS.clear()
    time.sleep(0.2)


def brightness_reporter() -> None:
    while True:
        time.sleep(1)
        with LOCK:
            values = dict(BRIGHTNESS)
        if values:
            emit({"event": "brightness", "values": values})


def orphan_watchdog() -> None:
    """Exit if the supervising server dies without closing our stdin."""
    import os

    while True:
        time.sleep(2)
        if os.getppid() == 1:
            log("orphaned (parent died), exiting")
            os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mjpeg-port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.mjpeg_port), MJPEGHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=brightness_reporter, daemon=True).start()
    threading.Thread(target=orphan_watchdog, daemon=True).start()

    emit({"event": "ready", "mjpegPort": args.mjpeg_port, "backend": "real"})
    log(f"ready, mjpeg on :{args.mjpeg_port}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            emit({"id": None, "ok": False, "error": "bad json"})
            continue
        rid = req.get("id")
        cmd = req.get("cmd")
        try:
            if cmd == "hello":
                result = {"driver": "lab-console", "version": "0.1.0", "backend": "real"}
            elif cmd == "list_cameras":
                result = cmd_list_cameras()
            elif cmd == "preview_start":
                result = cmd_preview_start(req.get("cameras", []))
            elif cmd == "preview_stop":
                stop_previews()
                result = {"stopped": True}
            elif cmd == "connect":
                result = cmd_connect(req)
            elif cmd == "disconnect":
                result = cmd_disconnect()
            elif cmd == "torque":
                result = cmd_torque(bool(req.get("on")))
            elif cmd == "estop":
                result = cmd_estop()
            elif cmd == "teleop_start":
                result = cmd_teleop_start()
            elif cmd == "teleop_stop":
                result = cmd_teleop_stop()
            elif cmd == "get_joints":
                result = cmd_get_joints()
            else:
                raise ValueError(f"unknown cmd: {cmd}")
            emit({"id": rid, "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 — protocol boundary
            emit({"id": rid, "ok": False, "error": str(exc)})

    stop_previews()
    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
