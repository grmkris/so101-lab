"""Persistent SO-101 desk CLI: one serve process holds torque; other verbs are clients.

Serve (driver venv — GUI cv2 + placo + lerobot 0.6.0):
  PY=../../eth-global-lisbon-2026-proof-of-hands/apps/driver/.venv/bin/python
  $PY desk.py serve            # live arm; do not start unless asked to pick/place
  $PY desk.py serve --dry      # no serial, for smoke

Client (any python):
  python desk.py pose | snap [workspace|wrist|both] | cams | status
  python desk.py delta shoulder_pan=-4 gripper=80
  python desk.py goto ready
  python desk.py grip 80
  python desk.py grip-state
  python desk.py save tub_hover
  python desk.py stop

Do not run alongside arm_daemon.py — both own the serial port.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEBUG = HERE / "debug"
POSES_PATH = HERE / "desk_poses.json"
CMDS = DEBUG / "desk_cmds.jsonl"
REPLY = DEBUG / "desk_reply.json"
STATUS = DEBUG / "desk_status.json"
PID_PATH = DEBUG / "desk.pid"
SNAP_DIR = DEBUG / "desk_snaps"

JOINTS = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]
DELTA_CLAMP_DEG = 8.0
GRIP_OPEN = 45.0
HELD_MIN = 5.0
EMPTY_MAX = 5.0
HEARTBEAT_S = 2.5
CLIENT_TIMEOUT_S = 60.0

# Seeded from arm_daemon READY when desk_poses.json is missing.
DEFAULT_READY = {
    "shoulder_pan": 3.3,
    "shoulder_lift": -34.3,
    "elbow_flex": 31.4,
    "wrist_flex": 56.0,
    "wrist_roll": -11.5,
    "gripper": 50.0,
}


def _out(obj: dict) -> None:
    print(json.dumps(obj, default=str), flush=True)


def load_poses() -> dict:
    if not POSES_PATH.exists():
        return {"ready": dict(DEFAULT_READY)}
    data = json.loads(POSES_PATH.read_text())
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save_poses(poses: dict) -> None:
    POSES_PATH.write_text(json.dumps(poses, indent=2) + "\n")


def load_cam_indexes() -> tuple[int, int]:
    calib = HERE / "calib.json"
    workspace, wrist = 0, 1
    if calib.exists():
        c = json.loads(calib.read_text())
        workspace = int(c.get("camera_index", 0))
        wrist = int(c.get("wrist", {}).get("camera_index", 1))
    workspace = int(os.environ.get("DESK_CAM_WORKSPACE", workspace))
    wrist = int(os.environ.get("DESK_CAM_WRIST", wrist))
    return workspace, wrist


def serve_alive() -> bool:
    if not PID_PATH.exists() or not STATUS.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)
    except (ValueError, OSError):
        return False
    age = time.time() - STATUS.stat().st_mtime
    return age < HEARTBEAT_S + 2.0


def send_cmd(payload: dict, timeout: float = CLIENT_TIMEOUT_S) -> dict:
    if not serve_alive():
        return {
            "ok": False,
            "error": "desk serve is not running. Start: $PY gemini_er/desk.py serve",
        }
    payload = dict(payload)
    payload["id"] = payload.get("id") or uuid.uuid4().hex[:12]
    DEBUG.mkdir(parents=True, exist_ok=True)
    CMDS.touch()
    with open(CMDS, "a") as f:
        f.write(json.dumps(payload) + "\n")
        f.flush()
        os.fsync(f.fileno())
    deadline = time.time() + timeout
    while time.time() < deadline:
        if REPLY.exists():
            try:
                rec = json.loads(REPLY.read_text())
            except json.JSONDecodeError:
                rec = {}
            if rec.get("id") == payload["id"]:
                return rec
        time.sleep(0.05)
    return {"ok": False, "id": payload["id"], "error": f"timeout after {timeout}s"}


# ---------------- serve ----------------

class DryRobot:
    def __init__(self):
        self.j = dict(DEFAULT_READY)
        self.bus = type("Bus", (), {"motors": {n: None for n in JOINTS}})()

    def get_observation(self):
        return {f"{k}.pos": float(v) for k, v in self.j.items()}

    def send_action(self, action: dict):
        for key, val in action.items():
            name = key.replace(".pos", "")
            if name in self.j:
                self.j[name] = float(val)

    def connect(self, calibrate=False):
        return None

    def disconnect(self):
        return None


def joints_of(robot) -> dict[str, float]:
    obs = robot.get_observation()
    return {n: float(obs[f"{n}.pos"]) for n in JOINTS}


def classify_grip(g: float, last_close: float | None) -> str:
    if g >= GRIP_OPEN:
        return "open"
    if last_close is not None and last_close < GRIP_OPEN:
        return "held" if g > last_close + 3.5 else "empty"
    if g < EMPTY_MAX:
        return "empty"
    if g >= HELD_MIN:
        return "held"
    return "unknown"


def clamp_delta(joints: dict) -> dict:
    out = {}
    for name, val in joints.items():
        if name not in JOINTS:
            raise ValueError(f"unknown joint {name}")
        v = float(val)
        if name != "gripper":
            v = max(-DELTA_CLAMP_DEG, min(DELTA_CLAMP_DEG, v))
        else:
            v = max(0.0, min(100.0, v))
        out[name] = v
    return out


class DeskServe:
    def __init__(self, dry: bool, allow_unprobed: bool):
        self.dry = dry
        self.allow_unprobed = allow_unprobed
        self.robot = None
        self.kin = None
        self.arm = None
        self.cams_ok = False
        self.cam_w, self.cam_r = load_cam_indexes()
        self.last_close: float | None = None
        self.hold: dict[str, float] = dict(DEFAULT_READY)
        self.cmd_offset = 0
        self.poses = load_poses()
        self._stopping = False

    def start(self):
        DEBUG.mkdir(parents=True, exist_ok=True)
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        CMDS.touch()
        self.cmd_offset = CMDS.stat().st_size
        PID_PATH.write_text(str(os.getpid()))
        if self.dry:
            self.robot = DryRobot()
            self.hold = joints_of(self.robot)
            return
        sys.path.insert(0, str(HERE))
        import arm as arm_mod

        self.arm = arm_mod
        self.robot = arm_mod.connect(max_relative_target=12.0)
        self.kin = arm_mod.kinematics(self.robot)
        self.hold = joints_of(self.robot)

    def shutdown(self, *_args):
        self._stopping = True

    def write_status(self):
        pose = joints_of(self.robot) if self.robot is not None else {}
        STATUS.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "dry": self.dry,
                    "cams_ok": self.cams_ok,
                    "cam_workspace": self.cam_w,
                    "cam_wrist": self.cam_r,
                    "pose": {k: round(v, 2) for k, v in pose.items()},
                    "grip_state": classify_grip(pose.get("gripper", 50.0), self.last_close),
                    "t": time.strftime("%H:%M:%S"),
                }
            )
        )

    def reply(self, cmd_id: str, **kw):
        rec = {"id": cmd_id, "ok": kw.pop("ok", True), **kw}
        rec["pose"] = {k: round(v, 2) for k, v in joints_of(self.robot).items()}
        REPLY.write_text(json.dumps(rec, default=str))
        _out(rec)

    def require_cams(self, op: str) -> bool:
        if self.cams_ok or self.allow_unprobed:
            return True
        return False

    def hold_torque(self):
        if self.robot is None:
            return
        try:
            self.robot.send_action({f"{k}.pos": v for k, v in self.hold.items()})
        except ConnectionError as exc:
            print(f"hold_torque serial blip: {exc}", flush=True)

    def move_to(self, target: dict, seconds: float = 2.0):
        tgt = dict(self.hold)
        tgt.update(target)
        if self.dry:
            self.robot.send_action({f"{k}.pos": v for k, v in tgt.items()})
            self.hold = dict(tgt)
            return
        arr = [tgt[n] for n in JOINTS]
        self.arm.move_joints(self.robot, arr, seconds=seconds, gripper=tgt["gripper"])
        # Hold the command, not the measured pose — gravity droop otherwise compounds.
        self.hold = dict(tgt)

    def ee_ok(self, target: dict) -> str | None:
        if self.dry or self.kin is None or self.arm is None:
            return None
        arr = [target[n] for n in JOINTS]
        xyz = self.kin.forward_kinematics(arr)[:3, 3]
        if not ((self.arm.EE_MIN <= xyz) & (xyz <= self.arm.EE_MAX)).all():
            return f"REFUSED: FK {xyz.tolist()} outside EE box"
        return None

    def snap(self, which: str) -> dict:
        which = which or "both"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        files = {}
        want = ("workspace", "wrist") if which == "both" else (which,)
        for name in want:
            idx = self.cam_w if name == "workspace" else self.cam_r
            latest = DEBUG / f"desk_{name}.jpg"
            hist = SNAP_DIR / f"{stamp}_{name}.jpg"
            if self.dry:
                import numpy as np

                try:
                    import cv2
                except ImportError:
                    latest.write_bytes(b"")
                    files[name] = str(latest)
                    continue
                img = np.full((480, 640, 3), 80 if name == "wrist" else 160, np.uint8)
                cv2.imwrite(str(latest), img)
                cv2.imwrite(str(hist), img)
            else:
                import shutil
                import subprocess

                cap = HERE / "capture.py"
                try:
                    subprocess.run(
                        [sys.executable, str(cap), str(idx), str(latest)],
                        check=True,
                        timeout=8,
                    )
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                    files[f"{name}_error"] = f"grab failed: {exc}"
                    continue
                if latest.exists():
                    shutil.copy(latest, hist)
            files[name] = str(latest)
            files[f"{name}_hist"] = str(hist)
        return files

    def probe_cams(self) -> dict:
        files = self.snap("both")
        self.cams_ok = True
        return {
            "files": files,
            "cam_workspace": self.cam_w,
            "cam_wrist": self.cam_r,
            "note": "confirm C922=workspace, Innomaker=wrist before any motion",
        }

    def handle(self, cmd: dict):
        op = cmd.get("op")
        cid = cmd.get("id", "")
        try:
            if op == "stop":
                self.reply(cid, op=op)
                self._stopping = True
                return
            if op == "status":
                self.write_status()
                self.reply(cid, op=op, status=json.loads(STATUS.read_text()))
                return
            if op == "pose":
                self.reply(cid, op=op)
                return
            if op == "snap":
                files = self.snap(cmd.get("which", "both"))
                self.reply(cid, op=op, files=files)
                return
            if op == "cams":
                self.reply(cid, op=op, **self.probe_cams())
                return
            if op == "grip-state":
                g = joints_of(self.robot)["gripper"]
                self.reply(
                    cid,
                    op=op,
                    gripper=round(g, 2),
                    state=classify_grip(g, self.last_close),
                    last_close=self.last_close,
                )
                return
            if op == "save":
                name = cmd.get("name")
                if not name:
                    raise ValueError("save needs name")
                self.poses[name] = joints_of(self.robot)
                save_poses(self.poses)
                self.reply(cid, op=op, name=name, saved=self.poses[name])
                return
            if op in ("delta", "goto", "grip") and not self.require_cams(op):
                self.reply(
                    cid,
                    ok=False,
                    op=op,
                    error="cams not probed this serve. Run: python desk.py cams",
                )
                return
            if op == "grip":
                val = max(0.0, min(100.0, float(cmd["value"])))
                if val < GRIP_OPEN:
                    self.last_close = val
                self.move_to({"gripper": val}, seconds=1.2)
                g = joints_of(self.robot)["gripper"]
                self.reply(cid, op=op, gripper=round(g, 2), state=classify_grip(g, self.last_close))
                return
            if op == "delta":
                d = clamp_delta(cmd.get("joints") or {})
                cur = joints_of(self.robot)
                tgt = dict(cur)
                for name, val in d.items():
                    if name == "gripper":
                        tgt[name] = val
                        if val < GRIP_OPEN:
                            self.last_close = val
                    else:
                        tgt[name] = cur[name] + val
                err = self.ee_ok(tgt)
                if err:
                    self.reply(cid, ok=False, op=op, error=err)
                    return
                self.move_to(tgt, seconds=1.2)
                self.reply(cid, op=op, applied=d)
                return
            if op == "goto":
                name = cmd.get("name")
                if name:
                    if name not in self.poses:
                        self.reply(
                            cid,
                            ok=False,
                            op=op,
                            error=f"unknown pose {name}. Known: {list(self.poses)}",
                        )
                        return
                    tgt = dict(self.hold)
                    tgt.update(self.poses[name])
                else:
                    tgt = dict(self.hold)
                    tgt.update(cmd.get("joints") or {})
                err = self.ee_ok(tgt)
                if err:
                    self.reply(cid, ok=False, op=op, error=err)
                    return
                self.move_to(tgt, seconds=float(cmd.get("seconds", 2.5)))
                self.reply(cid, op=op, name=name)
                return
            self.reply(cid, ok=False, error=f"unknown op {op}")
        except Exception as exc:
            self.reply(cid, ok=False, op=op, error=str(exc))

    def poll(self):
        size = CMDS.stat().st_size
        if size < self.cmd_offset:
            self.cmd_offset = 0
        if size <= self.cmd_offset:
            return
        with open(CMDS) as f:
            f.seek(self.cmd_offset)
            new = f.read()
        self.cmd_offset = size
        for line in new.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.handle(cmd)
            if self._stopping:
                return

    def loop(self):
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
        print(f"desk serve ready pid={os.getpid()} dry={self.dry}", flush=True)
        last_status = 0.0
        try:
            while not self._stopping:
                self.poll()
                now = time.time()
                if now - last_status > 0.5:
                    self.write_status()
                    last_status = now
                self.hold_torque()
                time.sleep(0.05)
        finally:
            if self.robot is not None and not self.dry:
                self.robot.disconnect()
            if PID_PATH.exists():
                PID_PATH.unlink()
            print("desk serve stopped (torque off if live)", flush=True)


def cmd_serve(args):
    if serve_alive():
        _out({"ok": False, "error": f"serve already running pid={PID_PATH.read_text().strip()}"})
        sys.exit(1)
    srv = DeskServe(dry=args.dry, allow_unprobed=args.allow_unprobed)
    srv.start()
    srv.loop()


def parse_delta(pairs: list[str]) -> dict:
    joints = {}
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"delta item must be joint=value, got {item!r}")
        k, v = item.split("=", 1)
        k = k.strip()
        if k not in JOINTS:
            raise SystemExit(f"unknown joint {k}. {JOINTS}")
        joints[k] = float(v)
    return joints


def parse_goto_joints(text: str) -> dict:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 6:
        raise SystemExit("goto joints need 6 comma-separated numbers in motor order")
    return {n: float(p) for n, p in zip(JOINTS, parts)}


def cmd_client(op: str, extra: dict):
    rec = send_cmd({"op": op, **extra})
    _out(rec)
    if not rec.get("ok", False):
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="connect once and hold torque")
    p_serve.add_argument("--dry", action="store_true", help="no serial")
    p_serve.add_argument("--allow-unprobed", action="store_true", help="allow motion before cams")

    sub.add_parser("pose")
    sub.add_parser("status")
    sub.add_parser("stop")
    sub.add_parser("grip-state")
    sub.add_parser("cams")

    p_snap = sub.add_parser("snap")
    p_snap.add_argument("which", nargs="?", default="both", choices=["workspace", "wrist", "both"])

    p_delta = sub.add_parser("delta")
    p_delta.add_argument("pairs", nargs="+", help="joint=value (gripper absolute, others relative)")

    p_goto = sub.add_parser("goto")
    p_goto.add_argument("target", help="named pose or 6 comma-separated joint degrees")
    p_goto.add_argument("--seconds", type=float, default=2.5)

    p_grip = sub.add_parser("grip")
    p_grip.add_argument("value", type=float)

    p_save = sub.add_parser("save")
    p_save.add_argument("name")

    args = ap.parse_args()
    if args.cmd == "serve":
        cmd_serve(args)
        return
    if args.cmd == "delta":
        cmd_client("delta", {"joints": parse_delta(args.pairs)})
        return
    if args.cmd == "goto":
        extra = {"seconds": args.seconds}
        if "," in args.target:
            extra["joints"] = parse_goto_joints(args.target)
        else:
            extra["name"] = args.target
        cmd_client("goto", extra)
        return
    if args.cmd == "grip":
        cmd_client("grip", {"value": args.value})
        return
    if args.cmd == "snap":
        cmd_client("snap", {"which": args.which})
        return
    if args.cmd == "save":
        cmd_client("save", {"name": args.name})
        return
    cmd_client(args.cmd, {})


if __name__ == "__main__":
    main()
