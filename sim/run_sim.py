"""ECE 4560 lab-4 exercise: start pose -> all-zeros over 2s -> hold 2s -> return.
The sim twin of a hardware wiggle script.

Run with viewer:   .venv/bin/python run_sim.py
Headless smoke test: .venv/bin/python run_sim.py --headless
Tweak STARTING_POSITION by eyeballing poses in:
  .venv/bin/python -m mujoco.viewer --mjcf=model/scene.xml   (slider values are radians)
"""
import sys

import mujoco
import mujoco.viewer

from so101_mujoco_utils import (
    convert_to_dictionary,
    hold_position,
    move_to_pose,
    set_initial_pose,
)

# Rough "rest" pose, degrees (gripper 0-100). Tweak via the viewer sliders.
STARTING_POSITION = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -60.0,
    "elbow_flex": 60.0,
    "wrist_flex": 60.0,
    "wrist_roll": 0.0,
    "gripper": 30.0,
}

ZERO_POSITION = {j: 0.0 for j in STARTING_POSITION}


def run(viewer, m, d):
    move_to_pose(m, d, viewer, ZERO_POSITION, duration=2.0)
    hold_position(m, d, viewer, duration=2.0)
    move_to_pose(m, d, viewer, STARTING_POSITION, duration=2.0)


def main():
    headless = "--headless" in sys.argv
    m = mujoco.MjModel.from_xml_path("model/scene.xml")
    d = mujoco.MjData(m)
    set_initial_pose(d, STARTING_POSITION)

    if headless:
        run(None, m, d)
    else:
        with mujoco.viewer.launch_passive(m, d) as viewer:
            run(viewer, m, d)
            hold_position(m, d, viewer, duration=2.0)  # linger so the end state is visible

    final = convert_to_dictionary(d.qpos)
    print("final pose (deg):", {k: round(v, 1) for k, v in final.items()})


if __name__ == "__main__":
    main()
