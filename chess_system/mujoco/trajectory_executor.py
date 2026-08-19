"""Physics-stepped MuJoCo execution with a temporary hybrid weld latch."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import mujoco
import numpy as np

from chess_system.model import (
    ExecutabilityReport,
    ManipulationResult,
    MovePlan,
    ResultStatus,
)
from chess_system.mujoco.backend import DEFAULT_SCENE, MujocoChessBackend
from chess_system.mujoco.collision_world import _quat_from_matrix, _transform
from chess_system.mujoco.ik import SquareUnreachable, solve_axis_ik
from chess_system.mujoco.trajectory import JointTrajectory, TrajectoryLibrary
from chess_system.mujoco.runtime_planner import (
    PlanningBudgetExceeded,
    RuntimeTrajectoryPlanner,
    occupancy_signature,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = (
    ROOT / "chess_system" / "mujoco" / "generated" / "trajectory_library.json"
)
TOOL_MOUNT = ROOT / "chess_system" / "mujoco" / "generated" / "tool_mount.json"


STRUCTURE_PREFIXES = ("chess_board", "capture_bin_", "discard_tray_")


def _is_structure(body_name: str) -> bool:
    """Fixed furniture the arm must never touch: board, capture bins, trays."""

    return body_name.startswith(STRUCTURE_PREFIXES)


class TrajectoryExecutionError(RuntimeError):
    pass


class TrajectoryExecutor:
    def __init__(
        self,
        backend: MujocoChessBackend,
        library: TrajectoryLibrary,
        *,
        control_hz: int = 30,
        frame_callback: Callable[[], None] | None = None,
        cache_path: str | Path | None = None,
    ):
        self.backend = backend
        self.model = backend.model
        self.data = backend.data
        self.geometry = backend.geometry
        self.library = library
        self.runtime_planner = (
            RuntimeTrajectoryPlanner(library, cache_path=cache_path)
            if cache_path is not None
            else RuntimeTrajectoryPlanner(library)
        )
        self.control_hz = int(control_hz)
        self.frame_callback = frame_callback
        self.arm_joint_ids = [
            mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_JOINT, name
            )
            for name in (
                "shoulder_pan",
                "shoulder_lift",
                "elbow_flex",
                "wrist_flex",
                "wrist_roll",
            )
        ]
        self.arm_qpos = np.asarray(
            [self.model.jnt_qposadr[joint] for joint in self.arm_joint_ids]
        )
        self.gripper_joint = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_JOINT, "gripper"
        )
        self.gripper_qpos = int(self.model.jnt_qposadr[self.gripper_joint])
        self.tcp_site = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_SITE, "chess_tcp"
        )
        self.gripper_body = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "gripper"
        )
        self.latch_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_EQUALITY, "chess_piece_latch"
        )
        self.held_piece: str | None = None
        self.released_piece: str | None = None
        self.approach_piece: tuple[str, np.ndarray] | None = None
        # Resolved from the model rather than a hardcoded id range, which
        # silently shifts whenever a body is added to the scene.
        self._robot_bodies = frozenset(self._descendant_bodies("base"))
        # Collision checking validates the planned waypoints, but the servo
        # follows them only approximately: what the arm actually sweeps is not
        # what was cleared. Measured peak deviation over 36 clean drives was
        # 0.82 deg; a jam against the capture bin ran to 2.45 deg. Bounding it
        # turns silent divergence from the certified path into a stated
        # failure, rather than letting it surface as a settle symptom.
        self.tracking_limit_degrees = 3.0
        self.tool_mount = json.loads(TOOL_MOUNT.read_text())
        # When True the carried piece is written straight into qpos each step:
        # the tool does not hold it, the simulator does. Off by default — the
        # jaws have to carry the piece. Kept switchable as a debug fallback.
        self.assist_grasp = False
        # Stiffen friction vs normal so a slow pinch can lift a 12 g mast.
        # noslip is load-bearing: without it the mast slides out at 2 mm of lift.
        self.model.opt.impratio = 10.0
        self.model.opt.noslip_iterations = 20
        for geom_id in range(self.model.ngeom):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
            if name in ("chess_tool_fixed", "chess_tool_moving") or name.endswith("_mast"):
                self.model.geom_friction[geom_id] = (2.5, 0.05, 0.001)

    def _descendant_bodies(self, root: str) -> list[int]:
        """Body ids of ``root`` and everything attached below it."""

        root_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, root)
        if root_id < 0:
            raise RuntimeError(f"body missing from scene: {root}")
        members = {root_id}
        for body_id in range(self.model.nbody):
            parent = body_id
            while parent > 0:
                if parent in members:
                    members.add(body_id)
                    break
                parent = int(self.model.body_parentid[parent])
        return sorted(members)

    def _sync(self) -> None:
        if self.frame_callback:
            self.frame_callback()

    def _step_for(self, seconds: float) -> None:
        steps = max(1, int(round(seconds / float(self.model.opt.timestep))))
        for _ in range(steps):
            mujoco.mj_step(self.model, self.data)
            self._update_upright_latch()
            self._update_muted_approach_piece()
            self._check_non_target_contacts()
        mujoco.mj_forward(self.model, self.data)
        self._sync()

    def _update_muted_approach_piece(self) -> None:
        if self.approach_piece is None:
            return
        piece, saved_qpos = self.approach_piece
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        joint_id = int(self.model.body_jntadr[body_id])
        address = int(self.model.jnt_qposadr[joint_id])
        velocity = int(self.model.jnt_dofadr[joint_id])
        self.data.qpos[address : address + 7] = saved_qpos
        self.data.qvel[velocity : velocity + 6] = 0

    def _update_upright_latch(self) -> None:
        if self.held_piece is None or not self.assist_grasp:
            return
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, self.held_piece
        )
        joint_id = int(self.model.body_jntadr[body_id])
        address = int(self.model.jnt_qposadr[joint_id])
        velocity = int(self.model.jnt_dofadr[joint_id])
        mast_center = (
            float(self.geometry.piece["grasp_mast_bottom_z"])
            + float(self.geometry.piece["grasp_mast_height"]) / 2
        )
        root = self.data.site_xpos[self.tcp_site].copy()
        root[2] -= mast_center
        self.data.qpos[address : address + 3] = root
        self.data.qpos[address + 3 : address + 7] = (1.0, 0.0, 0.0, 0.0)
        self.data.qvel[velocity : velocity + 6] = 0

    def _check_non_target_contacts(self) -> None:
        allowed = {
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, name)
            for name in (self.held_piece, self.released_piece)
            if name
        }
        held_body = (
            mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_BODY, self.held_piece
            )
            if self.held_piece
            else -1
        )
        for contact_index in range(self.data.ncon):
            contact = self.data.contact[contact_index]
            body1 = int(self.model.geom_bodyid[contact.geom1])
            body2 = int(self.model.geom_bodyid[contact.geom2])
            name1 = (
                mujoco.mj_id2name(
                    self.model, mujoco.mjtObj.mjOBJ_BODY, body1
                )
                or ""
            )
            name2 = (
                mujoco.mj_id2name(
                    self.model, mujoco.mjtObj.mjOBJ_BODY, body2
                )
                or ""
            )
            first_piece = name1.startswith("piece_")
            second_piece = name2.startswith("piece_")
            first_robot = body1 in self._robot_bodies
            second_robot = body2 in self._robot_bodies
            first_structure = _is_structure(name1)
            second_structure = _is_structure(name2)
            # The arm driving into fixed structure used to surface only as a
            # servo symptom ("failed to settle"): the monitor watched pieces
            # and ignored the board, the capture bins and the trays. A jam
            # against the black bin therefore reported a 2.45 deg tracking
            # error instead of the collision that caused it.
            if (first_robot and second_structure) or (second_robot and first_structure):
                structure = name2 if first_robot else name1
                member = name1 if first_robot else name2
                raise TrajectoryExecutionError(
                    f"arm contacted fixed structure: {member} with {structure}"
                )
            if first_piece and second_robot and body1 not in allowed:
                raise TrajectoryExecutionError(
                    f"non-target contact: {name1} with {name2}"
                )
            if second_piece and first_robot and body2 not in allowed:
                raise TrajectoryExecutionError(
                    f"non-target contact: {name2} with {name1}"
                )
            if first_piece and second_piece and held_body in (body1, body2):
                other = name2 if body1 == held_body else name1
                raise TrajectoryExecutionError(
                    f"carried piece contacted {other}"
                )

    def _gripper_command(self, normalized: float) -> float:
        """Map 0-100 onto the *chess working band*, not the joint's full range.

        The extensions hang off a rotating jaw, so tip separation is a steep
        function of the joint angle: the usable band is about 7 deg of a 110 deg
        joint. Mapping 0-100 across the whole joint — as this did — turned a
        carry command of 20 into +12 deg, which stands the tips 45 mm apart and
        sweeps them through neighbouring pieces.

        0 = fully closed (clamping), 100 = open just enough to clear a mast.
        """

        low = self.tool_mount["closed_angle_radians"]
        high = self.tool_mount["open_angle_radians"]
        return low + (high - low) * float(normalized) / 100.0

    def reset_ready(self, *, settle_seconds: float = 0.4) -> None:
        mujoco.mj_resetData(self.model, self.data)
        ready = np.radians(self.geometry.motion_planning["ready_joints_degrees"])
        self.data.qpos[self.arm_qpos] = ready
        self.data.ctrl[:5] = ready
        self.data.ctrl[5] = self._gripper_command(75.0)
        self.data.eq_active[self.latch_id] = 0
        self.held_piece = None
        self.approach_piece = None
        mujoco.mj_forward(self.model, self.data)
        self._step_for(settle_seconds)

    def _interpolate_trajectory(self, trajectory: JointTrajectory, elapsed: float) -> np.ndarray:
        times = np.asarray(trajectory.timestamps_seconds)
        points = np.asarray(trajectory.waypoints_degrees)
        if elapsed <= 0:
            return np.radians(points[0])
        if elapsed >= times[-1]:
            return np.radians(points[-1])
        upper = int(np.searchsorted(times, elapsed, side="right"))
        lower = upper - 1
        duration = times[upper] - times[lower]
        alpha = 1.0 if duration <= 0 else (elapsed - times[lower]) / duration
        return np.radians(points[lower] + (points[upper] - points[lower]) * alpha)

    def drive(self, trajectory: JointTrajectory) -> None:
        duration = float(trajectory.timestamps_seconds[-1])
        period = 1.0 / self.control_hz
        ticks = max(1, int(np.ceil(duration / period)))
        for tick in range(ticks + 1):
            elapsed = min(duration, tick * period)
            target = self._interpolate_trajectory(trajectory, elapsed)
            deviation = float(
                np.max(np.abs(np.degrees(self.data.qpos[self.arm_qpos] - target)))
            )
            if deviation > self.tracking_limit_degrees:
                raise TrajectoryExecutionError(
                    f"arm deviated from {trajectory.trajectory_id} by "
                    f"{deviation:.2f}° (limit {self.tracking_limit_degrees:.2f}°)"
                )
            self.data.ctrl[:5] = target
            self.data.ctrl[5] = self._gripper_command(
                float(trajectory.gripper_normalized[min(tick, len(trajectory.gripper_normalized) - 1)])
            )
            self._step_for(period)
        final = np.radians(np.asarray(trajectory.waypoints_degrees[-1]))
        for _ in range(self.control_hz * 2):
            self.data.ctrl[:5] = final
            self._step_for(period)
            if np.max(np.abs(self.data.qpos[self.arm_qpos] - final)) <= np.radians(0.5):
                break
        error = float(
            np.max(np.abs(np.degrees(self.data.qpos[self.arm_qpos] - final)))
        )
        if error > 1.0:
            raise TrajectoryExecutionError(
                f"arm failed to settle at {trajectory.trajectory_id}: {error:.2f}°"
            )

    def set_gripper(self, normalized: float, seconds: float = 0.35) -> None:
        self.data.ctrl[5] = self._gripper_command(normalized)
        self._step_for(seconds)

    def _set_piece_collision(self, piece: str, enabled: bool) -> None:
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        for geom_id in range(self.model.ngeom):
            if int(self.model.geom_bodyid[geom_id]) == body_id:
                self.model.geom_contype[geom_id] = 1 if enabled else 0
                self.model.geom_conaffinity[geom_id] = 1 if enabled else 0

    def drive_release_retreat(
        self, trajectory: JointTrajectory, piece: str
    ) -> None:
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        joint_id = int(self.model.body_jntadr[body_id])
        address = int(self.model.jnt_qposadr[joint_id])
        self._set_piece_collision(piece, False)
        self.approach_piece = (
            piece,
            self.data.qpos[address : address + 7].copy(),
        )
        try:
            self.drive(trajectory)
        finally:
            self.approach_piece = None
            self.released_piece = None
            self._set_piece_collision(piece, True)

    def _piece_mast_world(self, piece: str) -> np.ndarray:
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        mast_center = (
            float(self.geometry.piece["grasp_mast_bottom_z"])
            + float(self.geometry.piece["grasp_mast_height"]) / 2
        )
        return self.data.xpos[body_id] + self.data.xmat[body_id].reshape(3, 3) @ np.asarray(
            (0.0, 0.0, mast_center)
        )

    def _snap_tcp_to_mast(self, piece: str) -> None:
        """Put the TCP on the live mast before closing. Square IK can be a few
        millimetres off the actual piece, which loads one jaw and misses the other.
        """

        target = self._piece_mast_world(piece)
        axis = self.data.site_xmat[self.tcp_site].reshape(3, 3)[:, 0].copy()
        q = self.data.qpos[self.arm_qpos].copy()
        solved = solve_axis_ik(
            self.runtime_planner.world,
            target,
            axis,
            q,
            position_tolerance=0.0008,
            axis_tolerance_degrees=6.0,
        )
        if solved is None:
            return
        self.data.ctrl[:5] = solved[0]
        self.data.ctrl[5] = self._gripper_command(100.0)
        self._step_for(0.45)

    def _pinch_is_loaded(self, piece: str) -> bool:
        """Both jaws have to be on the piece. One-sided contact cannot lift."""

        piece_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, piece)
        loaded = set()
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            body1 = int(self.model.geom_bodyid[contact.geom1])
            body2 = int(self.model.geom_bodyid[contact.geom2])
            if piece_id not in (body1, body2):
                continue
            other = body2 if body1 == piece_id else body1
            name = (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, other) or ""
            )
            if name in ("gripper", "moving_jaw_so101_v1"):
                loaded.add(name)
        return loaded == {"gripper", "moving_jaw_so101_v1"}

    def latch(self, piece: str) -> None:
        mujoco.mj_forward(self.model, self.data)
        alignment = float(
            np.linalg.norm(self.data.site_xpos[self.tcp_site] - self._piece_mast_world(piece))
        )
        if alignment > 0.006:
            raise TrajectoryExecutionError(
                f"piece {piece} outside latch envelope: {alignment * 1000:.1f} mm"
            )
        self.data.eq_active[self.latch_id] = 0
        self.held_piece = piece
        self._update_upright_latch()
        self._step_for(0.08)

    def _set_weld(self, piece_body: int, relative: np.ndarray) -> None:
        self.model.eq_obj2id[self.latch_id] = piece_body
        self.model.eq_data[self.latch_id, :] = 0
        self.model.eq_data[self.latch_id, 3:6] = relative[:3, 3]
        self.model.eq_data[self.latch_id, 6:10] = _quat_from_matrix(
            relative[:3, :3]
        )
        self.model.eq_data[self.latch_id, 10] = 1.0
        self.data.eq_active[self.latch_id] = 1

    def retarget_latch(self, piece: str, trajectory: JointTrajectory, piece_xyz) -> None:
        """Recenter the cylindrical mast at ready for destination-specific entry."""

        endpoint_q = np.radians(np.asarray(trajectory.waypoints_degrees[-1]))
        # Placement entries run ready->grasp, so the final waypoint is the target.
        scratch = mujoco.MjData(self.model)
        scratch.qpos[:] = self.data.qpos
        scratch.qpos[self.arm_qpos] = endpoint_q
        scratch.eq_active[self.latch_id] = 0
        mujoco.mj_forward(self.model, scratch)
        gripper_transform = _transform(
            scratch.xmat[self.gripper_body].reshape(3, 3),
            scratch.xpos[self.gripper_body],
        )
        piece_transform = np.eye(4)
        piece_transform[:3, 3] = np.asarray(piece_xyz, dtype=float)
        relative = np.linalg.inv(gripper_transform) @ piece_transform
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        self._set_weld(body_id, relative)
        self._step_for(0.35)

    def release(self, open_normalized: float = 35.0) -> None:
        """Open the jaws, then let go — in that order.

        Clearing ``held_piece`` while the tips are still clamped on the mast
        turns the grasp itself into a "non-target contact" the instant the
        piece stops being the target. Releasing therefore means opening first,
        letting the tips clear the mast, and only then dropping the hold.

        The ordering only started to matter once the tool actually closed on
        the piece; while the extensions were frozen 19 mm apart there was
        never any contact to release.
        """

        # Opening swings only the moving tip; the piece is left resting
        # against the fixed one until the arm physically retreats. That
        # grazing contact is part of releasing, so it stays permitted until
        # the retreat clears it — muting the piece instead would drop it
        # through the board during the settle.
        self.released_piece = self.held_piece
        self.set_gripper(open_normalized)
        self._step_for(0.20)
        self.unlatch()

    def unlatch(self) -> None:
        self.data.eq_active[self.latch_id] = 0
        self.held_piece = None
        self._step_for(0.04)

    def _reverse(self, trajectory: JointTrajectory) -> JointTrajectory:
        if trajectory.mode.value == "placement_entry":
            return self.library.require(f"exit:{trajectory.target}")
        waypoints = tuple(reversed(trajectory.waypoints_degrees))
        duration = trajectory.timestamps_seconds[-1]
        timestamps = tuple(
            duration - value for value in reversed(trajectory.timestamps_seconds)
        )
        return replace_trajectory(
            trajectory,
            trajectory_id=f"return:{trajectory.target}",
            waypoints_degrees=waypoints,
            timestamps_seconds=timestamps,
        )

    def _clamp_carry(self, trajectory: JointTrajectory) -> JointTrajectory:
        return replace_trajectory(
            trajectory,
            gripper_normalized=tuple(0.0 for _ in trajectory.gripper_normalized),
        )

    def approach_and_latch(
        self,
        square: str,
        entry: JointTrajectory,
    ) -> str:
        piece = self.backend._square_piece[square]
        # Jaws stay open on the way in so they can drop over the mast with
        # contact on. Closing through the piece (the old library default of 20)
        # required muting collision and then teleporting the piece.
        open_entry = replace_trajectory(
            entry,
            gripper_normalized=tuple(100.0 for _ in entry.gripper_normalized),
        )
        self.held_piece = piece
        try:
            self.drive(open_entry)
            self._snap_tcp_to_mast(piece)
            self.set_gripper(0.0, seconds=0.8)
            if not self._pinch_is_loaded(piece):
                self.set_gripper(100.0, seconds=0.35)
                self._snap_tcp_to_mast(piece)
                self.set_gripper(0.0, seconds=0.8)
            self.latch(piece)
        except Exception:
            self.held_piece = None
            raise
        return piece

    def _verify_placement(self, piece: str, square: str) -> None:
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        expected = self.geometry.square(
            square, z=float(self.geometry.board["nominal_top_z"])
        )
        actual = self.data.xpos[body_id]
        xy_error = float(np.linalg.norm(actual[:2] - np.asarray((expected.x, expected.y))))
        z_error = abs(float(actual[2] - expected.z))
        up = self.data.xmat[body_id].reshape(3, 3)[:, 2]
        tilt = float(
            np.degrees(np.arccos(np.clip(up @ np.asarray((0.0, 0.0, 1.0)), -1.0, 1.0)))
        )
        if xy_error > 0.004 or z_error > 0.004 or tilt > 25.0:
            raise TrajectoryExecutionError(
                f"piece placement outside tolerance at {square}: "
                f"xy={xy_error * 1000:.1f} mm z={z_error * 1000:.1f} mm tilt={tilt:.1f}°"
            )

    def move_square(self, source: str, target: str) -> None:
        if target in self.backend._square_piece:
            raise TrajectoryExecutionError(f"destination occupied: {target}")
        occupied = set(self.backend._square_piece)
        transfer = self.runtime_planner.transfer_route(
            source, target, occupied
        )
        source_q = np.radians(np.asarray(transfer.waypoints_degrees[0]))
        source_pose = self.geometry.square(
            source, z=float(self.geometry.board["nominal_top_z"])
        )
        _, source_entry = self.runtime_planner.arm_routes_to_endpoint(
            source,
            source_q,
            np.asarray(source_pose.xyz()),
            occupied,
            excluded_square=source,
        )
        piece = self.approach_and_latch(source, source_entry)
        self.drive(self._clamp_carry(transfer))
        self.release()
        self._step_for(0.80)
        self._verify_placement(piece, target)
        self.backend._square_piece.pop(source)
        self.backend._square_piece[target] = piece
        self.backend._piece_square[piece] = target
        occupied.discard(source)
        occupied.add(target)
        target_q = np.radians(np.asarray(transfer.waypoints_degrees[-1]))
        target_pose = self.geometry.square(
            target, z=float(self.geometry.board["nominal_top_z"])
        )
        exit_trajectory, _ = self.runtime_planner.arm_routes_to_endpoint(
            target,
            target_q,
            np.asarray(target_pose.xyz()),
            occupied,
            excluded_square=target,
        )
        self.drive_release_retreat(exit_trajectory, piece)

    def plan_move_square(self, source: str, target: str, occupied: set[str]) -> None:
        """Plan every route ``move_square`` will need, without moving anything.

        Routes land in the runtime planner's cache, so a successful preflight
        makes the subsequent execution a cache hit rather than a second search.
        """

        if target in occupied:
            raise TrajectoryExecutionError(f"destination occupied: {target}")
        transfer = self.runtime_planner.transfer_route(source, target, occupied)
        source_q = np.radians(np.asarray(transfer.waypoints_degrees[0]))
        source_pose = self.geometry.square(
            source, z=float(self.geometry.board["nominal_top_z"])
        )
        self.runtime_planner.arm_routes_to_endpoint(
            source,
            source_q,
            np.asarray(source_pose.xyz()),
            occupied,
            excluded_square=source,
        )
        after = (occupied - {source}) | {target}
        target_q = np.radians(np.asarray(transfer.waypoints_degrees[-1]))
        target_pose = self.geometry.square(
            target, z=float(self.geometry.board["nominal_top_z"])
        )
        self.runtime_planner.arm_routes_to_endpoint(
            target,
            target_q,
            np.asarray(target_pose.xyz()),
            after,
            excluded_square=target,
        )

    def plan_capture_to_bin(self, source: str, color: str, occupied: set[str]) -> None:
        """Plan every route ``capture_to_bin`` will need, without moving anything."""

        transfer = self.runtime_planner.capture_transfer_route(source, color, occupied)
        source_q = np.radians(np.asarray(transfer.waypoints_degrees[0]))
        source_pose = self.geometry.square(
            source, z=float(self.geometry.board["nominal_top_z"])
        )
        self.runtime_planner.arm_routes_to_endpoint(
            source,
            source_q,
            np.asarray(source_pose.xyz()),
            occupied,
            excluded_square=source,
        )
        target_q = np.radians(np.asarray(transfer.waypoints_degrees[-1]))
        x, y = self.geometry.capture_bin(color)
        bin_xyz = np.asarray(
            (x, y, float(self.geometry.board["nominal_top_z"]) + 0.003)
        )
        self.runtime_planner.arm_routes_to_endpoint(
            f"bin:{color}",
            target_q,
            bin_xyz,
            occupied - {source},
            excluded_square=None,
        )

    def capture_to_bin(self, source: str, color: str) -> None:
        occupied = set(self.backend._square_piece)
        transfer = self.runtime_planner.capture_transfer_route(
            source, color, occupied
        )
        source_q = np.radians(np.asarray(transfer.waypoints_degrees[0]))
        source_pose = self.geometry.square(
            source, z=float(self.geometry.board["nominal_top_z"])
        )
        _, source_entry = self.runtime_planner.arm_routes_to_endpoint(
            source,
            source_q,
            np.asarray(source_pose.xyz()),
            occupied,
            excluded_square=source,
        )
        piece = self.approach_and_latch(source, source_entry)
        self.drive(self._clamp_carry(transfer))
        self.release()
        self._step_for(0.45)
        self.backend._square_piece.pop(source)
        self.backend._piece_square[piece] = None
        occupied.discard(source)
        target_q = np.radians(np.asarray(transfer.waypoints_degrees[-1]))
        x, y = self.geometry.capture_bin(color)
        bin_xyz = np.asarray(
            (x, y, float(self.geometry.board["nominal_top_z"]) + 0.003)
        )
        bin_exit, _ = self.runtime_planner.arm_routes_to_endpoint(
            f"bin:{color}",
            target_q,
            bin_xyz,
            occupied,
            excluded_square=None,
        )
        self.drive_release_retreat(bin_exit, piece)
        self._discard(piece, color)

    def _discard(self, piece: str, color: str) -> None:
        """Move a released piece from the chute mouth to the discard tray.

        Modelling boundary, stated deliberately: the funnel's interior is not
        simulated. What is simulated is the part that can affect the robot —
        the piece is carried to the mouth, released, and verified to have
        actually left the tool and settled inside the mouth footprint. From
        there a passive fabricated chute takes it somewhere the arm cannot
        reach, so no amount of accumulation can obstruct a planned motion.

        This is why the tray is placed outside the reach envelope rather than
        beside the board: an unreachable tray needs no occupancy model, and a
        reachable one would put capture history back into the planning state.
        """

        mouth_x, mouth_y = self.geometry.capture_bin(color)
        address = self.backend._qpos_address(piece)
        resting = np.asarray(self.data.qpos[address : address + 3], dtype=float)
        radius = float(np.hypot(resting[0] - mouth_x, resting[1] - mouth_y))
        allowance = float(max(self.geometry.board["capture_bin_inner_size"]))
        if radius > allowance:
            raise TrajectoryExecutionError(
                f"released {piece} did not settle at the {color} chute mouth: "
                f"{radius * 1000:.1f} mm from centre (allowed {allowance * 1000:.1f} mm)"
            )
        index = self.backend._captures[color]
        self.backend._captures[color] += 1
        self.backend._set_piece_xyz(
            piece, self.geometry.discard_slot(color, index)
        )


def replace_trajectory(trajectory: JointTrajectory, **changes) -> JointTrajectory:
    raw = {
        "trajectory_id": trajectory.trajectory_id,
        "mode": trajectory.mode,
        "target": trajectory.target,
        "scenario": trajectory.scenario,
        "joint_names": trajectory.joint_names,
        "waypoints_degrees": trajectory.waypoints_degrees,
        "timestamps_seconds": trajectory.timestamps_seconds,
        "gripper_normalized": trajectory.gripper_normalized,
        "attachment_enabled": trajectory.attachment_enabled,
        "metrics": trajectory.metrics,
        "checksum": "",
    }
    raw.update(changes)
    return JointTrajectory(**raw).with_checksum()


class PlannedMujocoChessBackend(MujocoChessBackend):
    name = "mujoco_planned"

    def __init__(
        self,
        scene: str | Path = DEFAULT_SCENE,
        library_path: str | Path = DEFAULT_LIBRARY,
        *,
        frame_callback: Callable[[], None] | None = None,
        cache_path: str | Path | None = None,
        preflight_budget_seconds: float | None = 25.0,
    ):
        super().__init__(scene)
        self.preflight_budget_seconds = preflight_budget_seconds
        self.trajectory_library = TrajectoryLibrary.load(library_path)
        self.executor = TrajectoryExecutor(
            self,
            self.trajectory_library,
            frame_callback=frame_callback,
            cache_path=cache_path,
        )
        # (square, occupancy signature) pairs already proven unactionable.
        self._unreachable_squares: dict[tuple[str, str], str] = {}
        self.executor.reset_ready()

    def can_execute(self, plan: MovePlan) -> ExecutabilityReport:
        """Plan every step of ``plan`` against the live occupancy without moving.

        Occupancy is advanced step by step, so a capture-then-move plan is
        probed the way it will actually run: the moving piece is planned into a
        square its victim has already vacated.

        Two results are memoized against ``(square, occupancy)``, and they mean
        different things. ``SquareUnreachable`` is a geometric proof — nothing
        on that square can be acted on in this position, so every candidate
        move from it fails identically. A budget stop is only a decision to
        stop looking; it is recorded so sibling candidates do not each pay the
        full budget, and labelled so it is never mistaken for the proof.
        """

        occupied = set(self._square_piece)
        started = time.time()
        with self.executor.runtime_planner.budget(self.preflight_budget_seconds):
            for index, step in enumerate(plan.steps):
                signature = occupancy_signature(occupied)
                memo = self._unreachable_squares.get((step.source or "", signature))
                if memo is not None:
                    return ExecutabilityReport(
                        uci=plan.uci,
                        executable=False,
                        reason=f"{step.kind} {step.source}->{step.target}: {memo} (memoized)",
                        blocked_step=index,
                        planning_seconds=time.time() - started,
                    )
                try:
                    if step.kind == "capture":
                        self.executor.plan_capture_to_bin(
                            step.source or "", step.capture_bin or "black", occupied
                        )
                        occupied.discard(step.source or "")
                    elif step.kind in ("move", "castle_rook"):
                        self.executor.plan_move_square(
                            step.source or "", step.target or "", occupied
                        )
                        occupied.discard(step.source or "")
                        occupied.add(step.target or "")
                except Exception as exc:
                    if isinstance(exc, SquareUnreachable) and exc.square == step.source:
                        self._unreachable_squares[(exc.square, signature)] = str(exc)
                    elif isinstance(exc, PlanningBudgetExceeded):
                        self._unreachable_squares[(step.source or "", signature)] = (
                            f"budget stop (not proven unreachable): {exc}"
                        )
                    return ExecutabilityReport(
                        uci=plan.uci,
                        executable=False,
                        reason=f"{step.kind} {step.source}->{step.target}: {exc}",
                        blocked_step=index,
                        planning_seconds=time.time() - started,
                    )
        return ExecutabilityReport(
            uci=plan.uci,
            executable=True,
            planning_seconds=time.time() - started,
        )

    def execute_plan(self, plan: MovePlan) -> ManipulationResult:
        completed = 0
        try:
            for step in plan.steps:
                if step.kind == "capture":
                    self.executor.capture_to_bin(
                        step.source or "", step.capture_bin or "black"
                    )
                elif step.kind in ("move", "castle_rook"):
                    self.executor.move_square(
                        step.source or "", step.target or ""
                    )
                completed += 1
        except Exception as exc:
            self.hold()
            return ManipulationResult(
                ResultStatus.FAILED,
                plan.move_id,
                completed_steps=completed,
                message=str(exc),
            )
        return ManipulationResult(
            ResultStatus.VERIFIED,
            plan.move_id,
            completed_steps=completed,
            message="planned MuJoCo trajectory complete",
        )
