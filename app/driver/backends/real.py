"""Real backend — serial SO-101 arms + OpenCV cameras via lerobot 0.6.0.
Connect/teleop structure cribbed from LeLab's teleoperate.py (worker owns disconnect).
"""

import threading
import time

from shared import emit, log


class RealBackend:
    name = "real"

    def __init__(self) -> None:
        self.robot = None
        self.teleop = None
        self.state = "disconnected"
        self.teleop_active = False
        self.joints: dict[str, float] = {}
        self._ports: dict = {}

    # ---------- lifecycle ----------

    def _emit_state(self) -> None:
        emit({"event": "robot_state", "state": self.state, "backend": self.name})

    @staticmethod
    def _safe_disconnect(device) -> None:
        if device is None:
            return
        try:
            device.disconnect()
        except Exception as exc:  # noqa: BLE001
            log(f"disconnect error (ignored): {exc}")

    def connect(self, req: dict) -> dict:
        if self.state != "disconnected":
            raise ValueError(f"already {self.state} — disconnect first")

        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
        from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

        robot_id = req.get("robotId", "arm")
        self._ports = {
            "followerPort": req["followerPort"],
            "leaderPort": req.get("leaderPort"),
            "robotId": robot_id,
        }
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

            self.robot, self.teleop, self.state = robot, teleop, "connected"
            self._emit_state()
            return {"state": self.state, "leader": teleop is not None}
        except Exception:
            self._safe_disconnect(robot)
            self._safe_disconnect(teleop)
            self.robot = self.teleop = None
            self.state = "disconnected"
            raise

    def disconnect(self) -> dict:
        self.teleop_active = False
        time.sleep(0.1)
        self._safe_disconnect(self.robot)
        self._safe_disconnect(self.teleop)
        self.robot = self.teleop = None
        self.state = "disconnected"
        self.joints.clear()
        self._emit_state()
        return {"state": "disconnected"}

    # ---------- control ----------

    def torque(self, on: bool) -> dict:
        if self.robot is None:
            raise ValueError("not connected")
        if on:
            self.robot.bus.enable_torque()
        else:
            self.robot.bus.disable_torque()
        return {"torque": on}

    def estop(self) -> dict:
        """Torque kill. Arm goes limp — hold it if it's raised."""
        self.teleop_active = False
        if self.robot is not None:
            try:
                self.robot.bus.disable_torque()
            except Exception as exc:  # noqa: BLE001
                log(f"estop disable_torque error: {exc}")
        self.state = "connected" if self.robot is not None else "disconnected"
        self._emit_state()
        return {"estopped": True}

    def _read_joints(self) -> dict[str, float]:
        obs = self.robot.get_observation()
        return {
            k.removesuffix(".pos"): round(float(v), 2)
            for k, v in obs.items()
            if k.endswith(".pos")
        }

    def get_joints(self) -> dict:
        if self.robot is None:
            raise ValueError("not connected")
        return self._read_joints()

    def _teleop_worker(self) -> None:
        last_emit = 0.0
        try:
            while self.teleop_active:
                action = self.teleop.get_action()
                self.robot.send_action(action)
                now = time.time()
                if now - last_emit >= 0.1:
                    self.joints.update(self._read_joints())
                    emit({"event": "joints", "values": dict(self.joints)})
                    last_emit = now
                time.sleep(0.001)
        except Exception as exc:  # noqa: BLE001
            log(f"teleop loop error: {exc}")
            emit({"event": "error", "where": "teleop", "error": str(exc)})
        finally:
            self.teleop_active = False
            self.state = "connected"
            self._emit_state()

    def teleop_start(self) -> dict:
        if self.robot is None or self.teleop is None:
            raise ValueError("connect with a leader arm first")
        if self.teleop_active:
            raise ValueError("teleop already active")
        self.teleop_active = True
        self.state = "teleop"
        threading.Thread(target=self._teleop_worker, name="teleop-worker", daemon=True).start()
        self._emit_state()
        return {"state": "teleop"}

    def teleop_stop(self) -> dict:
        self.teleop_active = False
        return {"state": "connected"}

    # ---------- record ----------

    def prepare_record(self, cfg: dict):
        """Release held devices, build FRESH lerobot objects with cameras for the recorder.

        Recording requires the leader arm (actions come from it).
        Returns (robot, teleop, on_episode_start).
        """
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
        from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

        if not self._ports.get("leaderPort"):
            raise ValueError("recording needs the leader arm — reconnect with leader")

        # recorder owns the serial ports + cameras from here
        self.teleop_active = False
        time.sleep(0.1)
        self._safe_disconnect(self.robot)
        self._safe_disconnect(self.teleop)
        self.robot = self.teleop = None
        self.state = "recording"
        self._emit_state()

        cameras = {
            name: OpenCVCameraConfig(
                index_or_path=cam["index"],
                width=cam.get("width", 640),
                height=cam.get("height", 480),
                fps=cam.get("fps", 30),
            )
            for name, cam in (cfg.get("cameras") or {}).items()
        }
        robot = SO101Follower(
            SO101FollowerConfig(
                port=self._ports["followerPort"], id=self._ports["robotId"], cameras=cameras
            )
        )
        teleop = SO101Leader(
            SO101LeaderConfig(port=self._ports["leaderPort"], id=self._ports["robotId"])
        )
        return robot, teleop, None

    def after_record(self) -> None:
        # recorder disconnected the devices it owned; back to square one
        self.robot = self.teleop = None
        self.state = "disconnected"
        self.joints.clear()
        self._emit_state()
