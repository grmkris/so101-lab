"""Physics-stepped MuJoCo execution with a temporary hybrid weld latch."""

from __future__ import annotations

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
from chess_system.mujoco.trajectory import JointTrajectory, TrajectoryLibrary
from chess_system.mujoco.runtime_planner import RuntimeTrajectoryPlanner


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = (
    ROOT / "chess_system" / "mujoco" / "generated" / "trajectory_library.json"
)


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
    ):
        self.backend = backend
        self.model = backend.model
        self.data = backend.data
        self.geometry = backend.geometry
        self.library = library
        self.runtime_planner = RuntimeTrajectoryPlanner(library)
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
        self.approach_piece: tuple[str, np.ndarray] | None = None

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
        if self.held_piece is None:
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
            first_robot = body1 in range(1, 8)
            second_robot = body2 in range(1, 8)
            if first_piece and second_robot and body1 != held_body:
                raise TrajectoryExecutionError(
                    f"non-target contact: {name1} with {name2}"
                )
            if second_piece and first_robot and body2 != held_body:
                raise TrajectoryExecutionError(
                    f"non-target contact: {name2} with {name1}"
                )
            if first_piece and second_piece and held_body in (body1, body2):
                other = name2 if body1 == held_body else name1
                raise TrajectoryExecutionError(
                    f"carried piece contacted {other}"
                )

    def _gripper_command(self, normalized: float) -> float:
        low, high = map(float, self.model.actuator_ctrlrange[5])
        return low + (high - low) * normalized / 100.0

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

    def approach_and_latch(
        self,
        square: str,
        entry: JointTrajectory,
    ) -> str:
        piece = self.backend._square_piece[square]
        self._set_piece_collision(piece, False)
        body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, piece
        )
        joint_id = int(self.model.body_jntadr[body_id])
        address = int(self.model.jnt_qposadr[joint_id])
        self.approach_piece = (
            piece,
            self.data.qpos[address : address + 7].copy(),
        )
        try:
            self.drive(entry)
            self.set_gripper(20.0)
            self.approach_piece = None
            self.latch(piece)
        finally:
            self.approach_piece = None
            self._set_piece_collision(piece, True)
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
        if xy_error > 0.003 or z_error > 0.0025 or tilt > 12.0:
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
        self.drive(transfer)
        self.unlatch()
        self.set_gripper(75.0)
        self._step_for(0.45)
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
        self.drive(transfer)
        self.unlatch()
        self.set_gripper(75.0)
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
    ):
        super().__init__(scene)
        self.trajectory_library = TrajectoryLibrary.load(library_path)
        self.executor = TrajectoryExecutor(
            self,
            self.trajectory_library,
            frame_callback=frame_callback,
        )
        self.executor.reset_ready()

    def can_execute(self, plan: MovePlan) -> ExecutabilityReport:
        """Plan every step of ``plan`` against the live occupancy without moving.

        Occupancy is advanced step by step, so a capture-then-move plan is
        probed the way it will actually run: the moving piece is planned into a
        square its victim has already vacated.
        """

        occupied = set(self._square_piece)
        started = time.time()
        for index, step in enumerate(plan.steps):
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
