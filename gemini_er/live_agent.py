"""ER 2 streaming orchestrator v2: supervises the persistent arm_daemon.

Stack: arm_daemon.py owns the robot + policy stream (instant episodes,
proprioceptive termination, live steering). This agent owns judgment: it
watches the workspace camera, commissions episodes (run_task), steers them
(steer_task), and verifies outcomes from pixels.

Session hygiene (per research): event-driven heartbeat with a 10s safety
timer (un-sticks server-side inference stalls), TaskGroup (no leaked
readers across reconnects), ping 10/10 (fast dead-socket detection),
resumption + sliding-window compression, mission resend after reconnect.

Run (driver venv, from gemini_er/):
  GEMINI_API_KEY=... python live_agent.py
Commands: append lines to debug/live_cmds.txt (stdin also works in a tty).
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
from google import genai
from google.genai import types

from capture import grab
from cycle import DEBUG, load

MODEL = "gemini-robotics-er-2-streaming-preview"
LOG = DEBUG / "live_agent.jsonl"
CMD_FILE = DEBUG / "live_cmds.txt"
ARM_CMDS = DEBUG / "arm_cmds.jsonl"
ARM_STATUS = DEBUG / "arm_status.json"
ARM_EPISODES = DEBUG / "arm_episodes.jsonl"

calib = load()
CAM = calib["camera_index"]

arm_lock = threading.Lock()   # serializes physical tools; survives session churn
resume_handle = None
pending_cmd = None            # active mission; resent after reconnects until reset

# heartbeat machinery (event-driven, per Google's session_manager)
hb_signal: asyncio.Event | None = None
hb_last = 0.0
turn_in_flight = False
turn_had_tool = False


def log(kind, **kw):
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "kind": kind, **kw}) + "\n")


def speak(text):
    subprocess.Popen(["say", text[:300]])


def arm_cmd(payload):
    with open(ARM_CMDS, "a") as f:
        f.write(json.dumps(payload) + "\n")


def episodes_count():
    try:
        return sum(1 for _ in open(ARM_EPISODES))
    except FileNotFoundError:
        return 0


def arm_state():
    try:
        return json.loads(ARM_STATUS.read_text())
    except Exception:
        return {}


# ---------------- tools (sync, run in worker threads) ----------------

def tool_run_task(args):
    if not arm_lock.acquire(blocking=False):
        return {"error": "arm BUSY - wait for the previous action's result"}
    try:
        st = arm_state()
        if not st or time.time() - time.mktime(time.strptime(
                time.strftime("%Y-%m-%d ") + st.get("t", "00:00:00"),
                "%Y-%m-%d %H:%M:%S")) > 10:
            return {"error": "arm daemon is not running or stale - tell the user"}
        task = str(args.get("instruction", ""))[:120]
        budget = min(max(int(args.get("budget", 45)), 20), 90)
        n0 = episodes_count()
        speak(f"Arm task: {task}")
        arm_cmd({"cmd": "run", "task": task, "budget": budget})
        log("run_task", task=task, budget=budget)
        deadline = time.time() + budget + 25
        while time.time() < deadline:
            if episodes_count() > n0:
                rec = list(open(ARM_EPISODES))[-1].strip()
                ep = json.loads(rec)
                return {"end_reason": ep.get("end_reason"),
                        "duration_s": ep.get("duration_s"),
                        "outcome": "unverified",
                        "instruction": "The episode ended with the given "
                                       "end_reason. Inspect the NEXT camera "
                                       "frames and judge from pixels whether "
                                       "the task succeeded. success_release "
                                       "means the arm grasped and released "
                                       "something - verify WHERE it released. "
                                       "Do not assume success."}
            time.sleep(1.0)
        return {"error": "episode did not report an end - daemon may be stuck"}
    finally:
        arm_lock.release()


def tool_steer_task(args):
    task = str(args.get("instruction", ""))[:120]
    arm_cmd({"cmd": "steer", "task": task})
    log("steer", task=task)
    return {"status": "instruction updated on the running episode",
            "note": "takes effect within ~2 seconds; keep observing"}


def tool_stop_arm(args):
    arm_cmd({"cmd": "stop"})
    log("stop_arm", reason=str(args.get("reason", ""))[:100])
    time.sleep(2.0)
    return {"status": "arm stopped and holding"}


def tool_home(args):
    if not arm_lock.acquire(blocking=False):
        return {"error": "arm BUSY"}
    try:
        arm_cmd({"cmd": "park"})
        time.sleep(5.0)
        return {"outcome": "arm parked at ready pose"}
    finally:
        arm_lock.release()


def tool_arm_status(args):
    return arm_state() or {"error": "no status - daemon down?"}


TOOLS = [{"function_declarations": [
    {"name": "run_task", "behavior": "BLOCKING",
     "description": "Run the manipulation policy for ONE episode with a "
                    "whole-task instruction (e.g. 'pick up the white cube and "
                    "place it in the plastic box'). Blocks until the episode "
                    "ends (proprioceptive trigger, stall, or budget). The arm "
                    "moves slowly; a pick-and-place usually needs budget 45-90.",
     "parameters": {"type": "OBJECT", "properties": {
         "instruction": {"type": "STRING"},
         "budget": {"type": "INTEGER", "description": "seconds, 20-90, default 45"}},
         "required": ["instruction"]}},
    {"name": "steer_task", "behavior": "BLOCKING",
     "description": "Change the instruction of the CURRENTLY RUNNING episode "
                    "without stopping the arm - e.g. after it grasps the "
                    "object, steer from 'pick up the white cube' to 'put the "
                    "white cube in the plastic box'. Use WHOLE-task phrasings, "
                    "never fragments like 'move left'.",
     "parameters": {"type": "OBJECT", "properties": {
         "instruction": {"type": "STRING"}}, "required": ["instruction"]}},
    {"name": "stop_arm", "behavior": "BLOCKING",
     "description": "Immediately stop the running episode. Use when the task "
                    "is visibly complete or something is going wrong.",
     "parameters": {"type": "OBJECT", "properties": {
         "reason": {"type": "STRING"}}, "required": []}},
    {"name": "home", "behavior": "BLOCKING",
     "description": "Park the arm at its safe ready pose.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "arm_status", "behavior": "BLOCKING",
     "description": "Read the arm daemon's state (IDLE/RUNNING, task, gripper "
                    "position, last episode end reason).",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "ack", "behavior": "BLOCKING",
     "description": "Acknowledge: scene nominal or step still in progress.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "reset", "behavior": "BLOCKING",
     "description": "Mission finished; report the outcome and go idle.",
     "parameters": {"type": "OBJECT", "properties": {}}},
]}]

FNS = {"run_task": tool_run_task, "steer_task": tool_steer_task,
       "stop_arm": tool_stop_arm, "home": tool_home,
       "arm_status": tool_arm_status,
       "ack": lambda a: {"ok": True}, "reset": lambda a: {"ok": True}}

HEARTBEAT = ("[HEARTBEAT] If no task is active, call 'ack' and wait for user "
             "input. If a task is active: observe the scene. If progressing, "
             "call 'ack'. If the current step is complete, proceed with the "
             "next step. If the overall goal is achieved, call 'reset' and "
             "tell the user.")

SYSTEM = ("You orchestrate a SO-101 robot arm over a live camera feed "
          "(front view: black mat, white cube, plastic box). You cannot move "
          "joints directly - use tools. Prefer ONE run_task with a full "
          "instruction, steer_task after a grasp if the goal has stages, and "
          "verify every outcome from camera frames before claiming success; "
          "tool results are diagnostics, not proof. Judge success only when "
          "the object is visibly in its goal location with the gripper clear. "
          "Keep spoken responses to one or two short sentences.")


def make_config():
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        tools=TOOLS,
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM)]),
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


def jpeg_frame():
    frame = grab(CAM, 640, 480, 5)
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpg.tobytes() if ok else None


async def heartbeat_loop(session):
    """Event-driven: fire on turn-complete signal, or after 10s of silence
    (the safety heartbeat that un-sticks server-side stalls)."""
    global hb_last, turn_in_flight
    while True:
        try:
            await asyncio.wait_for(hb_signal.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass  # safety heartbeat - recovers stalled turns
        hb_signal.clear()
        if arm_lock.locked():
            continue  # suppressed while a physical tool runs
        if time.monotonic() - hb_last < 0.5:
            continue
        try:
            jpg = await asyncio.to_thread(jpeg_frame)
            if jpg:
                await session.send_realtime_input(
                    video=types.Blob(data=jpg, mime_type="image/jpeg"))
        except Exception as e:
            log("camera_error", err=str(e)[:150])
        hb_last = time.monotonic()
        turn_in_flight = True
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=HEARTBEAT)]),
            turn_complete=True)


async def user_commands(session):
    CMD_FILE.touch()
    offset = CMD_FILE.stat().st_size
    stdin_ok = sys.stdin.isatty()
    if stdin_ok:
        print(f"type a command, or: echo 'cmd' >> {CMD_FILE}", flush=True)

    async def send(cmd):
        global pending_cmd, turn_in_flight
        pending_cmd = cmd
        turn_in_flight = True
        log("user", text=cmd)
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=cmd)]),
            turn_complete=True)

    while True:
        if stdin_ok:
            import select
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                cmd = sys.stdin.readline().strip()
                if cmd:
                    await send(cmd)
        size = CMD_FILE.stat().st_size
        if size > offset:
            with open(CMD_FILE) as f:
                f.seek(offset)
                new = f.read()
            offset = size
            for line in new.splitlines():
                if line.strip():
                    await send(line.strip())
        await asyncio.sleep(1.0)


async def receive(session):
    global resume_handle, pending_cmd, turn_in_flight, turn_had_tool
    async for msg in session.receive():
        if msg.session_resumption_update and msg.session_resumption_update.resumable:
            resume_handle = msg.session_resumption_update.new_handle
        if msg.go_away:
            log("go_away", time_left=str(msg.go_away.time_left))
        if msg.server_content:
            sc = msg.server_content
            if sc.model_turn:
                for p in sc.model_turn.parts:
                    if p.text:
                        print(f"MODEL: {p.text}", flush=True)
                        log("model", text=p.text)
                        speak(p.text)
            if sc.turn_complete:
                turn_in_flight = False
                if turn_had_tool:
                    turn_had_tool = False  # tool response re-triggers; no hb
                else:
                    hb_signal.set()
        if msg.tool_call:
            turn_had_tool = True
            if any(fc.name == "reset" for fc in msg.tool_call.function_calls):
                pending_cmd = None
            responses = []
            for fc in msg.tool_call.function_calls:
                log("tool_call", name=fc.name, args=dict(fc.args or {}))
                try:
                    result = await asyncio.to_thread(FNS[fc.name], dict(fc.args or {}))
                except Exception as e:
                    result = {"error": str(e)[:300]}
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name, response=result))
            try:  # fresh frame BEFORE the response: judge from now-pixels
                jpg = await asyncio.to_thread(jpeg_frame)
                if jpg:
                    await session.send_realtime_input(
                        video=types.Blob(data=jpg, mime_type="image/jpeg"))
            except Exception:
                pass
            turn_in_flight = True
            await session.send_tool_response(function_responses=responses)


async def main():
    global hb_signal, turn_in_flight
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(
            async_client_args={"ping_interval": 10, "ping_timeout": 10}))
    speak("Orchestrator version two connecting.")
    while True:
        hb_signal = asyncio.Event()
        turn_in_flight = False
        try:
            async with client.aio.live.connect(model=MODEL, config=make_config()) as s:
                log("connected", resumed=bool(resume_handle))
                if pending_cmd:
                    log("resend_mission", text=pending_cmd)
                    turn_in_flight = True
                    await s.send_client_content(
                        turns=types.Content(role="user",
                                            parts=[types.Part(text=pending_cmd)]),
                        turn_complete=True)
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(receive(s))
                    tg.create_task(heartbeat_loop(s))
                    tg.create_task(user_commands(s))
        except BaseExceptionGroup as eg:
            if any(isinstance(e, KeyboardInterrupt) for e in eg.exceptions):
                return
            log("reconnect", err=str(eg.exceptions[0])[:250])
            print(f"[reconnecting: {eg.exceptions[0]}]", flush=True)
            await asyncio.sleep(2)
        except KeyboardInterrupt:
            return
        except Exception as e:
            log("reconnect", err=str(e)[:250])
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
