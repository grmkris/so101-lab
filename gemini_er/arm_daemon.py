"""Persistent MolmoAct2 arm daemon (v2): one long-lived RobotClient — cameras and
robot connect ONCE, episodes start/stop/steer in ~a second via a file command
queue, and episodes END on proprioceptive triggers (grasp-release / stall /
budget), not raw wall-clock.

Run (LeLab env):  SERVER=100.x.y.z:8081 ~/.local/share/uv/tools/lelab/bin/python arm_daemon.py
Commands (append JSON lines to debug/arm_cmds.jsonl):
  {"cmd": "run",   "task": "pick up the white cube", "budget": 45}
  {"cmd": "steer", "task": "put the white cube in the plastic box"}
  {"cmd": "stop"}          {"cmd": "park"}          {"cmd": "quit"}
Status: debug/arm_status.json (state, task, gripper, end_reason, obs age).
Episode log: debug/arm_episodes.jsonl
"""

import json
import os
import threading
import time
from pathlib import Path
from queue import Queue

from lerobot.async_inference.configs import RobotClientConfig
from lerobot.async_inference.robot_client import RobotClient
from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
from lerobot.transport import services_pb2

DEBUG = Path(__file__).resolve().parent / "debug"
CMDS = DEBUG / "arm_cmds.jsonl"
STATUS = DEBUG / "arm_status.json"
EPISODES = DEBUG / "arm_episodes.jsonl"

PORT = "/dev/tty.usbmodem5AE60832001"
SERVER = os.environ["SERVER"]
CAM0_IDX = int(os.environ.get("CAM0_IDX", "0"))
CAM1_IDX = int(os.environ.get("CAM1_IDX", "1"))
FPS = int(os.environ.get("FPS", "15"))

# checkpoint's ready pose = idle pose = every episode starts in-distribution
READY = {"shoulder_pan.pos": 3.3, "shoulder_lift.pos": -34.3, "elbow_flex.pos": 31.4,
         "wrist_flex.pos": 56.0, "wrist_roll.pos": -11.5, "gripper.pos": 50.0}

GRIP_CLOSED = 35.0   # below = closing/holding zone (empty-close reads ~1, held ~7-22)
GRIP_OPEN = 45.0
STATION_EPS = 1.5    # deg; max joint delta considered stationary
DEFAULT_BUDGET = 45.0


def log_episode(rec):
    with open(EPISODES, "a") as f:
        f.write(json.dumps(rec) + "\n")


def build_client():
    if os.environ.get("SCENE_ONLY", "0") == "1":
        # wrist cam is OOD per community findings AND our Innomaker keeps dying
        # under sustained streaming: feed the scene camera into both keys
        cams = {
            "cam0": OpenCVCameraConfig(index_or_path=CAM0_IDX, width=320,
                                       height=240, fps=30, warmup_s=4),
            "cam1": OpenCVCameraConfig(index_or_path=CAM0_IDX, width=320,
                                       height=240, fps=30, warmup_s=4),
        }
    else:
        cams = {
            "cam0": OpenCVCameraConfig(index_or_path=CAM0_IDX, width=320,
                                       height=240, fps=30, warmup_s=4),
            "cam1": OpenCVCameraConfig(index_or_path=CAM1_IDX, width=640,
                                       height=480, fps=30, warmup_s=6),
        }
    robot_cfg = SO101FollowerConfig(port=PORT, id="arm", max_relative_target=15.0,
                                    cameras=cams, use_degrees=True)
    cfg = RobotClientConfig(
        policy_type="molmoact2",
        pretrained_name_or_path="/content/molmoact2_so101",
        robot=robot_cfg,
        actions_per_chunk=30,
        task="",
        server_address=SERVER,
        policy_device="cuda",
        client_device="cpu",
        chunk_size_threshold=0.6,
        fps=FPS,
        aggregate_fn_name="latest_only",
    )
    return RobotClient(cfg)


class Daemon:
    def __init__(self):
        self.client = build_client()
        # loud failure if a lerobot bump moves the private seams we touch
        for attr in ("start_barrier", "action_queue", "action_queue_lock",
                     "must_go", "stub", "robot", "control_loop_observation",
                     "control_loop_action"):
            assert hasattr(self.client, attr), f"lerobot seam moved: {attr}"
        self.state = "IDLE"
        self.task = ""
        self.budget = DEFAULT_BUDGET
        self.ep_start = 0.0
        self.end_reason = ""
        self.last_obs_t = time.time()
        self.cmd_offset = 0
        # termination tracking
        self.joint_hist = []      # (t, [joints])
        self.grip_hist = []       # (t, grip)
        self.was_closed_at = 0.0

    # ---------- lifecycle ----------
    def start(self):
        c = self.client
        c.start()
        threading.Thread(target=c.receive_actions, daemon=True).start()
        c.start_barrier.wait()
        CMDS.touch()
        self.cmd_offset = CMDS.stat().st_size
        self.park()
        print("daemon ready: IDLE at ready pose")

    def drain(self):
        with self.client.action_queue_lock:
            self.client.action_queue = Queue()

    def park(self):
        self.drain()
        for _ in range(int(4.0 * FPS)):  # clamp-limited ramp to ready pose
            self.client.robot.send_action(dict(READY))
            time.sleep(1.0 / FPS)

    def begin(self, task, budget):
        self.drain()
        self.client.stub.Ready(services_pb2.Empty())  # server reset, no reload
        self.client.must_go.set()
        self.task = task
        self.budget = float(budget or DEFAULT_BUDGET)
        self.ep_start = time.time()
        self.joint_hist, self.grip_hist, self.was_closed_at = [], [], 0.0
        self.end_reason = ""
        self.state = "RUNNING"
        print(f"episode start: {task!r} budget {self.budget}s")

    def steer(self, task):
        if self.state != "RUNNING":
            return
        self.drain()
        self.client.must_go.set()
        self.task = task
        print(f"steered: {task!r}")

    def end(self, reason):
        self.state = "IDLE"
        self.end_reason = reason
        dur = round(time.time() - self.ep_start, 1)
        time.sleep(1.2)  # let a late chunk land, then discard it
        self.drain()
        log_episode({"t": time.strftime("%H:%M:%S"), "task": self.task,
                     "end_reason": reason, "duration_s": dur})
        print(f"episode end: {reason} after {dur}s")

    # ---------- termination triggers ----------
    def check_triggers(self, obs):
        now = time.time()
        joints = [float(obs.get(f"{m}.pos", 0.0)) for m in
                  ("shoulder_pan", "shoulder_lift", "elbow_flex",
                   "wrist_flex", "wrist_roll")]
        grip = float(obs.get("gripper.pos", 50.0))
        self.joint_hist.append((now, joints))
        self.grip_hist.append((now, grip))
        self.joint_hist = [(t, j) for t, j in self.joint_hist if now - t <= 6.0]
        self.grip_hist = [(t, g) for t, g in self.grip_hist if now - t <= 6.0]

        if grip < GRIP_CLOSED:
            self.was_closed_at = now

        def stationary_for(secs):
            pts = [(t, j) for t, j in self.joint_hist if now - t <= secs]
            if len(pts) < max(3, int(secs * FPS * 0.5)) or now - pts[0][0] < secs * 0.8:
                return False
            ref = pts[0][1]
            return all(max(abs(a - b) for a, b in zip(j, ref)) < STATION_EPS
                       for _, j in pts)

        # success: gripper opened after having been closed, then arm settled
        if (self.was_closed_at and grip > GRIP_OPEN
                and now - self.was_closed_at > 1.0 and stationary_for(1.0)):
            return "success_release"
        # stall: long stationarity without any grasp-state change
        recent_grips = [g for t, g in self.grip_hist if now - t <= 5.0]
        grip_static = recent_grips and max(recent_grips) - min(recent_grips) < 3.0
        if stationary_for(5.0) and grip_static and now - self.ep_start > 8.0:
            return "stall"
        if now - self.ep_start > self.budget:
            return "budget"
        return None

    # ---------- command + status plumbing ----------
    def poll_commands(self):
        size = CMDS.stat().st_size
        if size <= self.cmd_offset:
            return None
        with open(CMDS) as f:
            f.seek(self.cmd_offset)
            new = f.read()
        self.cmd_offset = size
        for line in new.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            cmd = c.get("cmd")
            if cmd == "run":
                if self.state == "RUNNING":
                    self.end("preempted")
                self.begin(c.get("task", ""), c.get("budget"))
            elif cmd == "steer":
                self.steer(c.get("task", ""))
            elif cmd == "stop" and self.state == "RUNNING":
                self.end("stopped")
            elif cmd == "park":
                if self.state == "RUNNING":
                    self.end("stopped")
                self.park()
            elif cmd == "quit":
                return "quit"
        return None

    def write_status(self):
        grip = self.grip_hist[-1][1] if self.grip_hist else None
        STATUS.write_text(json.dumps({
            "state": self.state, "task": self.task,
            "end_reason": self.end_reason,
            "episode_s": round(time.time() - self.ep_start, 1) if self.state == "RUNNING" else 0,
            "gripper": grip,
            "obs_age_s": round(time.time() - self.last_obs_t, 1),
            "t": time.strftime("%H:%M:%S"),
        }))

    # ---------- main loop ----------
    def loop(self):
        dt = 1.0 / FPS
        last_status = 0.0
        obs_fail_streak = 0
        while True:
            t0 = time.perf_counter()
            if self.poll_commands() == "quit":
                break
            if self.state == "RUNNING":
                obs = None
                try:
                    obs = self.client.control_loop_observation(self.task)
                except Exception as e:
                    print(f"obs error: {e}")
                if obs:
                    self.last_obs_t = time.time()
                    obs_fail_streak = 0
                    trigger = self.check_triggers(obs)
                    if trigger:
                        self.end(trigger)
                else:
                    obs_fail_streak += 1
                    if obs_fail_streak > 3 * FPS:  # ~3s of no observations
                        self.end("camera_failure")
                        obs_fail_streak = 0
                if self.state == "RUNNING":
                    try:
                        self.client.control_loop_action()
                    except Exception:
                        pass  # empty queue etc.
            if time.time() - last_status > 0.5:
                self.write_status()
                last_status = time.time()
            elapsed = time.perf_counter() - t0
            if elapsed < dt:
                time.sleep(dt - elapsed)

    def shutdown(self):
        if self.state == "RUNNING":
            self.end("shutdown")
        try:
            self.client.stop()
        except Exception:
            pass


def main():
    DEBUG.mkdir(exist_ok=True)
    d = Daemon()
    try:
        d.start()
        d.loop()
    finally:
        d.shutdown()
        print("daemon stopped, torque released")


if __name__ == "__main__":
    main()
