"""Place the finger extensions against the SO-101's real jaw kinematics.

The first version of this tool model was wrong in a way that no test caught.
Both extensions were attached to the static ``gripper`` body and offset along
the gripper's local **y**. The gripper's hinge axis *is* local y, so the jaws
open and close along **x**: the two extensions were mounted perpendicular to
the direction the gripper actually moves, and neither of them was on the
moving jaw. Tip separation measured 19.00 mm at every commanded gripper angle
— fully open, carrying, fully closed — against a 7 mm grasp mast.

Nothing downstream noticed, because the piece was never carried by the tool.
It was written directly into ``qpos`` each step.

Measured from the real model, the jaw tips separate over 6.34 mm (fully
closed) to about 100 mm, so a 7 mm mast is well inside what the hardware can
clamp. This module solves, from the mesh geometry rather than from assumed
constants, where each extension has to sit for that clamp to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np


@dataclass(frozen=True)
class ToolMount:
    """Where each finger extension attaches, and the pose that clamps."""

    grip_angle: float
    """Gripper joint angle at which the tips just touch the mast (radians)."""

    closed_angle: float
    """Fully-closed angle. Commanding past ``grip_angle`` to here is what
    produces clamping force against a rigid mast."""

    open_angle: float
    """Widest angle chess ever commands. The extensions hang off a rotating
    jaw, so the tips sweep an arc: at the joint's mechanical limit they stand
    157 mm apart and carve a volume nothing on a 23 mm board could survive.
    Chess needs only enough opening to drop over a mast, so the working range
    is deliberately a small slice near closed."""

    fixed_x: float
    """Static-jaw extension centre, gripper frame (metres)."""

    moving_local_pos: tuple[float, float, float]
    """Moving-jaw extension centre, expressed in the moving jaw's frame."""

    moving_local_quat: tuple[float, float, float, float]
    """Moving-jaw extension orientation in the jaw frame, chosen so the
    extension hangs parallel to the fixed one at ``grip_angle``."""

    tcp_pos: tuple[float, float, float]
    """Grasp centre between the two tips, gripper frame."""

    jaw_tip_z: float
    separation_at_grip: float
    separation_when_closed: float


def _mesh_points(model, body_id: int) -> np.ndarray:
    points = []
    for geom in range(model.ngeom):
        if model.geom_bodyid[geom] != body_id:
            continue
        if model.geom_type[geom] != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        mesh = model.geom_dataid[geom]
        start = model.mesh_vertadr[mesh]
        count = model.mesh_vertnum[mesh]
        verts = model.mesh_vert[start : start + count].reshape(-1, 3)
        rotation = np.zeros(9)
        mujoco.mju_quat2Mat(rotation, model.geom_quat[geom])
        points.append(verts @ rotation.reshape(3, 3).T + model.geom_pos[geom])
    if not points:
        raise RuntimeError(f"body {body_id} has no mesh geometry to measure")
    return np.vstack(points)


def _quat_from_mat(matrix: np.ndarray) -> tuple[float, float, float, float]:
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.asarray(matrix, dtype=float).reshape(9))
    return tuple(float(v) for v in quat)


def solve_tool_mount(
    robot_path: str,
    *,
    mast_diameter: float,
    mast_height: float,
    tip_thickness: float,
    extension_length: float,
    open_separation: float,
) -> ToolMount:
    """Measure the jaws and solve for extension mounts that clamp the mast."""

    model = mujoco.MjModel.from_xml_path(str(robot_path))
    data = mujoco.MjData(model)
    joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "gripper")
    address = int(model.jnt_qposadr[joint])
    low, high = (float(v) for v in model.jnt_range[joint])
    gripper_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "gripper")
    jaw_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_BODY, "moving_jaw_so101_v1"
    )

    jaw_local = _mesh_points(model, jaw_id)
    gripper_local = _mesh_points(model, gripper_id)
    static_tip = gripper_local[gripper_local[:, 2].argmin()]

    def frames(angle: float):
        data.qpos[:] = 0
        data.qpos[address] = angle
        mujoco.mj_forward(model, data)
        return (
            data.xmat[gripper_id].reshape(3, 3).copy(),
            data.xpos[gripper_id].copy(),
            data.xmat[jaw_id].reshape(3, 3).copy(),
            data.xpos[jaw_id].copy(),
        )

    def jaw_tip_in_gripper(angle: float) -> np.ndarray:
        r_grip, p_grip, r_jaw, p_jaw = frames(angle)
        world = (r_jaw @ jaw_local.T).T + p_jaw
        local = (r_grip.T @ (world - p_grip).T).T
        return local[local[:, 2].argmin()]

    # Jaw tip x is monotonic over the closing range; bisect for the angle that
    # puts the moving extension at a given centre-to-centre separation.
    def angle_for(separation: float) -> float:
        target_x = float(static_tip[0]) + separation
        lower, upper = low, min(high, low + np.radians(20.0))
        for _ in range(60):
            middle = (lower + upper) / 2
            if jaw_tip_in_gripper(middle)[0] < target_x:
                lower = middle
            else:
                upper = middle
        return (lower + upper) / 2

    # Centre-to-centre spacing that puts both tip faces on the mast.
    grip_angle = angle_for(mast_diameter + tip_thickness)
    open_angle = angle_for(open_separation)

    tip = jaw_tip_in_gripper(grip_angle)
    jaw_tip_z = float(min(static_tip[2], tip[2]))

    # Both extensions hang straight down from the jaw tips at the grip angle.
    fixed_x = float(static_tip[0])
    moving_x = float(tip[0])
    centre_z = jaw_tip_z - extension_length / 2

    r_grip, p_grip, r_jaw, p_jaw = frames(grip_angle)
    desired_gripper = np.array([moving_x, float(static_tip[1]), centre_z])
    world = p_grip + r_grip @ desired_gripper
    moving_local_pos = tuple(float(v) for v in (r_jaw.T @ (world - p_jaw)))
    moving_local_quat = _quat_from_mat(r_jaw.T @ r_grip)

    closed_tip = jaw_tip_in_gripper(low)
    return ToolMount(
        grip_angle=float(grip_angle),
        closed_angle=float(low),
        open_angle=float(open_angle),
        fixed_x=fixed_x,
        moving_local_pos=moving_local_pos,
        moving_local_quat=moving_local_quat,
        # The TCP is the point the planner commands onto the mast centre, so
        # where it sits along the extension decides how much of the mast the
        # pinch actually covers. Putting it at the extension's very tip left
        # only the top 6 mm of a 12 mm mast gripped: too short a patch to
        # resist tilt, and the piece rotated out of the jaws while the clamp
        # itself never slipped. Raising it by half the mast height (less 2 mm
        # so the tips stay clear of the wider body below) straddles the band.
        tcp_pos=(
            (fixed_x + moving_x) / 2,
            float(static_tip[1]),
            jaw_tip_z - extension_length + (mast_height / 2 - 0.002),
        ),
        jaw_tip_z=jaw_tip_z,
        separation_at_grip=float(moving_x - fixed_x),
        separation_when_closed=float(closed_tip[0] - fixed_x),
    )
