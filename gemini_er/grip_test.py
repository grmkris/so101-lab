"""Empirically calibrate the proprioceptive grasp detector.

Closes on nothing (prints value), opens, waits for you to hold the block
between the jaws, closes again (prints value). The two numbers set the
held/empty threshold.
"""

import time

import arm

robot = arm.connect()
try:
    j = arm.joints_deg(robot)
    print("closing on NOTHING...")
    arm.move_joints(robot, j, 1.5, gripper=0)
    time.sleep(0.5)
    print(f"EMPTY close reads: {arm.joints_deg(robot)[-1]:.1f}")
    arm.move_joints(robot, j, 1.0, gripper=80)
    print("\nNow HOLD the block between the jaws, then press SPACE in the window...")
    import subprocess

    subprocess.run(["say", "hold the block between the jaws, then press space in the window"])
    import cv2

    cap = cv2.VideoCapture(1)
    cv2.namedWindow("block in jaws? then SPACE")
    while True:
        ok, f = cap.read()
        if ok:
            cv2.imshow("block in jaws? then SPACE", f)
        if cv2.waitKey(30) & 0xFF == ord(" "):
            break
    cap.release()
    cv2.destroyAllWindows()
    print("closing on the BLOCK...")
    arm.move_joints(robot, arm.joints_deg(robot), 1.5, gripper=0)
    time.sleep(0.5)
    print(f"HELD close reads: {arm.joints_deg(robot)[-1]:.1f}")
    time.sleep(2)
    arm.move_joints(robot, arm.joints_deg(robot), 1.0, gripper=80)
    print("released. Done.")
finally:
    robot.disconnect()
    print("robot disconnected (torque off).")
