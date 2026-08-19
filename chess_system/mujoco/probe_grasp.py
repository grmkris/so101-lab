"""One-square contact-grasp probe. Not the game path — measures whether a
piece actually leaves the board when the qpos latch is off."""

from __future__ import annotations

import json

import mujoco
import numpy as np

from chess_system.mujoco.trajectory_executor import PlannedMujocoChessBackend


def _contacts(executor, piece: str) -> list[dict]:
    rows = []
    piece_id = mujoco.mj_name2id(executor.model, mujoco.mjtObj.mjOBJ_BODY, piece)
    for index in range(executor.data.ncon):
        contact = executor.data.contact[index]
        body1 = int(executor.model.geom_bodyid[contact.geom1])
        body2 = int(executor.model.geom_bodyid[contact.geom2])
        if piece_id not in (body1, body2):
            continue
        force = np.zeros(6)
        mujoco.mj_contactForce(executor.model, executor.data, index, force)
        other = body2 if body1 == piece_id else body1
        rows.append(
            {
                "other": mujoco.mj_id2name(
                    executor.model, mujoco.mjtObj.mjOBJ_BODY, other
                ),
                "geom1": mujoco.mj_id2name(
                    executor.model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom1)
                ),
                "geom2": mujoco.mj_id2name(
                    executor.model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom2)
                ),
                "normal_n": float(force[0]),
                "dist_mm": float(contact.dist) * 1000,
            }
        )
    return rows


def _piece_z(executor, piece: str) -> float:
    body_id = mujoco.mj_name2id(executor.model, mujoco.mjtObj.mjOBJ_BODY, piece)
    return float(executor.data.xpos[body_id][2])


def _set_condim(model, names: tuple[str, ...], condim: int) -> None:
    for name in names:
        geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        if geom >= 0:
            model.geom_condim[geom] = condim


def _configure_physics(executor, *, condim: int, impratio: float) -> None:
    executor.model.opt.impratio = impratio
    executor.model.opt.noslip_iterations = 20
    tool = ("chess_tool_fixed", "chess_tool_moving")
    _set_condim(executor.model, tool, condim)
    for geom in range(executor.model.ngeom):
        name = mujoco.mj_id2name(executor.model, mujoco.mjtObj.mjOBJ_GEOM, geom) or ""
        if name.endswith("_mast"):
            executor.model.geom_condim[geom] = condim


def _disable_other_pieces(executor, keep: str) -> None:
    for body in range(executor.model.nbody):
        name = mujoco.mj_id2name(executor.model, mujoco.mjtObj.mjOBJ_BODY, body) or ""
        if name.startswith("piece_") and name != keep:
            executor._set_piece_collision(name, False)
            joint_id = int(executor.model.body_jntadr[body])
            address = int(executor.model.jnt_qposadr[joint_id])
            executor.data.qpos[address + 2] = -0.05


def probe(
    label: str,
    *,
    assist: bool,
    mute: bool,
    condim: int,
    impratio: float,
    isolated: bool = False,
    approach_open: bool = False,
    clamp: float = 20.0,
    use_library_transfer: bool = False,
) -> dict:
    backend = PlannedMujocoChessBackend()
    executor = backend.executor
    executor.assist_grasp = assist
    _configure_physics(executor, condim=condim, impratio=impratio)
    executor.reset_ready()
    executor._check_non_target_contacts = lambda: None
    peak_z = {"mm": 0.0}

    def _track():
        peak_z["mm"] = max(peak_z["mm"], (_piece_z(executor, piece) - board_z) * 1000)

    executor.frame_callback = _track

    source, target = "e2", "e4"
    occupied = set(backend._square_piece)
    transfer = executor.runtime_planner.transfer_route(source, target, occupied)
    source_q = np.radians(np.asarray(transfer.waypoints_degrees[0]))
    source_pose = executor.geometry.square(
        source, z=float(executor.geometry.board["nominal_top_z"])
    )
    _, entry = executor.runtime_planner.arm_routes_to_endpoint(
        source,
        source_q,
        np.asarray(source_pose.xyz()),
        occupied,
        excluded_square=source,
    )
    piece = backend._square_piece[source]
    board_z = float(executor.geometry.board["nominal_top_z"])
    target_pose = executor.geometry.square(target)
    if isolated:
        _disable_other_pieces(executor, piece)
        mujoco.mj_forward(executor.model, executor.data)
    if approach_open:
        from chess_system.mujoco.trajectory_executor import replace_trajectory

        entry = replace_trajectory(
            entry, gripper_normalized=tuple(100.0 for _ in entry.gripper_normalized)
        )
    z0 = _piece_z(executor, piece)

    if mute:
        executor._set_piece_collision(piece, False)
        address = backend._qpos_address(piece)
        executor.approach_piece = (piece, executor.data.qpos[address : address + 7].copy())
    else:
        executor.approach_piece = None
        executor._update_muted_approach_piece = lambda: None

    error = None
    z_after_approach = z_closed = z_lifted = z0
    contacts_closed = contacts_lifted = []
    try:
        executor.drive(entry)
        z_after_approach = _piece_z(executor, piece)
        if mute:
            executor._set_piece_collision(piece, True)
            executor.approach_piece = None
            executor._update_muted_approach_piece = lambda: None
        executor.set_gripper(clamp, seconds=0.8)
        contacts_closed = _contacts(executor, piece)
        z_closed = _piece_z(executor, piece)
        grip_closed = float(np.degrees(executor.data.qpos[executor.gripper_qpos]))
        axis_closed = executor.data.site_xmat[executor.tcp_site].reshape(3, 3)[:, 0].copy()
        executor.held_piece = piece
        if use_library_transfer:
            from chess_system.mujoco.trajectory_executor import replace_trajectory

            carry = replace_trajectory(
                transfer,
                gripper_normalized=tuple(clamp for _ in transfer.gripper_normalized),
            )
            executor.drive(carry)
        else:
            from chess_system.mujoco.collision_world import CollisionWorld
            from chess_system.mujoco.ik import solve_axis_ik

            tcp = executor.data.site_xpos[executor.tcp_site].copy()
            q = executor.data.qpos[executor.arm_qpos].copy()
            world = CollisionWorld()
            for millimetre in range(2, 21, 2):
                solved = solve_axis_ik(
                    world,
                    tcp + np.asarray((0.0, 0.0, millimetre / 1000)),
                    axis_closed,
                    q,
                    position_tolerance=0.001,
                    axis_tolerance_degrees=4.0,
                )
                if solved is None:
                    raise RuntimeError(f"no lift IK at {millimetre} mm")
                q = solved[0]
                executor.data.ctrl[:5] = q
                executor.data.ctrl[5] = executor._gripper_command(clamp)
                executor._step_for(0.12)
        z_lifted = _piece_z(executor, piece)
        contacts_lifted = _contacts(executor, piece)
        grip_lifted = float(np.degrees(executor.data.qpos[executor.gripper_qpos]))
        axis_lifted = executor.data.site_xmat[executor.tcp_site].reshape(3, 3)[:, 0]
        axis_change = float(
            np.degrees(np.arccos(np.clip(axis_closed @ axis_lifted, -1.0, 1.0)))
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        z_lifted = _piece_z(executor, piece)
        contacts_lifted = _contacts(executor, piece)

    lift_mm = (z_lifted - board_z) * 1000
    body_id = mujoco.mj_name2id(executor.model, mujoco.mjtObj.mjOBJ_BODY, piece)
    xy = executor.data.xpos[body_id][:2]
    xy_error_mm = float(np.linalg.norm(xy - np.asarray((target_pose.x, target_pose.y)))) * 1000
    jaw_contacts = [
        row
        for row in contacts_lifted
        if row["other"] in ("gripper", "moving_jaw_so101_v1")
    ]
    return {
        "label": label,
        "assist": assist,
        "mute": mute,
        "condim": condim,
        "impratio": impratio,
        "error": error,
        "z0_mm": (z0 - board_z) * 1000,
        "z_approach_mm": (z_after_approach - board_z) * 1000,
        "z_closed_mm": (z_closed - board_z) * 1000,
        "z_lifted_mm": lift_mm,
        "peak_z_mm": peak_z["mm"],
        "xy_error_to_e4_mm": xy_error_mm,
        "grip_closed_deg": locals().get("grip_closed"),
        "grip_lifted_deg": locals().get("grip_lifted"),
        "axis_change_deg": locals().get("axis_change"),
        "carried": peak_z["mm"] > 8.0 and bool(jaw_contacts),
        "contacts_closed": contacts_closed,
        "contacts_lifted": contacts_lifted,
        "closed_force_n": sum(abs(row["normal_n"]) for row in contacts_closed),
        "lifted_force_n": sum(abs(row["normal_n"]) for row in contacts_lifted),
    }


def main() -> None:
    variants = [
        (
            "lib-isolated",
            dict(
                assist=False,
                mute=False,
                condim=3,
                impratio=10.0,
                isolated=True,
                approach_open=True,
                clamp=0.0,
                use_library_transfer=True,
            ),
        ),
        (
            "lib-crowded",
            dict(
                assist=False,
                mute=False,
                condim=3,
                impratio=10.0,
                isolated=False,
                approach_open=True,
                clamp=0.0,
                use_library_transfer=True,
            ),
        ),
    ]
    results = []
    for label, kwargs in variants:
        print(f"\n=== {label} ===", flush=True)
        row = probe(label, **kwargs)
        results.append(row)
        print(
            json.dumps(
                {k: v for k, v in row.items() if k not in ("contacts_closed", "contacts_lifted")},
                indent=2,
            ),
            flush=True,
        )
        print("contacts_closed", row["contacts_closed"], flush=True)
        print("contacts_lifted", row["contacts_lifted"], flush=True)
    print("\n=== SUMMARY ===")
    for row in results:
        print(
            f"{row['label']:20} carried={row['carried']!s:5} "
            f"peak={row.get('peak_z_mm', 0):.1f}mm endz={row['z_lifted_mm']:.1f}mm "
            f"xy={row.get('xy_error_to_e4_mm', 0):.1f}mm force={row['closed_force_n']:.2f}N "
            f"err={row['error']}"
        )


if __name__ == "__main__":
    main()
