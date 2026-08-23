#!/usr/bin/env python3
"""Record a LeRobot dataset on the room host, with the preview alive throughout.

Why this exists instead of `lerobot-record`
-------------------------------------------
A V4L2 device has exactly one owner, so while a recording is running nothing
else can open `/dev/cam_*`. That normally means recording blind — fatal when the
operator is teleoperating from another room and the camera feed is the only way
to see what the arm is doing.

`record_loop` only ever *calls* the observation processor, so wrapping that
processor is enough to see every frame it reads — no lerobot patch, and the
frames are copied out of the control loop rather than re-read from hardware, so
the preview costs one JPEG encode on a worker thread and zero contention.

The preview therefore shows **exactly the frames going into the dataset**, which
is strictly better than a second stream that could silently diverge.

    python lab_record.py --repo-id kris0/so101_wall_v2 --task "pick up the block" \
        --episodes 5 --episode-time 20

Stop/keep/redo an episode: right-arrow keeps and moves on, left-arrow re-records,
escape stops — same keys as the lerobot CLI (that is lerobot's own listener).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab_cameras import CameraLock, CamerasBusy, read_session  # noqa: E402
from lab_cameras.preview import RecordTee, serve  # noqa: E402

PREVIEW_SERVICE = "labcam-preview"

# Measured on lab-pi with real frames: both cameras encode at 3.17x realtime with
# these settings, 4.4 MB per 20 s episode. The lerobot default (libsvtav1, g=2)
# is 0.4x realtime here and unusable. See notes/lab-setup-2026-08.md.
ENCODER = {"vcodec": "h264", "preset": "ultrafast"}


def _port_free(port: int) -> bool:
    import socket as _s
    with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as sock:
        sock.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def release_preview_service(port: int) -> bool:
    """The standalone preview autostarts and holds the camera mutex. Stop it for
    the duration of the recording, and put it back afterwards.

    Waiting for the LOCK to clear is not enough: the old process releases the
    flock before its HTTP socket is gone, so binding the preview port a moment
    later fails and the recording runs blind. Wait for the port too.
    """
    doc = read_session() or {}
    if "preview" not in str(doc.get("owner", "")) and doc.get("mode") != "preview":
        return False
    print(f"stopping {PREVIEW_SERVICE} (it holds the cameras); will restart it after")
    subprocess.run(["sudo", "-n", "systemctl", "stop", PREVIEW_SERVICE], capture_output=True)
    for _ in range(40):
        if not read_session() and _port_free(port):
            return True
        time.sleep(0.25)
    print(f"warning: {PREVIEW_SERVICE} did not release cleanly", file=sys.stderr)
    return True


def restore_preview_service() -> None:
    subprocess.run(["sudo", "-n", "systemctl", "start", PREVIEW_SERVICE], capture_output=True)


# The mesh-free derivative: FK is bit-identical (verified over 200 random configs)
# and it loads without the 15 MB of gitignored STLs, so a fresh checkout works.
URDF = str(Path(__file__).resolve().parent / "phone_teleop/SO101/so101_kinematics.urdf")

# The arm's own reach, measured by FK over this URDF: well-conditioned 63-300 mm
# from the pan axis. Clamping here is what stops a wild headset gesture from
# commanding a pose the IK will contort to reach.
EE_BOUNDS = {"min": [-0.32, -0.32, -0.02], "max": [0.32, 0.32, 0.34]}
EE_STEP = {"x": 1.0, "y": 1.0, "z": 1.0}   # headset metres -> robot metres


def build_robot(args):
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig

    sys.path.insert(0, str(Path(__file__).resolve().parent / "gemini_er"))
    import devices as dev

    cams = {
        "workspace_cam": OpenCVCameraConfig(index_or_path=dev.camera("workspace"),
                                            width=args.width, height=args.height, fps=args.fps),
        "wrist_cam": OpenCVCameraConfig(index_or_path=dev.camera("wrist"),
                                        width=args.width, height=args.height, fps=args.fps),
    }
    return SO101Follower(SO101FollowerConfig(
        port=dev.follower_port(), id=args.robot_id, cameras=cams, use_degrees=True,
        max_relative_target=args.max_relative_target))


def build_leader(args):
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    sys.path.insert(0, str(Path(__file__).resolve().parent / "gemini_er"))
    import devices as dev
    return SO101Leader(SO101LeaderConfig(port=dev.leader_port(), id=args.teleop_id)), None


def build_quest(args, robot):
    """Meta Quest over WebXR, using lerobot 0.6.0's own phone teleoperator.

    lerobot's "Android phone" path is really a generic WebXR 6-DoF pose source
    (`from teleop import Teleop`), and the SpesRobotics `teleop` package it
    drives explicitly supports VR headsets. So the Quest needs no fork and no
    extra IK stack -- every stage below ships with the pinned lerobot:

        AndroidPhone (WebXR)  -> phone.pos / phone.rot / raw_inputs / enabled
        MapPhoneActionToRobotAction -> target_x..wz + gripper_vel
        EEReferenceAndDelta   -> absolute EE target from the deltas
        EEBoundsAndSafety     -> clip to the arm's real reach, reject jumps
        GripperVelocityToJoint-> A/B buttons -> gripper
        InverseKinematicsEEToJoints (placo) -> joint targets

    Right controller: hold GRIP to engage (dead-man - release and the arm
    stops following), A/B open/close the gripper, thumbstick scales motion.
    """
    from lerobot.model.kinematics import RobotKinematics
    from lerobot.processor import RobotProcessorPipeline
    from lerobot.processor.converters import (
        robot_action_observation_to_transition, transition_to_robot_action)
    from lerobot.robots.so_follower.robot_kinematic_processor import (
        EEBoundsAndSafety, EEReferenceAndDelta, GripperVelocityToJoint,
        InverseKinematicsEEToJoints)
    from lerobot.teleoperators.phone.config_phone import PhoneConfig, PhoneOS
    from lerobot.teleoperators.phone.phone_processor import MapPhoneActionToRobotAction
    from lerobot.teleoperators.phone.teleop_phone import Phone

    teleop = Phone(PhoneConfig(phone_os=PhoneOS.ANDROID))
    motor_names = list(robot.bus.motors)
    kin = RobotKinematics(urdf_path=URDF, target_frame_name="gripper_frame_link",
                          joint_names=[m for m in motor_names if m != "gripper"])
    steps = [
        MapPhoneActionToRobotAction(platform=PhoneOS.ANDROID),
        EEReferenceAndDelta(kinematics=kin, end_effector_step_sizes=EE_STEP,
                            motor_names=motor_names, use_latched_reference=True),
        EEBoundsAndSafety(end_effector_bounds=EE_BOUNDS, max_ee_step_m=args.max_ee_step),
        GripperVelocityToJoint(speed_factor=args.gripper_speed),
        InverseKinematicsEEToJoints(kinematics=kin, motor_names=motor_names),
    ]
    pipeline = RobotProcessorPipeline[tuple[dict, dict], dict](
        steps=steps,
        to_transition=robot_action_observation_to_transition,
        to_output=transition_to_robot_action,
    )
    return teleop, pipeline


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--episodes", type=int, default=5)
    ap.add_argument("--episode-time", type=float, default=20.0)
    ap.add_argument("--reset-time", type=float, default=10.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--teleop", choices=["leader", "quest"], default="leader",
                    help="leader arm, or a Meta Quest over WebXR (lerobot's phone teleop)")
    ap.add_argument("--max-ee-step", type=float, default=0.05,
                    help="quest: reject end-effector jumps larger than this (m)")
    ap.add_argument("--gripper-speed", type=float, default=20.0)
    ap.add_argument("--robot-id", default="arm")
    ap.add_argument("--teleop-id", default="arm")
    ap.add_argument("--max-relative-target", type=float, default=None,
                    help="leave unset for recording: clamping distorts the demonstrations")
    ap.add_argument("--preview-port", type=int, default=8088)
    ap.add_argument("--encoder-threads", type=int, default=2,
                    help="per encoder; 2 measured 3.17x realtime for both cameras")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    restarted = release_preview_service(args.preview_port)
    try:
        with CameraLock(mode="record", extra={"repo_id": args.repo_id,
                                              "total": args.episodes}) as lock:
            return run(args, lock)
    except CamerasBusy as exc:
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        print("Free them first:  sudo systemctl stop labcam-preview", file=sys.stderr)
        return 2
    finally:
        if restarted:
            restore_preview_service()


def run(args, lock) -> int:
    from lerobot.configs.video import RGBEncoderConfig
    from lerobot.datasets import LeRobotDataset
    from lerobot.processor import make_default_processors
    from lerobot.scripts.lerobot_record import record_loop
    from lerobot.utils.feature_utils import hw_to_dataset_features

    robot = build_robot(args)
    if args.teleop == "quest":
        teleop, quest_pipeline = build_quest(args, robot)
    else:
        teleop, quest_pipeline = build_leader(args)
    tee = None
    if not args.no_preview:
        tee = RecordTee()
        serve(None, ["workspace", "wrist"], args.preview_port)  # push-only: no device access
        print(f"preview (live recording frames) on http://0.0.0.0:{args.preview_port}/")

    tap, rap, rop = make_default_processors()
    if quest_pipeline is not None:
        rap = quest_pipeline   # pose -> EE target -> IK -> joints
    if tee is not None:
        inner = rop

        def rop(obs, _inner=inner):
            tee(obs)      # never raises - a dead preview beats a dead recording
            return _inner(obs)

    features = {**hw_to_dataset_features(robot.action_features, "action", True),
                **hw_to_dataset_features(robot.observation_features, "observation", True)}
    common_ds = dict(
        image_writer_processes=0,
        image_writer_threads=2 * len(robot.cameras),
        rgb_encoder=RGBEncoderConfig(**ENCODER),
        encoder_threads=args.encoder_threads,
        # encode while recording rather than in a burst between episodes: at
        # 3.17x realtime it keeps up live, so there is no inter-episode gap
        streaming_encoding=True,
    )
    if args.resume:
        # resume() refuses root=None -- it would write into the shared Hub
        # snapshot cache. Point it at the same local path create() used.
        from lerobot.utils.constants import HF_LEROBOT_HOME
        dataset = LeRobotDataset.resume(args.repo_id,
                                        root=str(HF_LEROBOT_HOME / args.repo_id), **common_ds)
    else:
        dataset = LeRobotDataset.create(args.repo_id, args.fps, robot_type=robot.name,
                                        features=features, use_videos=True, **common_ds)

    robot.connect()
    teleop.connect()
    events = {"exit_early": False, "rerecord_episode": False, "stop_recording": False}
    common = dict(robot=robot, events=events, fps=args.fps, teleop=teleop,
                  teleop_action_processor=tap, robot_action_processor=rap,
                  robot_observation_processor=rop, single_task=args.task,
                  display_data=False)  # NEVER True on the Pi

    saved, ep, t0 = 0, 1, time.time()
    try:
        while saved < args.episodes:
            lock.update(episode=ep, phase="recording", saved=saved)
            print(f"\n=== episode {ep}/{args.episodes}  ({args.episode_time:.0f}s)", flush=True)
            events["exit_early"] = False
            record_loop(dataset=dataset, control_time_s=args.episode_time, **common)

            if events.get("rerecord_episode"):
                events["rerecord_episode"] = False
                events["exit_early"] = False
                dataset.clear_episode_buffer()
                print("  re-recording this one", flush=True)
                if events.get("stop_recording"):
                    break
                lock.update(phase="resetting")
                record_loop(control_time_s=args.reset_time, **common)
                continue

            te = time.time()
            dataset.save_episode()
            saved, ep = saved + 1, ep + 1
            print(f"  saved ({saved}/{args.episodes})  save took {time.time()-te:.2f}s", flush=True)
            if events.get("stop_recording") or saved >= args.episodes:
                break
            lock.update(episode=ep, phase="resetting", saved=saved)
            events["exit_early"] = False
            record_loop(control_time_s=args.reset_time, **common)
            if events.get("stop_recording"):
                break
    finally:
        if tee is not None:
            tee.stop()
        robot.disconnect()
        teleop.disconnect()

    wall = time.time() - t0
    print(f"\n{saved} episodes in {wall:.1f}s "
          f"({wall/max(saved,1):.1f}s each, {args.episode_time+args.reset_time:.0f}s of that "
          f"is the loop itself -> {wall/max(saved,1)-(args.episode_time+args.reset_time):+.1f}s "
          f"of per-episode overhead)")
    print(f"dataset: {dataset.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
