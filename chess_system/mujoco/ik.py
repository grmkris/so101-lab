"""Collision-aware endpoint IK selection for squares and capture bins."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from collections.abc import Callable

import mujoco
import numpy as np
from scipy.optimize import least_squares

from chess_system.mujoco.collision_world import CollisionWorld


class SquareUnreachable(RuntimeError):
    """No collision-free way to act on ``square`` in the current occupancy.

    Carries the square because the fact is a property of that square and the
    surrounding pieces, not of any particular destination. Callers memoize on
    it: once a piece cannot be grasped or extracted, every move from that
    square in the same position fails identically, and rediscovering that per
    candidate move is the dominant cost in a game.

    Subclasses ``RuntimeError`` so existing fallback paths that catch
    ``RuntimeError`` keep working unchanged.
    """

    def __init__(self, square: str, message: str):
        super().__init__(message)
        self.square = square


@dataclass(frozen=True)
class GraspEndpoint:
    target: str
    q_radians: np.ndarray
    target_axis: np.ndarray
    target_piece_xyz: np.ndarray
    tcp_target_xyz: np.ndarray
    position_error_m: float
    axis_error_degrees: float
    tilt_degrees: float
    iterations: int


def _skew(vector: np.ndarray) -> np.ndarray:
    x, y, z = vector
    return np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))


def solve_axis_ik(
    world: CollisionWorld,
    tcp_target_xyz: np.ndarray,
    target_axis: np.ndarray,
    seed: np.ndarray,
    *,
    maximum_iterations: int = 700,
    position_tolerance: float = 0.003,
    axis_tolerance_degrees: float = 6.0,
) -> tuple[np.ndarray, float, float, int] | None:
    model, data = world.model, world.data
    data.qpos[world.qpos_addresses] = np.asarray(seed, dtype=float)
    tolerance = float(position_tolerance)
    for iteration in range(maximum_iterations):
        mujoco.mj_forward(model, data)
        current_axis = data.site_xmat[world.site_id].reshape(3, 3)[:, 0]
        position_error_vector = tcp_target_xyz - data.site_xpos[world.site_id]
        position_error = float(np.linalg.norm(position_error_vector))
        axis_error = math.degrees(
            math.acos(float(np.clip(current_axis @ target_axis, -1.0, 1.0)))
        )
        if position_error <= tolerance and axis_error <= axis_tolerance_degrees:
            return (
                data.qpos[world.qpos_addresses].copy(),
                position_error,
                axis_error,
                iteration,
            )
        jac_position = np.zeros((3, model.nv))
        jac_rotation = np.zeros((3, model.nv))
        mujoco.mj_jacSite(
            model, data, jac_position, jac_rotation, world.site_id
        )
        axis_jacobian = (
            -_skew(current_axis) @ jac_rotation[:, world.dof_addresses]
        )
        weight = 0.25
        jacobian = np.vstack(
            (jac_position[:, world.dof_addresses], weight * axis_jacobian)
        )
        error = np.concatenate(
            (position_error_vector, weight * (target_axis - current_axis))
        )
        delta = jacobian.T @ np.linalg.solve(
            jacobian @ jacobian.T + 0.008 * np.eye(6), error
        )
        data.qpos[world.qpos_addresses] = np.clip(
            data.qpos[world.qpos_addresses] + np.clip(delta, -0.09, 0.09),
            world.lower,
            world.upper,
        )
    return None


def solve_position_ik(
    world: CollisionWorld,
    tcp_target_xyz: np.ndarray,
    seed: np.ndarray,
    *,
    position_tolerance: float = 0.0008,
    maximum_iterations: int = 400,
) -> np.ndarray | None:
    """Position-only continuation used after the grasp orientation is secured."""

    model, data = world.model, world.data
    data.qpos[world.qpos_addresses] = np.asarray(seed, dtype=float)
    for _ in range(maximum_iterations):
        mujoco.mj_forward(model, data)
        error = tcp_target_xyz - data.site_xpos[world.site_id]
        if np.linalg.norm(error) <= position_tolerance:
            return data.qpos[world.qpos_addresses].copy()
        jac_position = np.zeros((3, model.nv))
        jac_rotation = np.zeros((3, model.nv))
        mujoco.mj_jacSite(
            model, data, jac_position, jac_rotation, world.site_id
        )
        jacobian = jac_position[:, world.dof_addresses]
        delta = jacobian.T @ np.linalg.solve(
            jacobian @ jacobian.T + 0.004 * np.eye(3), error
        )
        data.qpos[world.qpos_addresses] = np.clip(
            data.qpos[world.qpos_addresses] + np.clip(delta, -0.06, 0.06),
            world.lower,
            world.upper,
        )
    return None


def refine_axis_ik(
    world: CollisionWorld,
    tcp_target_xyz: np.ndarray,
    target_axis: np.ndarray,
    seed: np.ndarray,
) -> tuple[np.ndarray, float, float, int] | None:
    """Refine a valid coarse branch without letting endpoint errors compound."""

    model, data = world.model, world.data

    def residual(q):
        data.qpos[world.qpos_addresses] = q
        mujoco.mj_forward(model, data)
        current_axis = data.site_xmat[world.site_id].reshape(3, 3)[:, 0]
        return np.concatenate(
            (
                (data.site_xpos[world.site_id] - tcp_target_xyz) / 0.0005,
                (current_axis - target_axis) / 0.03,
            )
        )

    result = least_squares(
        residual,
        np.asarray(seed, dtype=float),
        bounds=(world.lower, world.upper),
        max_nfev=500,
        ftol=1e-11,
        xtol=1e-11,
        gtol=1e-11,
    )
    q = result.x
    data.qpos[world.qpos_addresses] = q
    mujoco.mj_forward(model, data)
    current_axis = data.site_xmat[world.site_id].reshape(3, 3)[:, 0]
    position_error = float(
        np.linalg.norm(data.site_xpos[world.site_id] - tcp_target_xyz)
    )
    axis_error = math.degrees(
        math.acos(float(np.clip(current_axis @ target_axis, -1.0, 1.0)))
    )
    if position_error > 0.0005 or axis_error > 5.0:
        return None
    return q, position_error, axis_error, int(result.nfev)


def _seed_value(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big")


def choose_endpoint(
    world: CollisionWorld,
    target: str,
    piece_xyz: np.ndarray,
    *,
    excluded_square: str | None,
    preferred_q: np.ndarray | None = None,
    occupied_squares: set[str] | None = None,
    attached: bool = True,
    upright_attachment: bool = False,
    axis_candidates: list[tuple[float, float]] | None = None,
    candidate_validator: Callable[[GraspEndpoint], bool] | None = None,
    on_candidate: Callable[[], None] | None = None,
) -> GraspEndpoint:
    geometry = world.geometry
    tcp_target = np.asarray(piece_xyz, dtype=float).copy()
    tcp_target[2] += (
        float(geometry.piece["grasp_mast_bottom_z"])
        + float(geometry.piece["grasp_mast_height"]) / 2
    )
    rng = np.random.default_rng(_seed_value(target))
    seeds = [world.ready, world.ranges.mean(axis=1)]
    if preferred_q is not None:
        seeds.insert(0, np.asarray(preferred_q, dtype=float))
        folded_escape = np.asarray(preferred_q, dtype=float).copy()
        folded_escape[1] += math.radians(12.0)
        folded_escape[2] -= math.radians(4.0)
        folded_escape[3] -= math.radians(4.0)
        folded_escape[4] = math.radians(-75.0 if piece_xyz[1] >= 0 else 75.0)
        seeds.insert(1, np.clip(folded_escape, world.lower, world.upper))
    seeds.extend(rng.uniform(world.lower, world.upper) for _ in range(64))
    # Prefer vertical. For the four innermost near-rank squares, a modest
    # baseward tilt avoids the real gripper/shoulder self-collision.
    candidates = axis_candidates or [
        (tilt, 180.0) for tilt in (0.0, 5.0, 10.0, 15.0, 20.0, 25.0)
    ]
    for tilt, yaw in candidates:
        # Each candidate runs a full seed sweep of IK solves, so this is the
        # granularity at which a caller's search budget can be honoured.
        if on_candidate is not None:
            on_candidate()
        angle = math.radians(tilt)
        yaw_radians = math.radians(yaw)
        axis = np.asarray(
            (
                math.sin(angle) * math.cos(yaw_radians),
                math.sin(angle) * math.sin(yaw_radians),
                -math.cos(angle),
            )
        )
        for seed in seeds:
            solved = solve_axis_ik(
                world,
                tcp_target,
                axis,
                seed,
                position_tolerance=0.003,
                axis_tolerance_degrees=6.0,
            )
            if solved is None:
                continue
            coarse_q, _, _, coarse_iterations = solved
            world.configure(
                target,
                coarse_q,
                target_xyz=piece_xyz,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=attached,
                upright_attachment=upright_attachment,
            )
            if not world.state_valid(coarse_q):
                continue
            refined = refine_axis_ik(
                world, tcp_target, axis, coarse_q
            )
            if refined is None:
                continue
            q, position_error, axis_error, refinement_iterations = refined
            world.configure(
                target,
                q,
                target_xyz=piece_xyz,
                excluded_square=excluded_square,
                occupied_squares=occupied_squares,
                attached=attached,
                upright_attachment=upright_attachment,
            )
            if not world.state_valid(q):
                continue
            iterations = coarse_iterations + refinement_iterations
            endpoint = GraspEndpoint(
                target=target,
                q_radians=q,
                target_axis=axis,
                target_piece_xyz=np.asarray(piece_xyz, dtype=float),
                tcp_target_xyz=tcp_target,
                position_error_m=position_error,
                axis_error_degrees=axis_error,
                tilt_degrees=tilt,
                iterations=iterations,
            )
            if candidate_validator is None or candidate_validator(endpoint):
                return endpoint
    contacts = world.last_forbidden_contacts
    raise SquareUnreachable(
        target,
        f"no collision-free grasp endpoint for {target}; last contacts={contacts}",
    )


def choose_square_endpoint(
    world: CollisionWorld,
    square: str,
    *,
    occupied_squares: set[str] | None = None,
    attached: bool = True,
    upright_attachment: bool = False,
    axis_candidates: list[tuple[float, float]] | None = None,
    candidate_validator: Callable[[GraspEndpoint], bool] | None = None,
    on_candidate: Callable[[], None] | None = None,
) -> GraspEndpoint:
    pose = world.geometry.square(square)
    piece_xyz = np.asarray(
        (pose.x, pose.y, float(world.geometry.board["nominal_top_z"])),
        dtype=float,
    )
    preferred = world.grasp_solutions().get(square)
    return choose_endpoint(
        world,
        square,
        piece_xyz,
        excluded_square=square,
        preferred_q=preferred,
        occupied_squares=occupied_squares,
        attached=attached,
        upright_attachment=upright_attachment,
        axis_candidates=axis_candidates,
        candidate_validator=candidate_validator,
        on_candidate=on_candidate,
    )


def choose_bin_endpoint(
    world: CollisionWorld,
    color: str,
    *,
    occupied_squares: set[str] | None = None,
    attached: bool = True,
    upright_attachment: bool = False,
) -> GraspEndpoint:
    x, y = world.geometry.capture_bin(color)
    piece_xyz = np.asarray(
        (
            x,
            y,
            float(world.geometry.board["nominal_top_z"]) + 0.003,
        )
    )
    return choose_endpoint(
        world,
        f"bin:{color}",
        piece_xyz,
        excluded_square=None,
        occupied_squares=occupied_squares,
        attached=attached,
        upright_attachment=upright_attachment,
    )
