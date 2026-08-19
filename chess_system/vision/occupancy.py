"""Overhead-camera board registration and per-square occupancy verification.

The chess engine remains authoritative for identity. This module answers only:
"is the calibrated board still where expected?" and "which squares contain an
object unlike the empty-board reference?"
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from chess_system.geometry import FILES, RANKS, load_geometry

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None


@dataclass(frozen=True)
class BoardObservation:
    occupancy: dict[str, bool]
    scores: dict[str, float]
    translation_error_m: float
    rotation_error_degrees: float
    rectified_bgr: object


class BoardVerifier:
    def __init__(self, calibration_dir: str | Path, *, pixels_per_square: int = 64, threshold: float = 18.0):
        if cv2 is None or np is None:
            raise RuntimeError("BoardVerifier requires OpenCV and NumPy")
        self.geometry = load_geometry()
        self.directory = Path(calibration_dir)
        self.pixels_per_square = int(pixels_per_square)
        self.threshold = float(threshold)
        self.metadata_path = self.directory / "board_verifier.json"
        self.empty_path = self.directory / "empty_board.png"
        self.dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.detector = cv2.aruco.ArucoDetector(self.dictionary)

    def _detect(self, frame) -> dict[int, object]:
        corners, ids, _ = self.detector.detectMarkers(frame)
        if ids is None:
            raise RuntimeError("no board fiducials detected")
        found = {int(marker_id): corner.reshape(-1, 2).mean(axis=0) for corner, marker_id in zip(corners, ids.flatten(), strict=True)}
        missing = set(range(4)) - set(found)
        if missing:
            raise RuntimeError(f"missing board fiducials: {sorted(missing)}")
        return found

    def _homography(self, centers: dict[int, object]):
        world = np.asarray(self.geometry.board["fiducial_centers"], dtype=np.float32)
        image = np.asarray([centers[index] for index in range(4)], dtype=np.float32)
        homography, _ = cv2.findHomography(image, world)
        if homography is None:
            raise RuntimeError("could not fit image-to-board homography")
        return homography

    def _rectify(self, frame, image_to_world):
        size = self.geometry.square_size
        near = float(self.geometry.board["playfield_near_x"])
        half = self.geometry.playfield_size / 2
        pixels = self.pixels_per_square
        # World (x, y) -> rectified image (column=file a..h, row=rank 8..1).
        world_to_grid = np.asarray(
            [
                [0.0, -pixels / size, half * pixels / size],
                [-pixels / size, 0.0, (near + self.geometry.playfield_size) * pixels / size],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        image_to_grid = world_to_grid @ image_to_world
        side = pixels * 8
        return cv2.warpPerspective(frame, image_to_grid, (side, side), flags=cv2.INTER_LINEAR)

    def calibrate_empty(self, frame) -> None:
        centers = self._detect(frame)
        homography = self._homography(centers)
        rectified = self._rectify(frame, homography)
        self.directory.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(self.empty_path), rectified):
            raise RuntimeError(f"could not save {self.empty_path}")
        metadata = {
            "schema_version": 1,
            "pixels_per_square": self.pixels_per_square,
            "threshold": self.threshold,
            "marker_centers_px": {str(key): [float(v) for v in value] for key, value in centers.items()},
        }
        self.metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    def observe(self, frame) -> BoardObservation:
        if not self.metadata_path.exists() or not self.empty_path.exists():
            raise RuntimeError("empty-board calibration missing")
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        reference_centers = {int(key): np.asarray(value, dtype=float) for key, value in metadata["marker_centers_px"].items()}
        centers = self._detect(frame)
        homography = self._homography(centers)
        rectified = self._rectify(frame, homography)
        empty = cv2.imread(str(self.empty_path), cv2.IMREAD_COLOR)
        if empty is None or empty.shape != rectified.shape:
            raise RuntimeError("empty-board reference is missing or has the wrong size")

        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        empty_gray = cv2.cvtColor(empty, cv2.COLOR_BGR2GRAY)
        delta = cv2.absdiff(gray, empty_gray)
        pixels = self.pixels_per_square
        inset = max(3, pixels // 8)
        occupancy: dict[str, bool] = {}
        scores: dict[str, float] = {}
        for visual_rank in range(8):
            rank = 8 - visual_rank
            for file_index, file_name in enumerate(FILES):
                tile = delta[
                    visual_rank * pixels + inset : (visual_rank + 1) * pixels - inset,
                    file_index * pixels + inset : (file_index + 1) * pixels - inset,
                ]
                score = float(np.percentile(tile, 80))
                square = f"{file_name}{rank}"
                scores[square] = score
                occupancy[square] = score >= float(metadata.get("threshold", self.threshold))

        ref = np.asarray([reference_centers[index] for index in range(4)], dtype=float)
        current = np.asarray([centers[index] for index in range(4)], dtype=float)
        mean_px_shift = float(np.linalg.norm(current - ref, axis=1).mean())
        # Estimate local scale using the two fiducials spanning the board's X direction.
        world = np.asarray(self.geometry.board["fiducial_centers"], dtype=float)
        world_span = float(np.linalg.norm(world[1] - world[0]))
        pixel_span = max(1.0, float(np.linalg.norm(ref[1] - ref[0])))
        translation = mean_px_shift * world_span / pixel_span
        ref_vector = ref[1] - ref[0]
        cur_vector = current[1] - current[0]
        ref_angle = math.atan2(ref_vector[1], ref_vector[0])
        cur_angle = math.atan2(cur_vector[1], cur_vector[0])
        rotation = math.degrees(cur_angle - ref_angle)
        return BoardObservation(occupancy, scores, translation, rotation, rectified)


def _capture(camera_index: int):
    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    for _ in range(20):
        ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"camera {camera_index} did not return a frame")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration-dir", type=Path, required=True)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--calibrate-empty", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    verifier = BoardVerifier(args.calibration_dir)
    frame = _capture(args.camera)
    if args.calibrate_empty:
        verifier.calibrate_empty(frame)
        print(f"saved empty-board calibration to {args.calibration_dir}")
        return
    observation = verifier.observe(frame)
    print(json.dumps({
        "occupied": [square for square, occupied in observation.occupancy.items() if occupied],
        "translation_error_mm": observation.translation_error_m * 1000,
        "rotation_error_degrees": observation.rotation_error_degrees,
        "scores": observation.scores,
    }, indent=2))
    if args.output:
        cv2.imwrite(str(args.output), observation.rectified_bgr)


if __name__ == "__main__":
    main()
