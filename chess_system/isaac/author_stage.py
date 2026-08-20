"""Author an Isaac/PhysX micro-chess stage from the shared geometry contract.

Run inside the pinned Isaac environment. The script uses primitive compound
colliders for stable contact and references Blender geometry only as visuals.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "chess_system" / "config" / "chess_geometry.json"
BACK_RANK = ("rook", "knight", "bishop", "queen", "king", "bishop", "knight", "rook")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
    except ImportError as exc:
        raise SystemExit("run author_stage.py inside the Isaac Sim/LeIsaac environment") from exc

    with CONFIG.open(encoding="utf-8") as handle:
        spec = json.load(handle)
    board = spec["board"]
    piece = spec["piece"]
    square = float(board["square_size"])
    board_z = float(board["nominal_top_z"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    visual_output = args.output.parent / "visuals"
    visual_output.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(args.output))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    def cube(path: str, size_xyz, xyz, color):
        geom = UsdGeom.Cube.Define(stage, path)
        geom.CreateSizeAttr(1.0)
        xform = UsdGeom.Xformable(geom)
        xform.AddTranslateOp().Set(Gf.Vec3d(*xyz))
        xform.AddScaleOp().Set(Gf.Vec3f(*size_xyz))
        geom.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        UsdPhysics.CollisionAPI.Apply(geom.GetPrim())
        return geom

    carrier_x, carrier_y, carrier_h = map(float, board["carrier_size"])
    carrier_center_x = float(board["carrier_near_x"]) + carrier_x / 2
    cube(
        "/World/Board/Carrier",
        (carrier_x, carrier_y, carrier_h),
        (carrier_center_x, 0, board_z - carrier_h / 2),
        (0.07, 0.08, 0.09),
    )
    for rank in range(8):
        for file_index in range(8):
            x = float(board["playfield_near_x"]) + (rank + 0.5) * square
            y = square * (3.5 - file_index)
            color = (0.78, 0.70, 0.54) if (rank + file_index) % 2 == 0 else (0.18, 0.22, 0.20)
            tile = UsdGeom.Cube.Define(stage, f"/World/Board/Squares/s_{file_index}_{rank}")
            tile.CreateSizeAttr(1.0)
            xf = UsdGeom.Xformable(tile)
            xf.AddTranslateOp().Set(Gf.Vec3d(x, y, board_z + 0.00025))
            xf.AddScaleOp().Set(Gf.Vec3f(square, square, 0.0005))
            tile.CreateDisplayColorAttr([Gf.Vec3f(*color)])

    bin_size_x, bin_size_y = map(float, board["capture_bin_inner_size"])
    bin_height = float(board["capture_bin_height"])
    for color_name, (x, y) in board["capture_bin_centers"].items():
        root = f"/World/CaptureBins/{color_name}"
        color = (0.75, 0.76, 0.72) if color_name == "white" else (0.04, 0.05, 0.06)
        cube(f"{root}/Floor", (bin_size_x + 0.004, bin_size_y + 0.004, 0.003), (x, y, board_z + 0.0015), color)
        for suffix, size_xyz, xyz in (
            ("WallXPos", (0.002, bin_size_y + 0.004, bin_height), (x + bin_size_x / 2 + 0.001, y, board_z + bin_height / 2)),
            ("WallXNeg", (0.002, bin_size_y + 0.004, bin_height), (x - bin_size_x / 2 - 0.001, y, board_z + bin_height / 2)),
            ("WallYPos", (bin_size_x, 0.002, bin_height), (x, y + bin_size_y / 2 + 0.001, board_z + bin_height / 2)),
            ("WallYNeg", (bin_size_x, 0.002, bin_height), (x, y - bin_size_y / 2 - 0.001, board_z + bin_height / 2)),
        ):
            cube(f"{root}/{suffix}", size_xyz, xyz, color)

    def piece_prim(path: str, piece_type: str, color: str, x: float, y: float):
        root = UsdGeom.Xform.Define(stage, path)
        UsdGeom.Xformable(root).AddTranslateOp().Set(Gf.Vec3d(x, y, board_z))
        UsdPhysics.RigidBodyAPI.Apply(root.GetPrim())
        mass_api = UsdPhysics.MassAPI.Apply(root.GetPrim())
        mass_api.CreateMassAttr(float(piece["target_mass"]))
        rgb = (0.88, 0.89, 0.84) if color == "white" else (0.045, 0.055, 0.065)
        visual_path = ROOT / "chess_system" / "assets" / "generated" / "usd" / f"{color}_{piece_type}.usda"
        if visual_path.exists():
            source = Usd.Stage.Open(str(visual_path))
            source_roots = list(source.GetPseudoRoot().GetChildren()) if source else []
            if source_roots:
                packaged_visual = visual_output / visual_path.name
                if packaged_visual.resolve() != visual_path.resolve():
                    shutil.copy2(visual_path, packaged_visual)
                visual = UsdGeom.Xform.Define(stage, f"{path}/Visual")
                visual.GetPrim().GetReferences().AddReference(
                    f"visuals/{visual_path.name}", source_roots[0].GetPath()
                )
        for name, radius, height, z in (
            ("Base", float(piece["base_diameter"]) / 2, float(piece["base_height"]), float(piece["base_height"]) / 2),
            ("Mast", float(piece["grasp_mast_diameter"]) / 2, float(piece["grasp_mast_height"]), float(piece["grasp_mast_bottom_z"]) + float(piece["grasp_mast_height"]) / 2),
        ):
            cylinder = UsdGeom.Cylinder.Define(stage, f"{path}/Collision/{name}")
            cylinder.CreateAxisAttr("Z")
            cylinder.CreateRadiusAttr(radius)
            cylinder.CreateHeightAttr(height)
            UsdGeom.Xformable(cylinder).AddTranslateOp().Set(Gf.Vec3d(0, 0, z))
            cylinder.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])
            UsdPhysics.CollisionAPI.Apply(cylinder.GetPrim())
            if visual_path.exists():
                UsdGeom.Imageable(cylinder.GetPrim()).MakeInvisible()
        root.GetPrim().CreateAttribute("chess:pieceType", Sdf.ValueTypeNames.String).Set(piece_type)
        root.GetPrim().CreateAttribute("chess:color", Sdf.ValueTypeNames.String).Set(color)

    files = "abcdefgh"
    for color, pawn_rank, home_rank in (("white", 2, 1), ("black", 7, 8)):
        for file_index, file_name in enumerate(files):
            x = float(board["playfield_near_x"]) + (pawn_rank - 0.5) * square
            y = square * (3.5 - file_index)
            piece_prim(f"/World/Pieces/{color}_pawn_{file_name}", "pawn", color, x, y)
        for file_index, (file_name, piece_type) in enumerate(zip(files, BACK_RANK, strict=True)):
            x = float(board["playfield_near_x"]) + (home_rank - 0.5) * square
            y = square * (3.5 - file_index)
            piece_prim(f"/World/Pieces/{color}_{piece_type}_{file_name}", piece_type, color, x, y)

    stage.GetRootLayer().Save()
    print(f"authored {args.output}")


if __name__ == "__main__":
    main()
