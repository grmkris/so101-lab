"""Generate the exact engineered chess twin with Blender.

Run from the repository root:

    /Applications/Blender.app/Contents/MacOS/Blender --background \
      --python chess_system/assets/blender/generate_assets.py

The script deliberately builds the physical and simulated assets from simple,
overlapping printable solids. Slicers union the intersecting shells; simulator
collision geometry is generated separately from the same JSON dimensions.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "chess_system" / "config" / "chess_geometry.json"
OUT = ROOT / "chess_system" / "assets" / "generated"
PIECE_TYPES = ("pawn", "rook", "knight", "bishop", "queen", "king")

with CONFIG.open(encoding="utf-8") as handle:
    SPEC = json.load(handle)


def mm(value_m: float) -> float:
    """Blender uses metres; this helper only makes intent explicit."""

    return float(value_m)


def clear_scene() -> None:
    # ``object.delete`` does not select objects hidden by the export pipeline.
    # Remove datablocks directly so repeated headless runs are deterministic.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    # Materials are module-level singletons created before ``main``. Keep them
    # alive while clearing geometry from a previous invocation.
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        # Remove only orphaned data; Blender may still be iterating linked blocks.
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def material(name: str, rgba: tuple[float, float, float, float], metallic=0.0, roughness=0.45):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.metallic = metallic
    mat.roughness = roughness
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = rgba
        principled.inputs["Metallic"].default_value = metallic
        principled.inputs["Roughness"].default_value = roughness
    return mat


WHITE = material("piece_white", (0.88, 0.89, 0.84, 1.0), roughness=0.35)
BLACK = material("piece_black", (0.045, 0.055, 0.065, 1.0), roughness=0.30)
BOARD_LIGHT = material("board_light", (0.78, 0.70, 0.54, 1.0), roughness=0.65)
BOARD_DARK = material("board_dark", (0.18, 0.22, 0.20, 1.0), roughness=0.65)
BOARD_EDGE = material("board_edge", (0.07, 0.08, 0.09, 1.0), roughness=0.55)
TOOL_MAT = material("tool", (0.95, 0.36, 0.08, 1.0), roughness=0.40)
PAD_MAT = material("contact_pad", (0.08, 0.08, 0.08, 1.0), roughness=0.9)


def add_cylinder(name: str, radius: float, depth: float, z: float, vertices=48, mat=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=(0, 0, z))
    obj = bpy.context.object
    obj.name = name
    if mat:
        obj.data.materials.append(mat)
    return obj


def add_cube(name: str, size_xyz: tuple[float, float, float], xyz: tuple[float, float, float], mat=None):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=xyz)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size_xyz
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        obj.data.materials.append(mat)
    return obj


def add_cone(name: str, radius1: float, radius2: float, depth: float, z: float, vertices=32, mat=None):
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices, radius1=radius1, radius2=radius2, depth=depth, location=(0, 0, z)
    )
    obj = bpy.context.object
    obj.name = name
    if mat:
        obj.data.materials.append(mat)
    return obj


def add_uv_sphere(name: str, radius: float, xyz: tuple[float, float, float], mat=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=radius, location=xyz)
    obj = bpy.context.object
    obj.name = name
    if mat:
        obj.data.materials.append(mat)
    return obj


def join_objects(objects: list, name: str):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    objects[0].name = name
    return objects[0]


def add_top_marker(piece_type: str, mat) -> list:
    """Small type-specific marker on top of the grasp mast."""

    cap_z = float(SPEC["piece"]["total_height"]) - 0.002
    if piece_type == "pawn":
        return [add_uv_sphere("pawn_marker", 0.0020, (0, 0, cap_z), mat)]
    if piece_type == "rook":
        return [add_cube("rook_marker", (0.006, 0.006, 0.002), (0, 0, cap_z), mat)]
    if piece_type == "knight":
        obj = add_cone("knight_marker", 0.0035, 0.0, 0.004, cap_z, vertices=3, mat=mat)
        obj.rotation_euler.z = math.radians(90)
        return [obj]
    if piece_type == "bishop":
        return [add_cone("bishop_marker", 0.0035, 0.0, 0.004, cap_z, vertices=24, mat=mat)]
    if piece_type == "queen":
        return [add_cone("queen_marker", 0.0035, 0.0028, 0.002, cap_z, vertices=8, mat=mat)]
    return [
        add_cube("king_marker_v", (0.0025, 0.005, 0.004), (0, 0, cap_z), mat),
        add_cube("king_marker_h", (0.006, 0.0025, 0.002), (0, 0, cap_z + 0.001), mat),
    ]


def create_piece(piece_type: str, color: str):
    piece = SPEC["piece"]
    mat = WHITE if color == "white" else BLACK
    components = [
        add_cylinder("base", mm(piece["base_diameter"]) / 2, mm(piece["base_height"]), mm(piece["base_height"]) / 2, mat=mat),
        add_cylinder(
            "grasp_mast",
            mm(piece["grasp_mast_diameter"]) / 2,
            mm(piece["grasp_mast_height"]),
            mm(piece["grasp_mast_bottom_z"]) + mm(piece["grasp_mast_height"]) / 2,
            mat=mat,
        ),
    ]
    # Type band on the stump, below jaw height, mast-thin so stock jaws clear.
    band_sides = {"pawn": 32, "rook": 4, "knight": 3, "bishop": 24, "queen": 8, "king": 6}
    band_z = mm(piece["base_height"]) - 0.001
    components.append(
        add_cylinder(
            "identity_band",
            mm(piece["grasp_mast_diameter"]) / 2,
            0.002,
            band_z,
            vertices=band_sides[piece_type],
            mat=mat,
        )
    )
    components.extend(add_top_marker(piece_type, mat))
    return join_objects(components, f"{color}_{piece_type}")


def create_board():
    board = SPEC["board"]
    carrier_x, carrier_y, carrier_z = map(float, board["carrier_size"])
    objects = [add_cube("carrier", (carrier_x, carrier_y, carrier_z), (0, 0, -carrier_z / 2), BOARD_EDGE)]
    size = float(board["square_size"])
    for rank in range(8):
        for file_index in range(8):
            x = (rank - 3.5) * size
            y = (3.5 - file_index) * size
            mat = BOARD_LIGHT if (rank + file_index) % 2 == 0 else BOARD_DARK
            objects.append(add_cube(f"square_{file_index}_{rank}", (size, size, 0.0008), (x, y, 0.0004), mat))
    return objects


def create_extension(name: str, mirror: float):
    tool = SPEC["tool"]
    length = float(tool["extension_length"])
    tip_t = float(tool["tip_thickness"])
    tip_w = float(tool["tip_width"])
    components = [
        # Nominal keyed root. The physical runbook requires a jaw-fit coupon
        # before treating this root geometry as production-ready.
        add_cube("keyed_root", (0.010, 0.018, 0.014), (mirror * 0.005, 0, length + 0.007), TOOL_MAT),
        add_cube("extension", (tip_t, tip_w, length), (mirror * 0.006, 0, length / 2), TOOL_MAT),
        add_cube("pad", (0.0008, tip_w, float(tool["contact_height"])), (mirror * 0.0041, 0, 0.010), PAD_MAT),
    ]
    return join_objects(components, name)


def create_coupon():
    pitch = float(SPEC["validation"]["crowded_coupon_pitch"])
    plate = add_cube("coupon_plate", (pitch * 3 + 0.010, pitch * 3 + 0.010, 0.003), (0, 0, -0.0015), BOARD_EDGE)
    rings = [plate]
    for row in range(3):
        for col in range(3):
            x = (row - 1) * pitch
            y = (col - 1) * pitch
            ring = add_cylinder("coupon_target", 0.009, 0.0006, 0.0003, vertices=32, mat=BOARD_LIGHT)
            ring.location.x = x
            ring.location.y = y
            rings.append(ring)
    return join_objects(rings, "crowded_coupon")


def create_alignment_gauge():
    """Simple pivot-to-carrier setup gauge.

    The round pad is centered over the marked pan axis; the upright lip touches
    the carrier's near edge. It is a setup aid, not a structural arm mount.
    """

    distance = float(SPEC["board"]["carrier_near_x"])
    components = [
        add_cube("gauge_bar", (distance, 0.012, 0.003), (distance / 2, 0, 0.0015), TOOL_MAT),
        add_cylinder("pivot_pad", 0.007, 0.003, 0.0015, vertices=40, mat=TOOL_MAT),
        add_cube("board_stop", (0.003, 0.024, 0.012), (distance, 0, 0.006), TOOL_MAT),
    ]
    return join_objects(components, "pivot_to_board_gauge")


def select_only(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def export_stl(obj, path: Path) -> None:
    select_only(obj)
    bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=True, ascii_format=False)


def export_obj(obj, path: Path) -> None:
    select_only(obj)
    bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=True, export_materials=True)


def export_usd(obj, path: Path) -> None:
    select_only(obj)
    bpy.ops.wm.usd_export(
        filepath=str(path),
        selected_objects_only=True,
        export_materials=True,
    )


def build_preview_scene(piece_objects: dict[tuple[str, str], object]):
    # Keep one instance of every piece type, alternating colors.
    bpy.ops.object.select_all(action="DESELECT")
    for i, piece_type in enumerate(PIECE_TYPES):
        color = "white" if i % 2 == 0 else "black"
        original = piece_objects[(color, piece_type)]
        preview = original.copy()
        preview.data = original.data.copy()
        bpy.context.collection.objects.link(preview)
        preview.location = ((i - 2.5) * 0.030, -0.055, 0.004)
        preview.hide_render = False
    create_board()
    bpy.ops.object.camera_add(location=(0.27, -0.31, 0.25))
    camera = bpy.context.object
    bpy.context.scene.camera = camera
    direction = Vector((0, 0.0, 0.012)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.light_add(type="AREA", location=(0.0, -0.08, 0.28))
    bpy.context.object.data.energy = 55
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 0.30
    bpy.ops.object.light_add(type="AREA", location=(-0.20, -0.10, 0.12))
    bpy.context.object.data.energy = 25
    bpy.context.object.data.size = 0.20
    scene = bpy.context.scene
    # Blender 5.2 LTS exposes Eevee under the stable ``BLENDER_EEVEE`` id.
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(OUT / "previews" / "engineered_chess_set.png")
    scene.world.color = (0.025, 0.03, 0.04)
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -1.2
    bpy.ops.render.render(write_still=True)


def build_tool_preview():
    clear_scene()
    left = create_extension("fixed_extension_preview", -1.0)
    right = create_extension("moving_extension_preview", 1.0)
    left.location.x = -0.014
    left.location.y = -0.025
    right.location.x = 0.014
    right.location.y = -0.025
    coupon = create_coupon()
    coupon.location.y = 0.050
    add_cylinder("mast_fit_reference", float(SPEC["piece"]["grasp_mast_diameter"]) / 2, 0.042, 0.021, mat=WHITE).location.y = 0.005
    bpy.ops.object.camera_add(location=(0.24, -0.34, 0.24))
    camera = bpy.context.object
    bpy.context.scene.camera = camera
    camera.rotation_euler = (Vector((0, 0.015, 0.025)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.light_add(type="AREA", location=(0.0, -0.10, 0.25))
    bpy.context.object.data.energy = 55
    bpy.context.object.data.size = 0.22
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(OUT / "previews" / "tool_and_coupon.png")
    scene.world.color = (0.025, 0.03, 0.04)
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -1.0
    bpy.ops.render.render(write_still=True)


def main() -> None:
    for directory in ("stl", "obj", "usd", "previews"):
        (OUT / directory).mkdir(parents=True, exist_ok=True)
    clear_scene()
    piece_objects: dict[tuple[str, str], object] = {}
    for color in ("white", "black"):
        for piece_type in PIECE_TYPES:
            obj = create_piece(piece_type, color)
            piece_objects[(color, piece_type)] = obj
            export_stl(obj, OUT / "stl" / f"{piece_type}.stl") if color == "white" else None
            export_obj(obj, OUT / "obj" / f"{color}_{piece_type}.obj")
            export_usd(obj, OUT / "usd" / f"{color}_{piece_type}.usda")
            obj.hide_render = True
            obj.hide_viewport = True

    left = create_extension("fixed_finger_extension", -1.0)
    export_stl(left, OUT / "stl" / "fixed_finger_extension.stl")
    export_usd(left, OUT / "usd" / "fixed_finger_extension.usda")
    left.hide_render = True
    left.hide_viewport = True
    right = create_extension("moving_finger_extension", 1.0)
    export_stl(right, OUT / "stl" / "moving_finger_extension.stl")
    export_usd(right, OUT / "usd" / "moving_finger_extension.usda")
    right.hide_render = True
    right.hide_viewport = True
    coupon = create_coupon()
    export_stl(coupon, OUT / "stl" / "crowded_clearance_coupon.stl")
    coupon.hide_render = True
    coupon.hide_viewport = True
    gauge = create_alignment_gauge()
    export_stl(gauge, OUT / "stl" / "pivot_to_board_gauge.stl")
    gauge.hide_render = True
    gauge.hide_viewport = True

    # Save the editable source before adding presentation-only duplicates.
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "micro_chess.blend"))
    build_preview_scene(piece_objects)
    # USD is the Isaac visual source. The Isaac adapter authors physics schemas.
    bpy.ops.wm.usd_export(
        filepath=str(OUT / "usd" / "micro_chess_visual.usda"),
        export_materials=True,
        selected_objects_only=False,
    )
    build_tool_preview()
    print(f"generated micro-chess assets in {OUT}")


if __name__ == "__main__":
    main()
