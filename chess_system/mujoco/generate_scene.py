"""Generate the SO-101 micro-chess MJCF scene from the shared manifest."""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from chess_system.geometry import FILES, RANKS, load_geometry
from chess_system.mujoco.tool_mount import solve_stock_mount, solve_tool_mount


ROOT = Path(__file__).resolve().parents[2]
BASE_ROBOT = ROOT / "sim" / "model" / "so101_new_calib.xml"
ROBOT_OUT = ROOT / "sim" / "model" / "so101_chess.xml"
SCENE_OUT = ROOT / "sim" / "model" / "chess_scene.xml"
PLANNING_SCENE_OUT = ROOT / "sim" / "model" / "chess_planning_scene.xml"
TOOL_MOUNT_OUT = ROOT / "chess_system" / "mujoco" / "generated" / "tool_mount.json"

BACK_RANK = ("rook", "knight", "bishop", "queen", "king", "bishop", "knight", "rook")


def _augment_robot_model() -> None:
    """Place ``chess_tcp`` on the jaws that actually close.

    With ``use_finger_extensions`` the 20 mm printed pads are mounted on the
    moving/static jaws. Without it the stock SO-101 meshes are the tool.
    """

    geometry = load_geometry()
    use_extensions = bool(geometry.tool.get("use_finger_extensions", True))
    if use_extensions:
        mount = solve_tool_mount(
            BASE_ROBOT,
            mast_diameter=float(geometry.piece["grasp_mast_diameter"]),
            mast_height=float(geometry.piece["grasp_mast_height"]),
            tip_thickness=float(geometry.tool["tip_thickness"]),
            extension_length=float(geometry.tool["extension_length"]),
            open_separation=(
                float(geometry.tool["maximum_open_outer_width"])
                - float(geometry.tool["tip_thickness"])
            ),
        )
    else:
        mount = solve_stock_mount(
            BASE_ROBOT,
            neck_width=float(geometry.piece["grasp_mast_diameter"]),
            approach_clearance=float(geometry.tool.get("approach_clearance", 0.004)),
        )

    tree = ET.parse(BASE_ROBOT)
    root = tree.getroot()
    gripper = root.find(".//body[@name='gripper']")
    if gripper is None:
        raise RuntimeError("gripper body missing from SO-101 model")
    jaw = gripper.find("body[@name='moving_jaw_so101_v1']")
    if jaw is None:
        raise RuntimeError("moving jaw body missing from SO-101 model")

    attached = []
    if use_extensions:
        tip_half_thickness = float(geometry.tool["tip_thickness"]) / 2
        tip_half_width = float(geometry.tool["tip_width"]) / 2
        extension = float(geometry.tool["extension_length"])
        size = f"{tip_half_thickness:.6f} {tip_half_width:.6f} {extension / 2:.6f}"
        centre_z = mount.jaw_tip_z - extension / 2
        attached.append(
            ET.Element(
                "geom",
                {
                    "name": "chess_tool_fixed",
                    "type": "box",
                    "pos": f"{mount.fixed_x:.6f} {mount.tcp_pos[1]:.6f} {centre_z:.6f}",
                    "size": size,
                    "rgba": "1.0 0.25 0.0 1",
                    "mass": "0.009",
                    "friction": "1.4 0.02 0.001",
                    "group": "2",
                },
            )
        )
        jaw.append(
            ET.Element(
                "geom",
                {
                    "name": "chess_tool_moving",
                    "type": "box",
                    "pos": " ".join(f"{v:.6f}" for v in mount.moving_local_pos),
                    "quat": " ".join(f"{v:.6f}" for v in mount.moving_local_quat),
                    "size": size,
                    "rgba": "1.0 0.25 0.0 1",
                    "mass": "0.009",
                    "friction": "1.4 0.02 0.001",
                    "group": "2",
                },
            )
        )

    tcp = ET.Element(
        "site",
        {
            "name": "chess_tcp",
            "pos": " ".join(f"{v:.6f}" for v in mount.tcp_pos),
            "quat": "0.707107 0 0.707107 0",
            "size": "0.004",
            "rgba": "0.1 0.9 0.2 0.8",
            "group": "4",
        },
    )
    wrist_cam = ET.Element(
        "camera",
        {
            "name": "wrist_cam",
            "pos": "0.020 -0.045 -0.030",
            "quat": "0.707107 0 0.707107 0",
            "fovy": "62",
        },
    )

    moving_jaw_index = next(
        (
            i
            for i, child in enumerate(gripper)
            if child.tag == "body" and child.get("name") == "moving_jaw_so101_v1"
        ),
        len(gripper),
    )
    for element in (*attached, tcp, wrist_cam):
        gripper.insert(moving_jaw_index, element)
        moving_jaw_index += 1

    ET.indent(tree, space="  ")
    tree.write(ROBOT_OUT, encoding="utf-8", xml_declaration=True)
    # Consumers must not re-derive these; the working band is a 7 deg slice of
    # a 110 deg joint and getting it wrong sweeps the tool through the board.
    TOOL_MOUNT_OUT.parent.mkdir(parents=True, exist_ok=True)
    TOOL_MOUNT_OUT.write_text(
        json.dumps(
            {
                "closed_angle_radians": mount.closed_angle,
                "grip_angle_radians": mount.grip_angle,
                "open_angle_radians": mount.open_angle,
                "separation_at_grip_m": mount.separation_at_grip,
                "separation_when_closed_m": mount.separation_when_closed,
                "jaw_tip_z_m": mount.jaw_tip_z,
                "tcp_pos_m": list(mount.tcp_pos),
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"tool mount: grip {math.degrees(mount.grip_angle):.2f} deg, "
        f"separation {mount.separation_at_grip * 1000:.2f} mm, "
        f"closed {mount.separation_when_closed * 1000:.2f} mm, "
        f"open {math.degrees(mount.open_angle):.2f} deg"
    )


def _piece_geoms(
    piece_type: str,
    color: str,
    mass: float,
    name: str,
    *,
    collidable: bool,
) -> str:
    geometry = load_geometry()
    piece = geometry.piece
    base_radius = float(piece["base_diameter"]) / 2
    base_half_height = float(piece["base_height"]) / 2
    mast_half_width = float(piece["grasp_mast_diameter"]) / 2
    mast_half_depth = float(piece.get("grasp_neck_depth", piece["grasp_mast_diameter"])) / 2
    mast_half_height = float(piece["grasp_mast_height"]) / 2
    mast_center = float(piece["grasp_mast_bottom_z"]) + mast_half_height
    use_extensions = bool(geometry.tool.get("use_finger_extensions", True))
    rgba = "0.88 0.89 0.84 1" if color == "white" else "0.045 0.055 0.065 1"
    cap_z = float(piece["total_height"]) - 0.002
    marker = {
        "pawn": f'<geom name="{{n}}_marker" type="sphere" pos="0 0 {cap_z:.3f}" size="0.002" rgba="{{c}}" contype="0" conaffinity="0"/>',
        "rook": f'<geom name="{{n}}_marker" type="box" pos="0 0 {cap_z:.3f}" size="0.003 0.003 0.001" rgba="{{c}}" contype="0" conaffinity="0"/>',
        "knight": f'<geom name="{{n}}_marker" type="ellipsoid" pos="0 0 {cap_z:.3f}" size="0.0035 0.0025 0.002" rgba="{{c}}" contype="0" conaffinity="0"/>',
        "bishop": f'<geom name="{{n}}_marker" type="cone" pos="0 0 {cap_z:.3f}" size="0.0035 0.002" rgba="{{c}}" contype="0" conaffinity="0"/>',
        "queen": f'<geom name="{{n}}_marker" type="cylinder" pos="0 0 {cap_z:.3f}" size="0.0035 0.001" rgba="{{c}}" contype="0" conaffinity="0"/>',
        "king": f'<geom name="{{n}}_marker" type="box" pos="0 0 {cap_z:.3f}" size="0.003 0.0025 0.002" rgba="{{c}}" contype="0" conaffinity="0"/>',
    }[piece_type]
    # MuJoCo has no cone primitive geom in older builds. Use cylinders for the
    # collision/visual twin and keep detailed silhouettes in Blender/Isaac.
    marker = marker.replace('type="cone"', 'type="cylinder"')
    contact = "" if collidable else ' contype="0" conaffinity="0"'
    return "\n".join(
        [
            f'<geom name="{name}_base" type="cylinder" pos="0 0 {base_half_height:.6f}" size="{base_radius:.6f} {base_half_height:.6f}" mass="{mass * 0.85:.6f}" rgba="{rgba}" friction="0.9 0.01 0.001"{contact}/>',
            (
                f'<geom name="{name}_mast" type="cylinder" pos="0 0 {mast_center:.6f}" '
                f'size="{mast_half_width:.6f} {mast_half_height:.6f}" mass="{mass * 0.15:.6f}" '
                f'rgba="{rgba}"{contact}/>'
                if use_extensions
                else (
                    f'<geom name="{name}_mast" type="box" pos="0 0 {mast_center:.6f}" '
                    f'size="{mast_half_width:.6f} {mast_half_depth:.6f} {mast_half_height:.6f}" '
                    f'mass="{mass * 0.15:.6f}" rgba="{rgba}" friction="1.2 0.02 0.001"{contact}/>'
                )
            ),
            marker.format(n=name, c=rgba),
        ]
    )


def _piece_bodies(*, collidable: bool) -> str:
    geometry = load_geometry()
    board_z = float(geometry.board["nominal_top_z"])
    mass = float(geometry.piece["target_mass"])
    bodies: list[str] = []
    for color, pawn_rank, home_rank in (("white", "2", "1"), ("black", "7", "8")):
        for file_name in FILES:
            square = geometry.square(f"{file_name}{pawn_rank}")
            name = f"piece_{color}_pawn_{file_name}"
            bodies.append(
                f'<body name="{name}" pos="{square.x:.6f} {square.y:.6f} {board_z:.6f}">\n'
                f'  <freejoint name="{name}_joint"/>\n  {_piece_geoms("pawn", color, mass, name, collidable=collidable)}\n</body>'
            )
        for file_name, piece_type in zip(FILES, BACK_RANK, strict=True):
            square = geometry.square(f"{file_name}{home_rank}")
            name = f"piece_{color}_{piece_type}_{file_name}"
            bodies.append(
                f'<body name="{name}" pos="{square.x:.6f} {square.y:.6f} {board_z:.6f}">\n'
                f'  <freejoint name="{name}_joint"/>\n  {_piece_geoms(piece_type, color, mass, name, collidable=collidable)}\n</body>'
            )
    return "\n".join(bodies)


def _squares() -> str:
    geometry = load_geometry()
    z = float(geometry.board["nominal_top_z"]) + 0.00025
    geoms = []
    for rank_index, rank in enumerate(RANKS):
        for file_index, file_name in enumerate(FILES):
            pose = geometry.square(f"{file_name}{rank}")
            rgba = "0.78 0.70 0.54 1" if (rank_index + file_index) % 2 == 0 else "0.18 0.22 0.20 1"
            geoms.append(
                f'<geom name="square_{file_name}{rank}" type="box" pos="{pose.x:.6f} {pose.y:.6f} {z:.6f}" '
                f'size="0.0125 0.0125 0.00025" rgba="{rgba}" contype="0" conaffinity="0" group="2"/>'
            )
    return "\n".join(geoms)


def _planning_proxies(*, enabled: bool) -> str:
    """Invisible planning bodies, compile-time enabled only in the planning scene."""

    geometry = load_geometry()
    board_z = float(geometry.board["nominal_top_z"])
    clearance = float(geometry.motion_planning["nominal_clearance"])
    piece = geometry.piece
    base_radius = float(piece["base_diameter"]) / 2 + clearance
    base_half_height = float(piece["base_height"]) / 2 + clearance / 2
    upper_radius = float(piece["maximum_upper_width"]) / 2 + clearance
    mast_half_height = float(piece["grasp_mast_height"]) / 2 + clearance / 2
    mast_center = float(piece["grasp_mast_bottom_z"]) + float(piece["grasp_mast_height"]) / 2
    bodies = []
    contact = (
        'contype="1" conaffinity="1"'
        if enabled
        else 'contype="0" conaffinity="0"'
    )
    for square in geometry.squares():
        bodies.append(
            f'''<body name="planning_obstacle_{square.square}" pos="{square.x:.6f} {square.y:.6f} {board_z:.6f}">
      <geom name="planning_obstacle_{square.square}_base" type="cylinder" pos="0 0 {base_half_height:.6f}" size="{base_radius:.6f} {base_half_height:.6f}" {contact} group="5" rgba="0 0 0 0"/>
      <geom name="planning_obstacle_{square.square}_upper" type="cylinder" pos="0 0 {mast_center:.6f}" size="{upper_radius:.6f} {mast_half_height:.6f}" {contact} group="5" rgba="0 0 0 0"/>
    </body>'''
        )
    bodies.append(
        f'''<body name="planning_carried_piece" pos="0 0 -1">
      <freejoint name="planning_carried_piece_joint"/>
      <geom name="planning_carried_piece_base" type="cylinder" pos="0 0 {base_half_height:.6f}" size="{base_radius:.6f} {base_half_height:.6f}" mass="0.010" {contact} group="5" rgba="0 0 0 0"/>
      <geom name="planning_carried_piece_upper" type="cylinder" pos="0 0 {mast_center:.6f}" size="{upper_radius:.6f} {mast_half_height:.6f}" mass="0.002" {contact} group="5" rgba="0 0 0 0"/>
    </body>'''
    )
    return "\n".join(bodies)


def _scene_xml(*, planning: bool = False) -> str:
    geometry = load_geometry()
    board = geometry.board
    carrier_x, carrier_y, carrier_z = map(float, board["carrier_size"])
    carrier_center_x = float(board["carrier_near_x"]) + carrier_x / 2
    board_top = float(board["nominal_top_z"])
    carrier_center_z = board_top - carrier_z / 2
    white_bin = geometry.capture_bin("white")
    black_bin = geometry.capture_bin("black")
    white_tray = board["discard_tray_centers"]["white"]
    black_tray = board["discard_tray_centers"]["black"]
    bin_x, bin_y = map(float, board["capture_bin_inner_size"])
    bin_h = float(board["capture_bin_height"])
    tray_pitch = float(board["discard_tray_pitch"])
    tray_cols = int(board["discard_tray_columns"])
    tray_rows = -(-int(board["discard_tray_capacity"]) // tray_cols)
    tray_x = tray_cols * tray_pitch
    tray_y = tray_rows * tray_pitch
    tray_h = float(board["discard_tray_wall_height"])

    def tray_geoms(color: str) -> str:
        rgba = "0.62 0.63 0.60 1" if color == "white" else "0.10 0.11 0.13 1"
        return "\n".join(
            [
                f'<geom name="discard_tray_{color}_floor" type="box" pos="0 0 0.0015" size="{tray_x/2:.6f} {tray_y/2:.6f} 0.0015" rgba="{rgba}"/>',
                f'<geom name="discard_tray_{color}_wall_x_pos" type="box" pos="{tray_x/2:.6f} 0 {tray_h/2:.6f}" size="0.001 {tray_y/2:.6f} {tray_h/2:.6f}" rgba="{rgba}"/>',
                f'<geom name="discard_tray_{color}_wall_x_neg" type="box" pos="{-tray_x/2:.6f} 0 {tray_h/2:.6f}" size="0.001 {tray_y/2:.6f} {tray_h/2:.6f}" rgba="{rgba}"/>',
                f'<geom name="discard_tray_{color}_wall_y_pos" type="box" pos="0 {tray_y/2:.6f} {tray_h/2:.6f}" size="{tray_x/2:.6f} 0.001 {tray_h/2:.6f}" rgba="{rgba}"/>',
                f'<geom name="discard_tray_{color}_wall_y_neg" type="box" pos="0 {-tray_y/2:.6f} {tray_h/2:.6f}" size="{tray_x/2:.6f} 0.001 {tray_h/2:.6f}" rgba="{rgba}"/>',
            ]
        )

    def bin_geoms(color: str) -> str:
        rgba = "0.75 0.76 0.72 1" if color == "white" else "0.04 0.05 0.06 1"
        return "\n".join(
            [
                f'<geom name="capture_bin_{color}_floor" type="box" pos="0 0 0.0015" size="{bin_x/2+0.002:.6f} {bin_y/2+0.002:.6f} 0.0015" rgba="{rgba}"/>',
                f'<geom name="capture_bin_{color}_wall_x_pos" type="box" pos="{bin_x/2+0.001:.6f} 0 {bin_h/2:.6f}" size="0.001 {bin_y/2+0.002:.6f} {bin_h/2:.6f}" rgba="{rgba}"/>',
                f'<geom name="capture_bin_{color}_wall_x_neg" type="box" pos="{-bin_x/2-0.001:.6f} 0 {bin_h/2:.6f}" size="0.001 {bin_y/2+0.002:.6f} {bin_h/2:.6f}" rgba="{rgba}"/>',
                f'<geom name="capture_bin_{color}_wall_y_pos" type="box" pos="0 {bin_y/2+0.001:.6f} {bin_h/2:.6f}" size="{bin_x/2:.6f} 0.001 {bin_h/2:.6f}" rgba="{rgba}"/>',
                f'<geom name="capture_bin_{color}_wall_y_neg" type="box" pos="0 {-bin_y/2-0.001:.6f} {bin_h/2:.6f}" size="{bin_x/2:.6f} 0.001 {bin_h/2:.6f}" rgba="{rgba}"/>',
            ]
        )
    return f'''<?xml version="1.0"?>
<mujoco model="so101_micro_chess">
  <include file="so101_chess.xml"/>
  <option timestep="0.002" integrator="implicitfast" cone="elliptic" iterations="80"/>
  <statistic center="0.15 0 0.10" extent="0.48"/>
  <visual>
    <headlight diffuse="0.65 0.65 0.65" ambient="0.30 0.30 0.30" specular="0.15 0.15 0.15"/>
    <global azimuth="155" elevation="-28" offwidth="1280" offheight="960"/>
  </visual>
  <worldbody>
    <light name="key" pos="0.1 -0.2 0.55" dir="0.1 0.2 -1" directional="true" diffuse="0.8 0.8 0.8"/>
    <light name="fill" pos="0.35 0.30 0.30" dir="-0.2 -0.2 -1" diffuse="0.45 0.45 0.45"/>
    <geom name="floor" type="plane" pos="0 0 {board_top - carrier_z:.6f}" size="1 1 0.01" rgba="0.08 0.10 0.12 1" friction="1 0.01 0.001"/>
    <body name="chess_board" pos="0 0 0">
      <geom name="board_carrier" type="box" pos="{carrier_center_x:.6f} 0 {carrier_center_z:.6f}" size="{carrier_x/2:.6f} {carrier_y/2:.6f} {carrier_z/2:.6f}" rgba="0.07 0.08 0.09 1" friction="1.1 0.01 0.001"/>
      {_squares()}
    </body>
    <body name="capture_bin_white" pos="{white_bin[0]:.6f} {white_bin[1]:.6f} {board_top:.6f}">
      {bin_geoms("white")}
    </body>
    <body name="capture_bin_black" pos="{black_bin[0]:.6f} {black_bin[1]:.6f} {board_top:.6f}">
      {bin_geoms("black")}
    </body>
    <body name="discard_tray_white" pos="{white_tray[0]:.6f} {white_tray[1]:.6f} {board_top:.6f}">
      {tray_geoms("white")}
    </body>
    <body name="discard_tray_black" pos="{black_tray[0]:.6f} {black_tray[1]:.6f} {board_top:.6f}">
      {tray_geoms("black")}
    </body>
    {_piece_bodies(collidable=not planning)}
    {_planning_proxies(enabled=planning)}
    <camera name="workspace_cam" mode="targetbody" target="chess_board" pos="0.18 -0.42 0.48" fovy="48"/>
  </worldbody>
  <equality>
    <weld name="chess_piece_latch" body1="gripper" body2="planning_carried_piece" active="false"/>
  </equality>
</mujoco>
'''


def main() -> None:
    _augment_robot_model()
    SCENE_OUT.write_text(_scene_xml(planning=False), encoding="utf-8")
    PLANNING_SCENE_OUT.write_text(_scene_xml(planning=True), encoding="utf-8")
    print(f"generated {ROBOT_OUT.relative_to(ROOT)}")
    print(f"generated {SCENE_OUT.relative_to(ROOT)}")
    print(f"generated {PLANNING_SCENE_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
