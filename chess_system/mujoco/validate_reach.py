"""Validate all 64 vertical grasp poses against the generated SO-101 MJCF.

This is the board-sizing gate: every square must admit a downward ``chess_tcp``
pose within Cartesian tolerance and with the configured joint-limit margin.
The separate hover/transition/contact-path gate remains physical-work-blocking
because near ranks need a curved approach that tilts before becoming vertical.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import mujoco
import numpy as np

from chess_system.geometry import load_geometry
from chess_system.mujoco.backend import DEFAULT_SCENE


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / "chess_system" / "mujoco" / "generated" / "reach_report.json"
DEFAULT_CSV = ROOT / "chess_system" / "mujoco" / "generated" / "square_poses.csv"
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")


def _skew(vector: np.ndarray) -> np.ndarray:
    x, y, z = vector
    return np.asarray(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))


def _solve_vertical_grasp(model, data, site_id, target, qpos_addresses, dof_addresses, ranges, geometry):
    target_axis = np.asarray((0.0, 0.0, -1.0))
    margin = math.radians(float(geometry.robot["minimum_joint_margin_degrees"]))
    tolerance = float(geometry.robot["ik_position_tolerance"])
    data.qpos[qpos_addresses] = ranges.mean(axis=1)
    data.qpos[5] = 0.8  # gripper open in the MJCF's native radians
    position_error = float("inf")
    axis_error = 180.0
    for iteration in range(600):
        mujoco.mj_forward(model, data)
        position_error_vector = target - data.site_xpos[site_id]
        current_axis = data.site_xmat[site_id].reshape(3, 3)[:, 0]
        position_error = float(np.linalg.norm(position_error_vector))
        axis_error = math.degrees(math.acos(float(np.clip(current_axis @ target_axis, -1.0, 1.0))))
        if position_error <= tolerance and axis_error <= 8.0:
            q = data.qpos[qpos_addresses].copy()
            lower_margin = np.degrees(q - ranges[:, 0])
            upper_margin = np.degrees(ranges[:, 1] - q)
            return {
                "success": True,
                "iterations": iteration,
                "position_error_m": position_error,
                "axis_error_degrees": axis_error,
                "joint_positions_degrees": np.degrees(q),
                "minimum_joint_margin_degrees": float(np.minimum(lower_margin, upper_margin).min()),
            }

        jac_position = np.zeros((3, model.nv))
        jac_rotation = np.zeros((3, model.nv))
        mujoco.mj_jacSite(model, data, jac_position, jac_rotation, site_id)
        axis_jacobian = -_skew(current_axis) @ jac_rotation[:, dof_addresses]
        orientation_weight = 0.25
        jacobian = np.vstack(
            (jac_position[:, dof_addresses], orientation_weight * axis_jacobian)
        )
        error = np.concatenate(
            (position_error_vector, orientation_weight * (target_axis - current_axis))
        )
        damping = 0.008
        delta = jacobian.T @ np.linalg.solve(
            jacobian @ jacobian.T + damping * np.eye(6), error
        )
        data.qpos[qpos_addresses] = np.clip(
            data.qpos[qpos_addresses] + np.clip(delta, -0.09, 0.09),
            ranges[:, 0] + margin,
            ranges[:, 1] - margin,
        )
    return {
        "success": False,
        "iterations": 600,
        "position_error_m": position_error,
        "axis_error_degrees": axis_error,
        "joint_positions_degrees": np.degrees(data.qpos[qpos_addresses].copy()),
        "minimum_joint_margin_degrees": 0.0,
    }


def validate(scene: str | Path = DEFAULT_SCENE) -> dict:
    geometry = load_geometry()
    model = mujoco.MjModel.from_xml_path(str(Path(scene).resolve()))
    data = mujoco.MjData(model)
    site_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "chess_tcp")
    if site_id < 0:
        raise RuntimeError("generated robot model does not contain chess_tcp")
    joint_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in JOINTS]
    qpos_addresses = np.asarray([model.jnt_qposadr[joint_id] for joint_id in joint_ids])
    dof_addresses = np.asarray([model.jnt_dofadr[joint_id] for joint_id in joint_ids])
    ranges = np.asarray([model.jnt_range[joint_id] for joint_id in joint_ids])

    # Other pieces are irrelevant to reach and would make every starting square
    # appear occupied. Tool/board contact is still retained.
    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        if name.startswith("piece_"):
            model.geom_contype[geom_id] = 0
            model.geom_conaffinity[geom_id] = 0

    conditioned_min, conditioned_max = map(float, geometry.robot["conditioned_radius_range"])
    board_top = float(geometry.board["nominal_top_z"])
    grasp_z = (
        board_top
        + float(geometry.piece["grasp_mast_bottom_z"])
        + float(geometry.piece["grasp_mast_height"]) / 2
    )
    rows = []
    radial_failures = []
    ik_failures = []
    contact_failures = []
    for square in geometry.squares(z=board_top):
        radial_pass = conditioned_min <= square.radius <= conditioned_max
        if not radial_pass:
            radial_failures.append(square.square)
        solution = _solve_vertical_grasp(
            model,
            data,
            site_id,
            np.asarray((square.x, square.y, grasp_z)),
            qpos_addresses,
            dof_addresses,
            ranges,
            geometry,
        )
        if not solution["success"]:
            ik_failures.append(square.square)

        board_contacts = []
        if solution["success"]:
            mujoco.mj_forward(model, data)
            for contact_id in range(data.ncon):
                contact = data.contact[contact_id]
                first = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom1) or ""
                second = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom2) or ""
                if "board_carrier" in (first, second):
                    board_contacts.append(f"{first}:{second}")
            if board_contacts:
                contact_failures.append(square.square)

        joint_degrees = solution.pop("joint_positions_degrees")
        row = {
            "square": square.square,
            "x_m": round(square.x, 6),
            "y_m": round(square.y, 6),
            "grasp_z_m": round(grasp_z, 6),
            "radius_m": round(square.radius, 6),
            "radial_gate": radial_pass,
            "vertical_grasp_ik": bool(solution["success"]),
            "position_error_mm": round(float(solution["position_error_m"]) * 1000, 4),
            "axis_error_degrees": round(float(solution["axis_error_degrees"]), 4),
            "minimum_joint_margin_degrees": round(float(solution["minimum_joint_margin_degrees"]), 4),
            "board_contacts": ";".join(board_contacts),
            "iterations": int(solution["iterations"]),
        }
        row.update({f"{name}_degrees": round(float(value), 5) for name, value in zip(JOINTS, joint_degrees, strict=True)})
        rows.append(row)

    passed = not radial_failures and not ik_failures and not contact_failures
    report = geometry.report()
    report.update(
        {
            "square_count": len(rows),
            "radial_failures": radial_failures,
            "vertical_grasp_ik_failures": ik_failures,
            "vertical_grasp_board_contact_failures": contact_failures,
            "status": "pass" if passed else "fail",
            "path_gate_status": "pending physical tool-root measurement and curved hover-path implementation",
            "note": "All-square vertical grasp sizing gate. Passing does not certify hover/transition paths or neighbor contact.",
            "squares": rows,
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, default=DEFAULT_SCENE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    report = validate(args.scene)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    fields = tuple(report["squares"][0])
    with args.csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report["squares"])
    print(json.dumps({key: value for key, value in report.items() if key != "squares"}, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
