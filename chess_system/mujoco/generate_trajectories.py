"""Generate and validate the all-square crowded-board trajectory library."""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from chess_system.mujoco.collision_world import ARM_JOINTS, CollisionWorld
from chess_system.mujoco.ik import (
    GraspEndpoint,
    SquareUnreachable,
    choose_bin_endpoint,
    choose_square_endpoint,
    solve_position_ik,
)
from chess_system.mujoco.rrt import PlanResult, RRTConnect, resample_path, shortcut_path
from chess_system.mujoco.trajectory import (
    JointTrajectory,
    MotionMode,
    TrajectoryLibrary,
    TrajectoryMetrics,
)


ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "chess_system" / "mujoco" / "generated"
DEFAULT_LIBRARY = GENERATED / "trajectory_library.json"
DEFAULT_REPORT = GENERATED / "trajectory_report.json"


def _vertical_escape_path(
    world: CollisionWorld,
    endpoint: GraspEndpoint,
    *,
    maximum_lift_m: float = 0.040,
) -> PlanResult | None:
    """Lift in 1 mm Cartesian increments until a direct ready edge is safe."""

    q = endpoint.q_radians.copy()
    path = [q.copy()]
    for millimeter in range(1, int(maximum_lift_m * 1000) + 1):
        target = endpoint.tcp_target_xyz + np.asarray(
            (0.0, 0.0, millimeter / 1000)
        )
        candidate = solve_position_ik(world, target, q)
        if candidate is None or not world.edge_valid(q, candidate):
            return None
        q = candidate
        path.append(q.copy())
        if world.edge_valid(q, world.ready):
            path.append(world.ready.copy())
            return PlanResult(tuple(path), 0, False)
    return None


def _timestamps(path: tuple[np.ndarray, ...], maximum_velocity: float, maximum_acceleration: float):
    if len(path) == 1:
        return (0.0,)
    segment_lengths = [
        float(np.max(np.abs(np.degrees(end - start))))
        for start, end in zip(path, path[1:])
    ]
    total_length = sum(segment_lengths)
    if total_length <= 1e-9:
        return tuple(0.0 for _ in path)
    duration = max(
        total_length / maximum_velocity + maximum_velocity / maximum_acceleration,
        2 * math.sqrt(total_length / maximum_acceleration),
    )
    timestamps = [0.0]
    accumulated = 0.0
    for length in segment_lengths:
        accumulated += length
        timestamps.append(duration * accumulated / total_length)
    return tuple(timestamps)


def _plan_endpoint(
    world: CollisionWorld,
    endpoint: GraspEndpoint,
    *,
    excluded_square: str | None,
    occupied_squares: set[str] | None = None,
    attached: bool = True,
    upright_attachment: bool = False,
    allow_rrt: bool = True,
) -> tuple[JointTrajectory, dict]:
    config = world.geometry.motion_planning
    world.configure(
        endpoint.target,
        endpoint.q_radians,
        target_xyz=endpoint.target_piece_xyz,
        excluded_square=excluded_square,
        occupied_squares=occupied_squares,
        attached=attached,
        upright_attachment=upright_attachment,
    )
    planner = RRTConnect(
        world.lower,
        world.upper,
        world.state_valid,
        world.edge_valid,
        step_radians=math.radians(float(config["rrt_step_degrees"])),
        goal_bias=float(config["goal_bias"]),
        maximum_iterations=int(config["maximum_iterations"]),
    )
    result = None
    attempt = 0
    selected_seed = None
    resampled = None
    tolerance_failures = []
    tolerance_count = int(config["tolerance_replay_seeds"])
    candidate_diagnostics = []
    world.configure(
        endpoint.target,
        endpoint.q_radians,
        target_xyz=endpoint.target_piece_xyz,
        excluded_square=excluded_square,
        occupied_squares=occupied_squares,
        attached=attached,
        upright_attachment=upright_attachment,
    )
    direct = (
        PlanResult((endpoint.q_radians.copy(), world.ready.copy()), 0, True)
        if world.edge_valid(endpoint.q_radians, world.ready)
        else None
    )
    escape = _vertical_escape_path(world, endpoint)
    def candidate_sources():
        if direct is not None:
            yield "direct", direct
        if escape is not None:
            yield "vertical_escape", escape
            # If nominal escape misses a perturbed obstacle, generate the same
            # Cartesian lift against that concrete tolerance world before
            # falling back to unconstrained joint-space search.
            for perturbation_seed in range(int(config["tolerance_replay_seeds"])):
                world.configure(
                    endpoint.target,
                    endpoint.q_radians,
                    target_xyz=endpoint.target_piece_xyz,
                    excluded_square=excluded_square,
                    occupied_squares=occupied_squares,
                    attached=attached,
                    upright_attachment=upright_attachment,
                    perturbation_seed=perturbation_seed,
                )
                robust_escape = _vertical_escape_path(world, endpoint)
                if robust_escape is not None:
                    yield f"vertical_escape:{perturbation_seed}", robust_escape
        if allow_rrt:
            for seed in config["attempt_seeds"]:
                yield int(seed), None

    for attempt, (seed_label, prepared_result) in enumerate(
        candidate_sources(), start=1
    ):
        world.configure(
            endpoint.target,
            endpoint.q_radians,
            target_xyz=endpoint.target_piece_xyz,
            excluded_square=excluded_square,
            occupied_squares=occupied_squares,
            attached=attached,
            upright_attachment=upright_attachment,
        )
        result = prepared_result or planner.plan(
            endpoint.q_radians, world.ready, seed=int(seed_label)
        )
        if result is None:
            candidate_diagnostics.append(
                {"seed": seed_label, "planning": "failed"}
            )
            continue
        shortened = (
            result.path
            if isinstance(seed_label, str)
            and seed_label.startswith("vertical_escape")
            else shortcut_path(
                result.path,
                world.edge_valid,
                attempts=int(config["shortcut_attempts"]),
                seed=(
                    9_991 + sum(ord(char) for char in seed_label)
                    if isinstance(seed_label, str)
                    else int(seed_label) + 10_000
                ),
            )
        )
        candidate = resample_path(
            shortened, math.radians(float(config["edge_resolution_degrees"]))
        )
        postprocess_valid = True
        for start, end in zip(candidate, candidate[1:]):
            if not world.edge_valid(start, end):
                postprocess_valid = False
                candidate_diagnostics.append(
                    {
                        "seed": seed_label,
                        "postprocess": "invalid",
                        "contacts": world.last_forbidden_contacts,
                    }
                )
                break
        if not postprocess_valid:
            continue

        current_failures = []
        for perturbation_seed in range(tolerance_count):
            world.configure(
                endpoint.target,
                endpoint.q_radians,
                target_xyz=endpoint.target_piece_xyz,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=attached,
                upright_attachment=upright_attachment,
                perturbation_seed=perturbation_seed,
            )
            if not world.state_valid(candidate[0]):
                current_failures.append(
                    {
                        "seed": perturbation_seed,
                        "phase": "start",
                        "contacts": world.last_forbidden_contacts,
                    }
                )
                continue
            for edge_index, (start, end) in enumerate(
                zip(candidate, candidate[1:])
            ):
                if not world.edge_valid(start, end):
                    current_failures.append(
                        {
                            "seed": perturbation_seed,
                            "phase": f"edge:{edge_index}",
                            "contacts": world.last_forbidden_contacts,
                        }
                    )
                    break
        candidate_diagnostics.append(
            {
                "seed": seed_label,
                "planning_iterations": result.iterations,
                "tolerance_failures": len(current_failures),
            }
        )
        if not current_failures:
            selected_seed = seed_label
            resampled = candidate
            tolerance_failures = current_failures
            break
    if result is None or resampled is None:
        raise SquareUnreachable(
            endpoint.target,
            f"robust planning failed for {endpoint.target}; "
            f"candidates={candidate_diagnostics}; contacts={world.last_forbidden_contacts}",
        )

    timestamps = _timestamps(
        resampled,
        float(config["maximum_velocity_degrees_s"]),
        float(config["maximum_acceleration_degrees_s2"]),
    )
    metrics = TrajectoryMetrics(
        planning_attempt=attempt,
        planning_iterations=result.iterations,
        raw_waypoints=len(result.path),
        final_waypoints=len(resampled),
        duration_seconds=float(timestamps[-1]),
        minimum_joint_margin_degrees=world.minimum_joint_margin_degrees(resampled),
        nominal_clearance_m=float(config["nominal_clearance"]),
        tolerance_replays=tolerance_count,
        tolerance_failures=len(tolerance_failures),
    )
    trajectory = JointTrajectory(
        trajectory_id=f"exit:{endpoint.target}",
        mode=MotionMode.PICKUP_EXIT,
        target=endpoint.target,
        scenario=(
            "empty_board_baseline"
            if not occupied_squares
            else "occupancy:" + ",".join(sorted(occupied_squares))
        ),
        joint_names=ARM_JOINTS,
        waypoints_degrees=tuple(
            tuple(round(float(value), 6) for value in np.degrees(q))
            for q in resampled
        ),
        timestamps_seconds=tuple(round(float(value), 6) for value in timestamps),
        gripper_normalized=tuple(20.0 for _ in resampled),
        attachment_enabled=tuple(True for _ in resampled),
        metrics=metrics,
    ).with_checksum()
    detail = {
        "target": endpoint.target,
        "tilt_degrees": endpoint.tilt_degrees,
        "endpoint_position_error_mm": endpoint.position_error_m * 1000,
        "endpoint_axis_error_degrees": endpoint.axis_error_degrees,
        "planner_direct": result.direct,
        "planner_seed": selected_seed,
        "planner_iterations": result.iterations,
        "raw_waypoints": len(result.path),
        "final_waypoints": len(resampled),
        "duration_seconds": timestamps[-1],
        "minimum_joint_margin_degrees": metrics.minimum_joint_margin_degrees,
        "tolerance_failures": tolerance_failures,
        "candidate_diagnostics": candidate_diagnostics,
        "checksum": trajectory.checksum,
    }
    return trajectory, detail


def generate() -> tuple[TrajectoryLibrary, dict]:
    started = time.perf_counter()
    world = CollisionWorld()
    library = TrajectoryLibrary(
        geometry_schema_version=int(world.geometry.raw["schema_version"]),
        generation={
            "planner": "deterministic_bidirectional_rrt_connect",
            "scenario": "empty_board_baseline_with_runtime_occupancy_replanning",
            "hybrid_attachment": True,
        },
    )
    details = []
    failures = []
    for square in (pose.square for pose in world.geometry.squares()):
        try:
            endpoint = choose_square_endpoint(
                world, square, occupied_squares=set()
            )
            exit_trajectory, detail = _plan_endpoint(
                world,
                endpoint,
                excluded_square=square,
                occupied_squares=set(),
            )
            library.add(exit_trajectory)
            library.add(exit_trajectory.reversed_for_placement())
            details.append(detail)
            print(
                f"{square}: tilt={endpoint.tilt_degrees:.0f}° "
                f"points={exit_trajectory.metrics.final_waypoints} "
                f"tolerance_failures={exit_trajectory.metrics.tolerance_failures}"
            )
        except Exception as exc:
            failures.append({"target": square, "error": str(exc)})
            print(f"{square}: FAILED {exc}")

    for color in ("white", "black"):
        target = f"bin:{color}"
        try:
            endpoint = choose_bin_endpoint(
                world, color, occupied_squares=set()
            )
            exit_trajectory, detail = _plan_endpoint(
                world,
                endpoint,
                excluded_square=None,
                occupied_squares=set(),
            )
            # Captures travel from shared ready into the bin.
            entry = exit_trajectory.reversed_for_placement()
            entry = replace(
                entry,
                trajectory_id=f"capture_bin:{color}",
                mode=MotionMode.CAPTURE_BIN_ENTRY,
                target=target,
                checksum="",
            ).with_checksum()
            library.add(entry)
            details.append(detail)
            print(
                f"{target}: tilt={endpoint.tilt_degrees:.0f}° "
                f"points={entry.metrics.final_waypoints} "
                f"tolerance_failures={entry.metrics.tolerance_failures}"
            )
        except Exception as exc:
            failures.append({"target": target, "error": str(exc)})
            print(f"{target}: FAILED {exc}")

    tolerance_failures = [
        detail["target"] for detail in details if detail["tolerance_failures"]
    ]
    report = {
        "status": "pass" if not failures and not tolerance_failures else "fail",
        "elapsed_seconds": time.perf_counter() - started,
        "square_exits": sum(key.startswith("exit:") and "bin:" not in key for key in library.trajectories),
        "square_entries": sum(key.startswith("entry:") for key in library.trajectories),
        "capture_bin_entries": sum(key.startswith("capture_bin:") for key in library.trajectories),
        "trajectory_count": len(library.trajectories),
        "failures": failures,
        "tolerance_failure_targets": tolerance_failures,
        "details": details,
    }
    return library, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    library, report = generate()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["status"] == "pass":
        library.save(args.library)
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
