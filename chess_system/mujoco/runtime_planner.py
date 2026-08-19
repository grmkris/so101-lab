"""Occupancy-aware validation, replanning, and caching over baseline routes."""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
import math
from dataclasses import replace
from pathlib import Path

import mujoco
import numpy as np

from chess_system.mujoco.collision_world import CollisionWorld
from chess_system.mujoco.generate_trajectories import _plan_endpoint
from chess_system.mujoco.generate_trajectories import _timestamps
from chess_system.mujoco.ik import (
    choose_bin_endpoint,
    choose_square_endpoint,
    solve_axis_ik,
    solve_position_ik,
)
from chess_system.mujoco.ik import GraspEndpoint
from chess_system.mujoco.trajectory import (
    JointTrajectory,
    MotionMode,
    TrajectoryLibrary,
    TrajectoryMetrics,
)
from chess_system.mujoco.rrt import RRTConnect, resample_path, shortcut_path
from chess_system.mujoco.collision_world import ARM_JOINTS


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = (
    ROOT
    / "chess_system"
    / "mujoco"
    / "generated"
    / "runtime_trajectory_cache.json"
)


def occupancy_signature(occupied_squares: set[str]) -> str:
    payload = ",".join(sorted(occupied_squares))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class PlanningBudgetExceeded(RuntimeError):
    """A search was stopped by its wall-clock budget, not by geometry.

    Deliberately distinct from ``SquareUnreachable``: that is a proof about the
    board, this is only a statement that we declined to keep looking. Never
    report one as the other — a budget stop must not become evidence that a
    square is unreachable.
    """


class RuntimeTrajectoryPlanner:
    def __init__(
        self,
        baseline: TrajectoryLibrary,
        *,
        cache_path: str | Path = DEFAULT_CACHE,
    ):
        self.baseline = baseline
        self.world = CollisionWorld()
        self.cache_path = Path(cache_path)
        self._deadline: float | None = None
        self.cache = (
            TrajectoryLibrary.load(self.cache_path)
            if self.cache_path.exists()
            else TrajectoryLibrary(
                geometry_schema_version=int(
                    self.world.geometry.raw["schema_version"]
                ),
                generation={"kind": "runtime_occupancy_cache"},
            )
        )

    @contextmanager
    def budget(self, seconds: float | None):
        """Bound the wall-clock cost of searches made inside the block.

        The bound is advisory in granularity: it is checked between candidate
        endpoints and between planner seeds, so a single very slow candidate
        can overrun it. That is enough to stop a search that would otherwise
        enumerate 61 IK candidates for several minutes.
        """

        previous = self._deadline
        self._deadline = None if seconds is None else time.monotonic() + float(seconds)
        try:
            yield
        finally:
            self._deadline = previous

    def _check_budget(self, what: str) -> None:
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise PlanningBudgetExceeded(f"planning budget exhausted while {what}")

    def _cache_pair(
        self,
        target: str,
        signature: str,
        exit_trajectory: JointTrajectory,
    ) -> tuple[JointTrajectory, JointTrajectory]:
        exit_id = f"runtime_exit:{target}:{signature}"
        entry_id = f"runtime_entry:{target}:{signature}"
        runtime_exit = replace(
            exit_trajectory,
            trajectory_id=exit_id,
            checksum="",
        ).with_checksum()
        runtime_entry = replace(
            exit_trajectory.reversed_for_placement(),
            trajectory_id=entry_id,
            checksum="",
        ).with_checksum()
        self.cache.add(runtime_exit)
        self.cache.add(runtime_entry)
        self.cache.save(self.cache_path)
        return runtime_exit, runtime_entry

    def _validate(
        self,
        trajectory: JointTrajectory,
        *,
        target: str,
        target_xyz: np.ndarray,
        excluded_square: str | None,
        occupied_squares: set[str],
        attached: bool = True,
        upright_attachment: bool = False,
    ) -> bool:
        path = tuple(np.radians(row) for row in trajectory.waypoints_degrees)
        endpoint_q = path[0]
        count = int(self.world.geometry.motion_planning["tolerance_replay_seeds"])
        for perturbation_seed in range(count):
            self.world.configure(
                target,
                endpoint_q,
                target_xyz=target_xyz,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=attached,
                upright_attachment=upright_attachment,
                perturbation_seed=perturbation_seed,
            )
            if not self.world.state_valid(path[0]):
                return False
            for start, end in zip(path, path[1:]):
                if not self.world.edge_valid(start, end):
                    return False
        return True

    def square_routes(
        self,
        square: str,
        occupied_squares: set[str],
    ) -> tuple[JointTrajectory, JointTrajectory]:
        occupied = set(occupied_squares)
        signature = occupancy_signature(occupied)
        exit_id = f"runtime_exit:{square}:{signature}"
        entry_id = f"runtime_entry:{square}:{signature}"
        if exit_id in self.cache.trajectories:
            return self.cache.require(exit_id), self.cache.require(entry_id)
        self._check_budget(f"planning square routes for {square}")

        baseline_exit = self.baseline.require(f"exit:{square}")
        pose = self.world.geometry.square(square)
        target_xyz = np.asarray(
            (
                pose.x,
                pose.y,
                float(self.world.geometry.board["nominal_top_z"]),
            )
        )
        if self._validate(
            baseline_exit,
            target=square,
            target_xyz=target_xyz,
            excluded_square=square,
            occupied_squares=occupied,
            attached=False,
        ):
            return self._cache_pair(
                square, signature, baseline_exit
            )

        endpoint = choose_square_endpoint(
            self.world,
            square,
            occupied_squares=occupied,
            attached=False,
        )
        replanned, _ = _plan_endpoint(
            self.world,
            endpoint,
            excluded_square=square,
            occupied_squares=occupied,
            attached=False,
        )
        return self._cache_pair(square, signature, replanned)

    def arm_routes_to_endpoint(
        self,
        target: str,
        endpoint_q: np.ndarray,
        target_xyz: np.ndarray,
        occupied_squares: set[str],
        *,
        excluded_square: str | None,
    ) -> tuple[JointTrajectory, JointTrajectory]:
        occupied = set(occupied_squares)
        q_digest = hashlib.sha256(
            np.asarray(endpoint_q, dtype=float).tobytes()
        ).hexdigest()[:10]
        signature = occupancy_signature(occupied) + q_digest
        exit_id = f"runtime_exit:{target}:{signature}"
        entry_id = f"runtime_entry:{target}:{signature}"
        if exit_id in self.cache.trajectories:
            return self.cache.require(exit_id), self.cache.require(entry_id)
        self._check_budget(f"planning arm routes for {target}")
        tcp_xyz = np.asarray(target_xyz, dtype=float).copy()
        tcp_xyz[2] += (
            float(self.world.geometry.piece["grasp_mast_bottom_z"])
            + float(self.world.geometry.piece["grasp_mast_height"]) / 2
        )
        endpoint = GraspEndpoint(
            target=target,
            q_radians=np.asarray(endpoint_q, dtype=float),
            target_axis=np.asarray((0.0, 0.0, -1.0)),
            target_piece_xyz=np.asarray(target_xyz, dtype=float),
            tcp_target_xyz=tcp_xyz,
            position_error_m=0.0,
            axis_error_degrees=0.0,
            tilt_degrees=0.0,
            iterations=0,
        )
        planned, _ = _plan_endpoint(
            self.world,
            endpoint,
            excluded_square=excluded_square,
            occupied_squares=occupied,
            attached=False,
        )
        return self._cache_pair(target, signature, planned)

    def transfer_route(
        self,
        source: str,
        target: str,
        occupied_squares: set[str],
    ) -> JointTrajectory:
        occupied = set(occupied_squares) - {source, target}
        signature = occupancy_signature(set(occupied_squares))
        cache_id = f"runtime_transfer:hover:{source}:{target}:{signature}"
        if cache_id in self.cache.trajectories:
            return self.cache.require(cache_id)
        self._check_budget(f"planning transfer {source}->{target}")
        target_pose = self.world.geometry.square(target)
        target_tcp = np.asarray(
            (
                target_pose.x,
                target_pose.y,
                float(self.world.geometry.board["nominal_top_z"])
                + float(self.world.geometry.piece["grasp_mast_bottom_z"])
                + float(self.world.geometry.piece["grasp_mast_height"]) / 2,
            )
        )
        source_endpoint = choose_square_endpoint(
            self.world,
            source,
            occupied_squares=occupied,
            attached=True,
            upright_attachment=True,
        )
        target_endpoint = choose_square_endpoint(
            self.world,
            target,
            occupied_squares=occupied,
            attached=True,
            upright_attachment=True,
        )
        try:
            return self._plan_transfer_between(
                cache_id,
                source_endpoint,
                target_endpoint,
                occupied,
                excluded_square=source,
                allow_direct_rrt=False,
            )
        except RuntimeError:
            directional = self._directional_source_endpoint(
                source, target_tcp, occupied
            )
            return self._plan_transfer_between(
                cache_id,
                directional,
                target_endpoint,
                occupied,
                excluded_square=source,
                allow_direct_rrt=False,
            )

    def capture_transfer_route(
        self,
        source: str,
        color: str,
        occupied_squares: set[str],
    ) -> JointTrajectory:
        occupied = set(occupied_squares) - {source}
        signature = occupancy_signature(set(occupied_squares))
        cache_id = f"runtime_capture:axis:{source}:{color}:{signature}"
        if cache_id in self.cache.trajectories:
            return self.cache.require(cache_id)
        self._check_budget(f"planning capture from {source}")
        bin_x, bin_y = self.world.geometry.capture_bin(color)
        bin_tcp = np.asarray(
            (
                bin_x,
                bin_y,
                float(self.world.geometry.board["nominal_top_z"])
                + 0.003
                + float(self.world.geometry.piece["grasp_mast_bottom_z"])
                + float(self.world.geometry.piece["grasp_mast_height"]) / 2,
            )
        )
        source_endpoint = choose_square_endpoint(
            self.world,
            source,
            occupied_squares=occupied,
            attached=True,
            upright_attachment=True,
        )
        target_endpoint = choose_bin_endpoint(
            self.world,
            color,
            occupied_squares=occupied,
            attached=True,
            upright_attachment=True,
        )
        try:
            return self._plan_transfer_between(
                cache_id,
                source_endpoint,
                target_endpoint,
                occupied,
                excluded_square=source,
                allow_direct_rrt=False,
            )
        except RuntimeError:
            directional = self._directional_source_endpoint(
                source, bin_tcp, occupied
            )
            return self._plan_transfer_between(
                cache_id,
                directional,
                target_endpoint,
                occupied,
                excluded_square=source,
                allow_direct_rrt=False,
            )

    def _directional_source_endpoint(
        self,
        source: str,
        destination_tcp: np.ndarray,
        occupied_squares: set[str],
    ):
        source_pose = self.world.geometry.square(source)
        source_tcp = np.asarray(
            (
                source_pose.x,
                source_pose.y,
                float(self.world.geometry.board["nominal_top_z"])
                + float(self.world.geometry.piece["grasp_mast_bottom_z"])
                + float(self.world.geometry.piece["grasp_mast_height"]) / 2,
            )
        )
        direction = destination_tcp - source_tcp
        direction_angle = math.degrees(math.atan2(direction[1], direction[0]))
        yaw_offsets = (75.0, -75.0, 105.0, -105.0, 45.0, -45.0, 180.0, 0.0, 90.0, 270.0)
        axes = [
            (tilt, (direction_angle + offset) % 360)
            for tilt in (10.0, 15.0, 5.0, 20.0, 25.0, 30.0)
            for offset in yaw_offsets
        ]
        axes.insert(0, (0.0, 180.0))

        return choose_square_endpoint(
            self.world,
            source,
            occupied_squares=occupied_squares,
            attached=True,
            upright_attachment=True,
            axis_candidates=axes,
            on_candidate=lambda: self._check_budget(
                f"searching grasp endpoints for {source}"
            ),
            candidate_validator=lambda endpoint: self._first_motion_clear(
                endpoint, destination_tcp, occupied_squares
            ),
        )

    def _first_motion_clear(
        self,
        endpoint,
        destination_tcp: np.ndarray,
        occupied_squares: set[str],
    ) -> bool:
        self.world.configure(
            endpoint.target,
            endpoint.q_radians,
            target_xyz=endpoint.target_piece_xyz,
            excluded_square=endpoint.target,
            occupied_squares=occupied_squares,
            attached=True,
            upright_attachment=True,
        )
        direction = destination_tcp - endpoint.tcp_target_xyz
        first_target = endpoint.tcp_target_xyz + direction * 0.15
        first_target[2] += 0.002
        next_q = solve_position_ik(
            self.world, first_target, endpoint.q_radians
        )
        return next_q is not None and self.world.edge_valid(
            endpoint.q_radians, next_q
        )

    def _plan_transfer_between(
        self,
        cache_id: str,
        source_endpoint,
        target_endpoint,
        occupied_squares: set[str],
        *,
        excluded_square: str | None,
        allow_direct_rrt: bool = True,
    ) -> JointTrajectory:
        config = self.world.geometry.motion_planning
        cartesian = self._cartesian_transfer_path(
            source_endpoint,
            target_endpoint,
            occupied_squares,
            excluded_square=excluded_square,
        )
        if cartesian is not None:
            timestamps = _timestamps(
                cartesian,
                float(config["maximum_velocity_degrees_s"]),
                float(config["maximum_acceleration_degrees_s2"]),
            )
            timestamps = self._stretch_for_tcp_speed(
                cartesian, timestamps, maximum_speed_m_s=0.008
            )
            metrics = TrajectoryMetrics(
                planning_attempt=1,
                planning_iterations=0,
                raw_waypoints=len(cartesian),
                final_waypoints=len(cartesian),
                duration_seconds=float(timestamps[-1]),
                minimum_joint_margin_degrees=self.world.minimum_joint_margin_degrees(
                    cartesian
                ),
                nominal_clearance_m=float(config["nominal_clearance"]),
                tolerance_replays=int(config["tolerance_replay_seeds"]),
                tolerance_failures=0,
            )
            trajectory = JointTrajectory(
                trajectory_id=cache_id,
                mode=MotionMode.PICKUP_EXIT,
                target=f"{source_endpoint.target}->{target_endpoint.target}",
                scenario="legal_cartesian_occupancy:"
                + ",".join(sorted(occupied_squares)),
                joint_names=ARM_JOINTS,
                waypoints_degrees=tuple(
                    tuple(round(float(value), 6) for value in np.degrees(q))
                    for q in cartesian
                ),
                timestamps_seconds=tuple(
                    round(float(value), 6) for value in timestamps
                ),
                gripper_normalized=tuple(20.0 for _ in cartesian),
                attachment_enabled=tuple(True for _ in cartesian),
                metrics=metrics,
            ).with_checksum()
            self.cache.add(trajectory)
            self.cache.save(self.cache_path)
            return trajectory

        try:
            source_exit, _ = _plan_endpoint(
                self.world,
                source_endpoint,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=True,
                upright_attachment=True,
                allow_rrt=False,
            )
            target_excluded = (
                target_endpoint.target
                if target_endpoint.target in self.world.obstacle_body_ids
                else None
            )
            target_exit, _ = _plan_endpoint(
                self.world,
                target_endpoint,
                excluded_square=target_excluded,
                occupied_squares=occupied_squares,
                attached=True,
                upright_attachment=True,
                allow_rrt=False,
            )
            source_path = tuple(
                np.radians(row) for row in source_exit.waypoints_degrees
            )
            target_entry = tuple(
                reversed(
                    tuple(
                        np.radians(row)
                        for row in target_exit.waypoints_degrees
                    )
                )
            )
            path = source_path + target_entry[1:]
            timestamps = _timestamps(
                path,
                float(config["maximum_velocity_degrees_s"]),
                float(config["maximum_acceleration_degrees_s2"]),
            )
            metrics = TrajectoryMetrics(
                planning_attempt=(
                    source_exit.metrics.planning_attempt
                    + target_exit.metrics.planning_attempt
                ),
                planning_iterations=(
                    source_exit.metrics.planning_iterations
                    + target_exit.metrics.planning_iterations
                ),
                raw_waypoints=(
                    source_exit.metrics.raw_waypoints
                    + target_exit.metrics.raw_waypoints
                ),
                final_waypoints=len(path),
                duration_seconds=float(timestamps[-1]),
                minimum_joint_margin_degrees=min(
                    source_exit.metrics.minimum_joint_margin_degrees,
                    target_exit.metrics.minimum_joint_margin_degrees,
                ),
                nominal_clearance_m=float(config["nominal_clearance"]),
                tolerance_replays=int(config["tolerance_replay_seeds"]),
                tolerance_failures=0,
            )
            trajectory = JointTrajectory(
                trajectory_id=cache_id,
                mode=MotionMode.PICKUP_EXIT,
                target=f"{source_endpoint.target}->{target_endpoint.target}",
                scenario="legal_occupancy:" + ",".join(sorted(occupied_squares)),
                joint_names=ARM_JOINTS,
                waypoints_degrees=tuple(
                    tuple(round(float(value), 6) for value in np.degrees(q))
                    for q in path
                ),
                timestamps_seconds=tuple(
                    round(float(value), 6) for value in timestamps
                ),
                gripper_normalized=tuple(20.0 for _ in path),
                attachment_enabled=tuple(True for _ in path),
                metrics=metrics,
            ).with_checksum()
            self.cache.add(trajectory)
            self.cache.save(self.cache_path)
            return trajectory
        except RuntimeError:
            # Fall through to direct joint-space RRT when a shared-ready half
            # has no robust solution for this legal occupancy.
            pass

        if not allow_direct_rrt:
            raise RuntimeError("deterministic transfer candidates exhausted")

        planner = RRTConnect(
            self.world.lower,
            self.world.upper,
            self.world.state_valid,
            self.world.edge_valid,
            step_radians=math.radians(float(config["rrt_step_degrees"])),
            goal_bias=float(config["goal_bias"]),
            maximum_iterations=int(config["maximum_iterations"]),
        )
        diagnostics = []
        selected = None
        selected_seed = None
        for attempt, seed in enumerate(config["attempt_seeds"], start=1):
            self.world.configure(
                source_endpoint.target,
                source_endpoint.q_radians,
                target_xyz=source_endpoint.target_piece_xyz,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=True,
                upright_attachment=True,
            )
            self._check_budget(f"planning {cache_id} with RRT seeds")
            result = planner.plan(
                source_endpoint.q_radians,
                target_endpoint.q_radians,
                seed=int(seed),
            )
            if result is None:
                diagnostics.append({"seed": int(seed), "planning": "failed"})
                continue
            path = shortcut_path(
                result.path,
                self.world.edge_valid,
                attempts=int(config["shortcut_attempts"]),
                seed=int(seed) + 20_000,
            )
            path = resample_path(
                path,
                math.radians(float(config["edge_resolution_degrees"])),
            )
            failures = []
            for perturbation_seed in range(
                int(config["tolerance_replay_seeds"])
            ):
                self.world.configure(
                    source_endpoint.target,
                    source_endpoint.q_radians,
                    target_xyz=source_endpoint.target_piece_xyz,
                    excluded_square=excluded_square,
                    occupied_squares=occupied_squares,
                    attached=True,
                    upright_attachment=True,
                    perturbation_seed=perturbation_seed,
                )
                for edge_index, (start, end) in enumerate(zip(path, path[1:])):
                    if not self.world.edge_valid(start, end):
                        failures.append(
                            {
                                "seed": perturbation_seed,
                                "edge": edge_index,
                                "contacts": self.world.last_forbidden_contacts,
                            }
                        )
                        break
            diagnostics.append(
                {
                    "seed": int(seed),
                    "iterations": result.iterations,
                    "tolerance_failures": len(failures),
                }
            )
            if not failures:
                selected = (path, result, attempt)
                selected_seed = int(seed)
                break
        if selected is None:
            raise RuntimeError(
                f"robust transfer planning failed {cache_id}: {diagnostics}"
            )
        path, result, attempt = selected
        timestamps = _timestamps(
            path,
            float(config["maximum_velocity_degrees_s"]),
            float(config["maximum_acceleration_degrees_s2"]),
        )
        metrics = TrajectoryMetrics(
            planning_attempt=attempt,
            planning_iterations=result.iterations,
            raw_waypoints=len(result.path),
            final_waypoints=len(path),
            duration_seconds=float(timestamps[-1]),
            minimum_joint_margin_degrees=self.world.minimum_joint_margin_degrees(path),
            nominal_clearance_m=float(config["nominal_clearance"]),
            tolerance_replays=int(config["tolerance_replay_seeds"]),
            tolerance_failures=0,
        )
        trajectory = JointTrajectory(
            trajectory_id=cache_id,
            mode=MotionMode.PICKUP_EXIT,
            target=f"{source_endpoint.target}->{target_endpoint.target}",
            scenario="legal_occupancy:" + ",".join(sorted(occupied_squares)),
            joint_names=ARM_JOINTS,
            waypoints_degrees=tuple(
                tuple(round(float(value), 6) for value in np.degrees(q))
                for q in path
            ),
            timestamps_seconds=tuple(round(float(value), 6) for value in timestamps),
            gripper_normalized=tuple(20.0 for _ in path),
            attachment_enabled=tuple(True for _ in path),
            metrics=metrics,
        ).with_checksum()
        self.cache.add(trajectory)
        self.cache.save(self.cache_path)
        return trajectory

    def _stretch_for_tcp_speed(
        self,
        path: tuple[np.ndarray, ...],
        timestamps: tuple[float, ...],
        *,
        maximum_speed_m_s: float,
    ) -> tuple[float, ...]:
        """Joint-space timing can yank a 20 mm lift in 0.5 s. Friction cannot."""

        previous = None
        length = 0.0
        for q in path:
            self.world.data.qpos[self.world.qpos_addresses] = q
            mujoco.mj_forward(self.world.model, self.world.data)
            tcp = self.world.data.site_xpos[self.world.site_id].copy()
            if previous is not None:
                length += float(np.linalg.norm(tcp - previous))
            previous = tcp
        current = float(timestamps[-1]) if timestamps else 0.0
        needed = length / maximum_speed_m_s if maximum_speed_m_s > 0 else current
        if current <= 0 or needed <= current:
            return timestamps
        scale = needed / current
        return tuple(float(value) * scale for value in timestamps)

    def _cartesian_transfer_path(
        self,
        source_endpoint,
        target_endpoint,
        occupied_squares: set[str],
        *,
        excluded_square: str | None,
    ) -> tuple[np.ndarray, ...] | None:
        config = self.world.geometry.motion_planning
        source_tcp = np.asarray(source_endpoint.tcp_target_xyz, dtype=float)
        dest_tcp = np.asarray(target_endpoint.tcp_target_xyz, dtype=float)
        axis = np.asarray(source_endpoint.target_axis, dtype=float)
        for hover_m in (0.030, 0.035, 0.040, 0.025, 0.020):
            self.world.configure(
                source_endpoint.target,
                source_endpoint.q_radians,
                target_xyz=source_endpoint.target_piece_xyz,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=True,
                upright_attachment=True,
            )
            q = source_endpoint.q_radians.copy()
            path = [q.copy()]
            failed = False
            waypoints = []
            hover_src = source_tcp.copy()
            hover_src[2] += hover_m
            hover_dst = dest_tcp.copy()
            hover_dst[2] += hover_m
            lift_steps = max(8, int(round(hover_m / 0.002)))
            across = dest_tcp[:2] - source_tcp[:2]
            across_steps = max(8, int(round(float(np.linalg.norm(across)) / 0.004)))
            for step in range(1, lift_steps + 1):
                point = source_tcp.copy()
                point[2] += hover_m * step / lift_steps
                waypoints.append(point)
            for step in range(1, across_steps + 1):
                alpha = step / across_steps
                waypoints.append(hover_src * (1 - alpha) + hover_dst * alpha)
            for step in range(1, lift_steps + 1):
                point = dest_tcp.copy()
                point[2] += hover_m * (1 - step / lift_steps)
                waypoints.append(point)
            for target in waypoints:
                solved = solve_axis_ik(
                    self.world,
                    target,
                    axis,
                    q,
                    position_tolerance=0.0008,
                    axis_tolerance_degrees=6.0,
                )
                if solved is None or not self.world.edge_valid(q, solved[0]):
                    failed = True
                    break
                q = solved[0]
                path.append(q.copy())
            if failed:
                continue
            resampled = resample_path(
                tuple(path),
                math.radians(float(config["edge_resolution_degrees"])),
            )
            robust = True
            for perturbation_seed in range(
                int(config["tolerance_replay_seeds"])
            ):
                self.world.configure(
                    source_endpoint.target,
                    source_endpoint.q_radians,
                    target_xyz=source_endpoint.target_piece_xyz,
                    excluded_square=excluded_square,
                    occupied_squares=occupied_squares,
                    attached=True,
                    upright_attachment=True,
                    perturbation_seed=perturbation_seed,
                )
                for start, end in zip(resampled, resampled[1:]):
                    if not self.world.edge_valid(start, end):
                        robust = False
                        break
                if not robust:
                    break
            if robust:
                return resampled
        return None

    def capture_bin_route(
        self,
        color: str,
        occupied_squares: set[str],
    ) -> JointTrajectory:
        occupied = set(occupied_squares)
        signature = occupancy_signature(occupied)
        cache_id = f"runtime_bin:{color}:{signature}"
        if cache_id in self.cache.trajectories:
            return self.cache.require(cache_id)
        baseline_entry = self.baseline.require(f"capture_bin:{color}")
        x, y = self.world.geometry.capture_bin(color)
        target_xyz = np.asarray(
            (
                x,
                y,
                float(self.world.geometry.board["nominal_top_z"]) + 0.003,
            )
        )
        baseline_exit = replace(
            baseline_entry,
            mode=MotionMode.PICKUP_EXIT,
            waypoints_degrees=tuple(reversed(baseline_entry.waypoints_degrees)),
            timestamps_seconds=tuple(
                baseline_entry.timestamps_seconds[-1] - value
                for value in reversed(baseline_entry.timestamps_seconds)
            ),
            checksum="",
        ).with_checksum()
        if self._validate(
            baseline_exit,
            target=f"bin:{color}",
            target_xyz=target_xyz,
            excluded_square=None,
            occupied_squares=occupied,
        ):
            entry = baseline_entry
        else:
            endpoint = choose_bin_endpoint(
                self.world,
                color,
                occupied_squares=occupied,
            )
            replanned_exit, _ = _plan_endpoint(
                self.world,
                endpoint,
                excluded_square=None,
                occupied_squares=occupied,
            )
            entry = replanned_exit.reversed_for_placement()
        runtime = replace(
            entry,
            trajectory_id=cache_id,
            mode=MotionMode.CAPTURE_BIN_ENTRY,
            checksum="",
        ).with_checksum()
        self.cache.add(runtime)
        self.cache.save(self.cache_path)
        return runtime
