"""MuJoCo collision world for crowded-board joint-space planning."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import mujoco
import numpy as np

from chess_system.geometry import load_geometry


ROOT = Path(__file__).resolve().parents[2]
REACH_CSV = ROOT / "chess_system" / "mujoco" / "generated" / "square_poses.csv"
DEFAULT_PLANNING_SCENE = ROOT / "sim" / "model" / "chess_planning_scene.xml"
ARM_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")


def _transform(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    result = np.eye(4)
    result[:3, :3] = rotation
    result[:3, 3] = translation
    return result


def _quat_from_matrix(rotation: np.ndarray) -> np.ndarray:
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.asarray(rotation, dtype=float).reshape(-1))
    return quat


class CollisionWorld:
    """Mutable planning scene with disabled visible pieces and proxy obstacles."""

    def __init__(self, scene: str | Path = DEFAULT_PLANNING_SCENE):
        self.geometry = load_geometry()
        self.model = mujoco.MjModel.from_xml_path(str(Path(scene).resolve()))
        self.data = mujoco.MjData(self.model)
        self.site_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_SITE, "chess_tcp"
        )
        self.joint_ids = np.asarray(
            [
                mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
                for name in ARM_JOINTS
            ]
        )
        self.qpos_addresses = np.asarray(
            [self.model.jnt_qposadr[joint_id] for joint_id in self.joint_ids]
        )
        self.dof_addresses = np.asarray(
            [self.model.jnt_dofadr[joint_id] for joint_id in self.joint_ids]
        )
        self.ranges = np.asarray(
            [self.model.jnt_range[joint_id] for joint_id in self.joint_ids]
        )
        margin = math.radians(float(self.geometry.robot["minimum_joint_margin_degrees"]))
        self.lower = self.ranges[:, 0] + margin
        self.upper = self.ranges[:, 1] - margin
        self.ready = np.radians(self.geometry.motion_planning["ready_joints_degrees"])

        carried_joint = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_JOINT, "planning_carried_piece_joint"
        )
        self.carried_qpos_address = int(self.model.jnt_qposadr[carried_joint])
        self.carried_dof_address = int(self.model.jnt_dofadr[carried_joint])
        self.carried_body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "planning_carried_piece"
        )
        self.carried_geom_ids = self._geom_ids_for_body(self.carried_body_id)
        self.actual_piece_geom_ids = [
            geom_id
            for geom_id in range(self.model.ngeom)
            if self._body_name_for_geom(geom_id).startswith("piece_")
        ]
        self.obstacle_body_ids = {
            square.square: mujoco.mj_name2id(
                self.model,
                mujoco.mjtObj.mjOBJ_BODY,
                f"planning_obstacle_{square.square}",
            )
            for square in self.geometry.squares()
        }
        self.obstacle_geom_ids = {
            square: self._geom_ids_for_body(body_id)
            for square, body_id in self.obstacle_body_ids.items()
        }
        self._original_body_pos = self.model.body_pos.copy()
        self._original_contype = self.model.geom_contype.copy()
        self._original_conaffinity = self.model.geom_conaffinity.copy()
        self.robot_body_ids = self._discover_robot_bodies()
        self._baseline_self_pairs = self._build_baseline_self_pairs()
        self.target_square = "a1"
        self.target_xy = np.zeros(2)
        self.attachment = np.eye(4)
        self.tcp_offset = np.zeros(3)
        self.attached = True
        self.upright_attachment = False
        self.last_forbidden_contacts: tuple[tuple[str, str], ...] = ()
        self.configure("a1", self.grasp_solutions()["a1"])

    def grasp_solutions(self) -> dict[str, np.ndarray]:
        with REACH_CSV.open(newline="", encoding="utf-8") as handle:
            return {
                row["square"]: np.radians(
                    [float(row[f"{name}_degrees"]) for name in ARM_JOINTS]
                )
                for row in csv.DictReader(handle)
            }

    def _geom_ids_for_body(self, body_id: int) -> list[int]:
        return [
            geom_id
            for geom_id in range(self.model.ngeom)
            if int(self.model.geom_bodyid[geom_id]) == body_id
        ]

    def _body_name_for_geom(self, geom_id: int) -> str:
        body_id = int(self.model.geom_bodyid[geom_id])
        return (
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, body_id)
            or "world"
        )

    def _geom_name(self, geom_id: int) -> str:
        return (
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
            or f"geom#{geom_id}"
        )

    def _discover_robot_bodies(self) -> set[int]:
        excluded_prefixes = (
            "piece_",
            "planning_",
            "capture_bin_",
            "chess_board",
        )
        result = set()
        for body_id in range(1, self.model.nbody):
            name = (
                mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, body_id)
                or ""
            )
            if name and not name.startswith(excluded_prefixes):
                result.add(body_id)
        return result

    def _set_enabled(self, geom_ids: list[int], enabled: bool) -> None:
        for geom_id in geom_ids:
            self.model.geom_contype[geom_id] = 1 if enabled else 0
            self.model.geom_conaffinity[geom_id] = 1 if enabled else 0

    def _build_baseline_self_pairs(self) -> set[tuple[int, int]]:
        for index, body_id in enumerate(self.obstacle_body_ids.values()):
            self.model.body_pos[body_id] = (100.0 + index, 100.0, 100.0)
        self.data.qpos[self.carried_qpos_address : self.carried_qpos_address + 3] = (
            100.0,
            100.0,
            100.0,
        )
        self.data.qpos[self.qpos_addresses] = self.ready
        mujoco.mj_forward(self.model, self.data)
        pairs = set()
        for body_id in self.robot_body_ids:
            parent = int(self.model.body_parentid[body_id])
            if parent in self.robot_body_ids:
                pairs.add(tuple(sorted((body_id, parent))))
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            first = int(self.model.geom_bodyid[contact.geom1])
            second = int(self.model.geom_bodyid[contact.geom2])
            if first in self.robot_body_ids and second in self.robot_body_ids:
                pairs.add(tuple(sorted((first, second))))
        self.model.body_pos[:] = self._original_body_pos
        return pairs

    def _tcp_transform(self) -> np.ndarray:
        return _transform(
            self.data.site_xmat[self.site_id].reshape(3, 3).copy(),
            self.data.site_xpos[self.site_id].copy(),
        )

    def _set_arm_only(self, q: np.ndarray) -> None:
        self.data.qpos[self.qpos_addresses] = q
        mujoco.mj_forward(self.model, self.data)

    def _set_carried_pose(self) -> None:
        if not self.attached:
            address = self.carried_qpos_address
            # High +X so it stays off the infinite floor and off the
            # (100+i, 100, 100) unused-obstacle pile.
            self.data.qpos[address : address + 3] = (250.0, 0.0, 250.0)
            self.data.qpos[address + 3 : address + 7] = (1.0, 0.0, 0.0, 0.0)
            return
        address = self.carried_qpos_address
        if self.upright_attachment:
            mast_center = (
                float(self.geometry.piece["grasp_mast_bottom_z"])
                + float(self.geometry.piece["grasp_mast_height"]) / 2
            )
            root = self.data.site_xpos[self.site_id].copy() + self.tcp_offset
            root[2] -= mast_center
            self.data.qpos[address : address + 3] = root
            self.data.qpos[address + 3 : address + 7] = (1.0, 0.0, 0.0, 0.0)
        else:
            world_piece = self._tcp_transform() @ self.attachment
            self.data.qpos[address : address + 3] = world_piece[:3, 3]
            self.data.qpos[address + 3 : address + 7] = _quat_from_matrix(
                world_piece[:3, :3]
            )
        self.data.qvel[self.carried_dof_address : self.carried_dof_address + 6] = 0

    def configure(
        self,
        target_square: str,
        grasp_q: np.ndarray,
        *,
        crowded: bool = True,
        attached: bool = True,
        perturbation_seed: int | None = None,
        target_xyz: np.ndarray | None = None,
        excluded_square: str | None = None,
        occupied_squares: set[str] | None = None,
        upright_attachment: bool = False,
    ) -> None:
        self.model.body_pos[:] = self._original_body_pos
        excluded = (
            target_square
            if excluded_square is None and target_square in self.obstacle_geom_ids
            else excluded_square
        )
        occupied = (
            set(self.obstacle_body_ids)
            if occupied_squares is None and crowded
            else set(occupied_squares or ())
        )
        for index, (square, body_id) in enumerate(self.obstacle_body_ids.items()):
            if square not in occupied or square == excluded:
                self.model.body_pos[body_id] = (100.0 + index, 100.0, 100.0)
        self.attached = attached
        self.upright_attachment = upright_attachment

        self.target_square = target_square
        if target_xyz is None:
            pose = self.geometry.square(target_square)
            target_xyz = np.asarray(
                (pose.x, pose.y, float(self.geometry.board["nominal_top_z"])),
                dtype=float,
            )
        else:
            target_xyz = np.asarray(target_xyz, dtype=float).copy()
        tcp_offset = np.zeros(3)
        if perturbation_seed is not None:
            config = self.geometry.motion_planning
            rng = np.random.default_rng(perturbation_seed)
            board_tolerance = float(config["board_piece_translation_tolerance"])
            tcp_tolerance = float(config["tcp_translation_tolerance"])
            board_shift = rng.uniform(-board_tolerance, board_tolerance, size=2)
            board_id = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_BODY, "chess_board"
            )
            self.model.body_pos[board_id, :2] += board_shift
            for name in ("capture_bin_white", "capture_bin_black"):
                body_id = mujoco.mj_name2id(
                    self.model, mujoco.mjtObj.mjOBJ_BODY, name
                )
                self.model.body_pos[body_id, :2] += board_shift
            for square, body_id in self.obstacle_body_ids.items():
                individual = rng.uniform(
                    -board_tolerance, board_tolerance, size=2
                )
                self.model.body_pos[body_id, :2] += board_shift + individual
                if square == excluded:
                    target_xyz[:2] += board_shift + individual
            if excluded is None:
                target_xyz[:2] += board_shift
            tcp_offset = rng.uniform(-tcp_tolerance, tcp_tolerance, size=3)

        self.target_xy = target_xyz[:2].copy()
        self._set_arm_only(np.asarray(grasp_q, dtype=float))
        piece_transform = np.eye(4)
        piece_transform[:3, 3] = target_xyz
        self.attachment = np.linalg.inv(self._tcp_transform()) @ piece_transform
        self.attachment[:3, 3] += tcp_offset
        self._set_carried_pose()
        mujoco.mj_forward(self.model, self.data)
        self.last_forbidden_contacts = ()

    def _is_robot_body(self, body_id: int) -> bool:
        return body_id in self.robot_body_ids

    def _is_obstacle_body(self, body_id: int) -> bool:
        name = (
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, body_id)
            or ""
        )
        return name.startswith("planning_obstacle_")

    def _is_board_or_bin(self, body_id: int, geom_id: int) -> bool:
        body = (
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, body_id)
            or ""
        )
        geom = self._geom_name(geom_id)
        return body == "chess_board" or body.startswith("capture_bin_") or geom == "floor"

    def _is_support_surface(self, geom_id: int) -> bool:
        name = self._geom_name(geom_id)
        return name == "board_carrier" or name.endswith("_floor")

    def _allow_carried_robot(self, robot_body: int) -> bool:
        name = (
            mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, robot_body)
            or ""
        )
        return name in ("gripper", "moving_jaw_so101_v1")

    def _allow_carried_board_rest(self) -> bool:
        root = self.data.xpos[self.carried_body_id]
        board_top = float(self.geometry.board["nominal_top_z"])
        return (
            np.linalg.norm(root[:2] - self.target_xy) <= 0.004
            and root[2] <= board_top + 0.006
        )

    def forbidden_contacts(self) -> tuple[tuple[str, str], ...]:
        forbidden = set()
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            geom1, geom2 = int(contact.geom1), int(contact.geom2)
            body1 = int(self.model.geom_bodyid[geom1])
            body2 = int(self.model.geom_bodyid[geom2])
            if body1 == body2:
                continue
            first_robot, second_robot = self._is_robot_body(body1), self._is_robot_body(body2)
            first_obstacle, second_obstacle = self._is_obstacle_body(body1), self._is_obstacle_body(body2)
            first_carried = body1 == self.carried_body_id
            second_carried = body2 == self.carried_body_id
            first_board = self._is_board_or_bin(body1, geom1)
            second_board = self._is_board_or_bin(body2, geom2)

            blocked = False
            if first_robot and second_robot:
                blocked = tuple(sorted((body1, body2))) not in self._baseline_self_pairs
            elif (first_robot and second_obstacle) or (second_robot and first_obstacle):
                blocked = True
            elif (first_robot and second_board) or (second_robot and first_board):
                blocked = True
            elif (first_carried and second_obstacle) or (second_carried and first_obstacle):
                blocked = True
            elif (first_carried and second_board) or (second_carried and first_board):
                support_geom = geom2 if first_carried else geom1
                blocked = not (
                    self._is_support_surface(support_geom)
                    and self._allow_carried_board_rest()
                )
            elif first_carried and second_robot:
                blocked = not self._allow_carried_robot(body2)
            elif second_carried and first_robot:
                blocked = not self._allow_carried_robot(body1)

            if blocked:
                forbidden.add(tuple(sorted((self._geom_name(geom1), self._geom_name(geom2)))))
        return tuple(sorted(forbidden))

    def set_state(self, q: np.ndarray) -> None:
        self._set_arm_only(np.asarray(q, dtype=float))
        self._set_carried_pose()
        mujoco.mj_forward(self.model, self.data)

    def state_valid(self, q: np.ndarray) -> bool:
        q = np.asarray(q, dtype=float)
        if np.any(q < self.lower) or np.any(q > self.upper):
            self.last_forbidden_contacts = (("joint_limits", "state"),)
            return False
        self.set_state(q)
        self.last_forbidden_contacts = self.forbidden_contacts()
        return not self.last_forbidden_contacts

    def edge_valid(self, start: np.ndarray, end: np.ndarray) -> bool:
        resolution = math.radians(
            float(self.geometry.motion_planning["edge_resolution_degrees"])
        )
        count = max(1, int(np.ceil(np.max(np.abs(end - start)) / resolution)))
        for index in range(1, count + 1):
            q = start + (end - start) * index / count
            if not self.state_valid(q):
                return False
        return True

    def minimum_joint_margin_degrees(self, path: tuple[np.ndarray, ...]) -> float:
        stack = np.asarray(path)
        lower = np.degrees(stack - self.ranges[:, 0]).min()
        upper = np.degrees(self.ranges[:, 1] - stack).min()
        return float(min(lower, upper))
