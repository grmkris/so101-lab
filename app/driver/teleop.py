"""Unified teleop: any source × any backend.

Owns the source registry and the single teleop loop
(`source.get_action() -> backend.apply_action()`); driver.py just dispatches
protocol commands here. Sources are lerobot Teleoperator subclasses, so the
same objects also serve record sessions.
"""

import threading
import time
from pathlib import Path

from shared import emit, log

URDF_PATH = str(
    (Path(__file__).parent.parent.parent / "phone_teleop/SO101/so101_new_calib.urdf").resolve()
)

_state: dict = {"active": False, "source": None, "name": None, "thread": None}


def is_active() -> bool:
    return bool(_state["active"])


def make_source(name: str, backend):
    if name == "leader":
        if backend.name != "real":
            raise ValueError("leader source needs the real backend")
        if backend.teleop is None:
            raise ValueError("connect with the leader arm first")
        return backend.teleop
    if name == "scripted":
        if backend.name != "sim":
            raise ValueError("scripted source is sim-only")
        from backends.sim import KEYFRAMES
        from sources.scripted import ScriptedExpert

        expert = ScriptedExpert(backend, KEYFRAMES)
        expert.reset()
        return expert
    if name == "keys":
        from sources.keys import BrowserKeys

        return BrowserKeys(
            urdf_path=URDF_PATH,
            motor_names=backend.lerobot_joint_names,
            seed_obs=backend.current_joints_pos(),
        )
    raise ValueError(f"unknown teleop source: {name}")


def _emit_state(backend, state: str) -> None:
    emit({
        "event": "robot_state",
        "state": state,
        "backend": backend.name,
        "source": _state["name"] if state == "teleop" else None,
    })


def _loop(source, backend, rate_hz: int) -> None:
    last_emit = 0.0
    try:
        while _state["active"]:
            action = source.get_action()
            backend.apply_action(action)
            now = time.time()
            if now - last_emit >= 0.1:
                emit({"event": "joints", "values": backend.get_joints()})
                last_emit = now
            time.sleep(1 / rate_hz)
    except Exception as exc:  # noqa: BLE001
        log(f"teleop loop error: {exc}")
        emit({"event": "error", "where": "teleop", "error": str(exc)})
    finally:
        _state.update(active=False, source=None, name=None)
        if hasattr(backend, "teleop_done"):
            backend.teleop_done()
        backend.state = "connected"
        _emit_state(backend, "connected")


def start(req: dict, backend, recording_active: bool) -> dict:
    if _state["active"]:
        raise ValueError("teleop already active")
    if recording_active:
        raise ValueError("recording is active")

    name = req.get("source") or ("scripted" if backend.name == "sim" else "leader")
    backend.teleop_ready(name)
    try:
        source = make_source(name, backend)
    except Exception:
        if hasattr(backend, "teleop_done"):
            backend.teleop_done()  # e.g. release the synthetic clamp on the real arm
        raise

    thread = threading.Thread(
        target=_loop,
        args=(source, backend, 60 if name == "leader" else 30),
        name="teleop-loop",
        daemon=True,
    )
    _state.update(active=True, source=source, name=name, thread=thread)
    backend.state = "teleop"
    thread.start()
    _emit_state(backend, "teleop")
    return {"state": "teleop", "source": name}


def stop(wait: bool = False) -> dict:
    _state["active"] = False
    thread = _state.get("thread")
    if wait and thread is not None and thread.is_alive():
        thread.join(timeout=2)
    return {"state": "connected"}


def set_input(req: dict) -> dict:
    source = _state.get("source")
    if source is None or not hasattr(source, "set_input"):
        raise ValueError("no input-driven teleop source active")
    source.set_input(req.get("axes") or {})
    return {"ok": True}
