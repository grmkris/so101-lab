"""Fail closed when generated fabrication meshes drift from the manifest."""

from __future__ import annotations

import json
from pathlib import Path

from chess_system.geometry import load_geometry


ROOT = Path(__file__).resolve().parents[2]
STL_DIR = ROOT / "chess_system" / "assets" / "generated" / "stl"
REPORT = ROOT / "chess_system" / "fabrication" / "generated" / "asset_validation.json"
PIECES = ("pawn", "rook", "knight", "bishop", "queen", "king")


def validate() -> dict:
    try:
        import trimesh
    except ImportError as exc:
        raise SystemExit("asset validation requires trimesh (already installed in sim/.venv)") from exc
    geometry = load_geometry()
    max_width = float(geometry.piece["base_diameter"])
    max_height = float(geometry.piece["total_height"])
    tolerance = 0.00015
    results = {}
    failures = []
    for name in PIECES:
        path = STL_DIR / f"{name}.stl"
        mesh = trimesh.load_mesh(path)
        extents = [float(value) for value in mesh.extents]
        passed = (
            extents[0] <= max_width + tolerance
            and extents[1] <= max_width + tolerance
            and extents[2] <= max_height + tolerance
            and float(mesh.bounds[0][2]) >= -tolerance
        )
        if not passed:
            failures.append(name)
        results[name] = {
            "extents_mm": [round(value * 1000, 3) for value in extents],
            "watertight": bool(mesh.is_watertight),
            "components": len(mesh.split(only_watertight=False)),
            "pass": passed,
        }
    return {
        "status": "pass" if not failures else "fail",
        "maximum_piece_width_mm": max_width * 1000,
        "maximum_piece_height_mm": max_height * 1000,
        "failures": failures,
        "pieces": results,
    }


def main() -> None:
    report = validate()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
