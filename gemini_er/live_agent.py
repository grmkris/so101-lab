"""ER 2 streaming orchestrator (Live API): workspace frames at ~0.3 fps + heartbeat,
tool calls out. Tools: vla_task (bounded MolmoAct2 rollout via run_molmoact.sh),
home, ack, reset. Model text output is spoken via macOS `say`.

Run (driver venv, from gemini_er/):
  GEMINI_API_KEY=... SERVER=100.x.y.z:8080 python live_agent.py
Type commands at the prompt; Ctrl-C to quit.
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from google import genai
from google.genai import types

import arm
from capture import grab
from cycle import DEBUG, load

MODEL = "gemini-robotics-er-2-streaming-preview"
SERVER = os.environ.get("SERVER", "")
LOG = DEBUG / "live_agent.jsonl"

calib = load()
CAM = calib["camera_index"]

tool_running = asyncio.Event()  # set while a blocking tool executes
resume_handle = None


def log(kind, **kw):
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "kind": kind, **kw}) + "\n")


def speak(text):
    subprocess.Popen(["say", text[:300]])


# ---------- tools (run in threads; camera is released between grabs) ----------

def tool_vla_task(args):
    task = str(args.get("instruction", "pick up the white block"))[:100]
    seconds = min(int(args.get("seconds", 60)), 90)
    if not SERVER:
        return {"error": "no policy server configured (SERVER env)"}
    speak(f"Running the robot policy: {task}")
    env = {**os.environ, "SERVER": SERVER, "TASK": task, "DURATION": str(seconds)}
    p = subprocess.run(["bash", "run_molmoact.sh"], env=env, capture_output=True,
                       text=True, timeout=seconds + 60)
    log("vla_task", task=task, seconds=seconds, rc=p.returncode,
        tail=p.stdout[-500:] + p.stderr[-300:])
    return {"outcome": "unverified",
            "instruction": "Inspect the next camera frame and judge from pixels "
                           "whether the task progressed. Do not assume success."}


def tool_home(args):
    robot = arm.connect()
    try:
        arm.move_joints(robot, np.array(calib["home_joints"]), 2.5, gripper=80)
    finally:
        robot.disconnect()
    return {"outcome": "arm commanded to home pose, gripper open"}


TOOLS = [{"function_declarations": [
    {"name": "vla_task", "behavior": "BLOCKING",
     "description": "Run the learned manipulation policy (MolmoAct2) on the arm for "
                    "a bounded time with a short natural-language instruction, e.g. "
                    "'pick up the white block'. Use for any physical manipulation.",
     "parameters": {"type": "OBJECT", "properties": {
         "instruction": {"type": "STRING"},
         "seconds": {"type": "INTEGER", "description": "max run time, <=90"}},
         "required": ["instruction"]}},
    {"name": "home", "behavior": "BLOCKING",
     "description": "Move the arm to its safe home pose with the gripper open.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "ack", "behavior": "BLOCKING",
     "description": "Acknowledge: scene nominal or step still in progress.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "reset", "behavior": "BLOCKING",
     "description": "Task finished; return to idle and summarize the outcome.",
     "parameters": {"type": "OBJECT", "properties": {}}},
]}]

FNS = {"vla_task": tool_vla_task, "home": tool_home,
       "ack": lambda a: {"ok": True}, "reset": lambda a: {"ok": True}}

HEARTBEAT = ("[HEARTBEAT] If no task is active, call 'ack' and wait for user input. "
             "If a task is active: observe the scene. If progressing, call 'ack'. "
             "If the current step is complete, proceed with the next step. "
             "If the overall goal is achieved, call 'reset' and tell the user.")

SYSTEM = ("You orchestrate a SO-101 robot arm over a live camera feed (front-oblique "
          "view: black mat, white block, plastic box). You cannot move joints "
          "directly - use tools. Verify every action from subsequent camera frames "
          "before claiming success; tool results are diagnostics, not proof. Keep "
          "spoken responses to one or two short sentences.")


def make_config():
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        tools=TOOLS,
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM)]),
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()),
    )


async def frames_and_heartbeat(session):
    while True:
        if not tool_running.is_set():  # camera free + safe to interrupt
            frame = None
            try:
                frame = await asyncio.to_thread(grab, CAM, 640, 480, 5)
            except Exception as e:
                log("camera_error", err=str(e)[:200])  # camera-only: keep looping
            if frame is not None:
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    # socket errors must PROPAGATE so the reconnect loop fires
                    await session.send_realtime_input(
                        video=types.Blob(data=jpg.tobytes(), mime_type="image/jpeg"))
                    await session.send_realtime_input(text=HEARTBEAT)
        await asyncio.sleep(3.0)  # well under the 1 fps hard limit


CMD_FILE = DEBUG / "live_cmds.txt"


async def user_commands(session):
    """Commands come from stdin (if a tty) AND from appended lines in
    debug/live_cmds.txt - the file path works while running backgrounded."""
    CMD_FILE.touch()
    offset = CMD_FILE.stat().st_size  # only react to NEW lines
    print(f"type a command, or: echo 'cmd' >> {CMD_FILE}", flush=True)
    stdin_ok = sys.stdin.isatty()
    loop = asyncio.get_running_loop()

    async def send(cmd):
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
    global resume_handle
    async for msg in session.receive():
        if msg.session_resumption_update and msg.session_resumption_update.resumable:
            resume_handle = msg.session_resumption_update.new_handle
        if msg.go_away:
            log("go_away", time_left=str(msg.go_away.time_left))
        if msg.server_content and msg.server_content.model_turn:
            for p in msg.server_content.model_turn.parts:
                if p.text:
                    print(f"\nMODEL: {p.text}\ntype a command > ", end="", flush=True)
                    log("model", text=p.text)
                    speak(p.text)
        if msg.tool_call:
            tool_running.set()
            responses = []
            for fc in msg.tool_call.function_calls:
                log("tool_call", name=fc.name, args=dict(fc.args or {}))
                try:
                    result = await asyncio.to_thread(FNS[fc.name], dict(fc.args or {}))
                except Exception as e:
                    result = {"error": str(e)[:300]}
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name, response=result))
            tool_running.clear()
            # fresh frame BEFORE the response so the model verifies from now-pixels
            try:
                frame = await asyncio.to_thread(grab, CAM, 640, 480, 5)
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    await session.send_realtime_input(
                        video=types.Blob(data=jpg.tobytes(), mime_type="image/jpeg"))
            except Exception:
                pass
            await session.send_tool_response(function_responses=responses)


async def main():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    speak("Live agent connecting.")
    while True:
        try:
            async with client.aio.live.connect(model=MODEL, config=make_config()) as s:
                log("connected", resumed=bool(resume_handle))
                await asyncio.gather(receive(s), frames_and_heartbeat(s),
                                     user_commands(s))
        except KeyboardInterrupt:
            break
        except Exception as e:
            log("reconnect", err=str(e)[:300])
            print(f"\n[reconnecting: {e}]")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
