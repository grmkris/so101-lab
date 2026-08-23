"""Dataset health gate — catch silently-wrong camera data before training on it.

Two independent checks, because the two failure modes look nothing alike:

1. **Frozen camera** — the device stops delivering and the recorder keeps
   writing the last frame it saw.  Shows up as runs of consecutive frames with
   a frame-to-frame mean-absolute-difference of exactly 0.
2. **Duplicated stream** — two feature keys carrying the same picture (the
   failure mode that disqualified lerobot's ZMQ camera, which substitutes an
   arbitrary other camera's image when one has no fresh frame).  Shows up as a
   near-zero mean-absolute-difference *between* the two camera streams.

Run it on a dataset you already trained on before trusting the numbers on a new
one — the baseline matters more than the absolute value.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

# A genuinely static scene still moves a little (sensor noise, lighting ripple).
# Exact 0.0 means the *same bytes*, which only happens when a frame is reused.
FROZEN_MAD = 0.05      # per-camera frame-to-frame MAD below this == frozen
DUPLICATE_MAD = 2.0    # cross-camera MAD below this == same picture
MAX_FROZEN_RUN = 3     # tolerate a couple of repeats; a run means a dead camera


@dataclass
class CameraReport:
    key: str
    frames: int
    frozen_frames: int
    longest_frozen_run: int
    mean_mad: float
    p05_mad: float

    @property
    def frozen_pct(self) -> float:
        return 100.0 * self.frozen_frames / self.frames if self.frames else 0.0


@dataclass
class SegmentReport:
    """One video *file*.  LeRobotDataset v3 packs many episodes into a single
    `file-NNN.mp4` per camera, so a segment is a chunk of episodes, not one."""

    segment: int
    cameras: list
    cross_mad: float | None
    duplicated: bool
    verdict: str
    notes: list


def _decode(path: str, stride: int, max_frames: int, width: int = 160) -> np.ndarray:
    """Decode a video to a small grayscale stack.  Downscaling is deliberate:
    we are looking for *identical* frames, and identity survives resizing while
    the cost drops ~16x."""
    import av

    frames = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for i, frame in enumerate(container.decode(stream)):
            if i % stride:
                continue
            img = frame.to_ndarray(format="gray")
            if img.shape[1] != width:
                h = max(1, round(img.shape[0] * width / img.shape[1]))
                idx_y = (np.arange(h) * img.shape[0] // h).clip(0, img.shape[0] - 1)
                idx_x = (np.arange(width) * img.shape[1] // width).clip(0, img.shape[1] - 1)
                img = img[np.ix_(idx_y, idx_x)]
            frames.append(img.astype(np.float32))
            if len(frames) >= max_frames:
                break
    if not frames:
        raise RuntimeError(f"no frames decoded from {path}")
    return np.stack(frames)


def check_camera(stack: np.ndarray, key: str) -> CameraReport:
    diffs = np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2))
    frozen = diffs < FROZEN_MAD
    run = best = 0
    for f in frozen:
        run = run + 1 if f else 0
        best = max(best, run)
    return CameraReport(
        key=key,
        frames=int(stack.shape[0]),
        frozen_frames=int(frozen.sum()),
        longest_frozen_run=int(best),
        mean_mad=float(diffs.mean()) if diffs.size else 0.0,
        p05_mad=float(np.percentile(diffs, 5)) if diffs.size else 0.0,
    )


def check_segment(video_paths: dict, segment: int, stride: int = 5,
                  max_frames: int = 400) -> SegmentReport:
    stacks = {k: _decode(p, stride, max_frames) for k, p in video_paths.items()}
    cams = [check_camera(s, k) for k, s in stacks.items()]

    cross = None
    duplicated = False
    keys = list(stacks)
    if len(keys) == 2:
        a, b = stacks[keys[0]], stacks[keys[1]]
        n = min(len(a), len(b))
        cross = float(np.abs(a[:n] - b[:n]).mean())
        duplicated = cross < DUPLICATE_MAD

    notes = []
    for c in cams:
        if c.longest_frozen_run > MAX_FROZEN_RUN:
            notes.append(
                f"{c.key}: {c.longest_frozen_run} consecutive identical frames "
                f"({c.frozen_pct:.1f}% frozen) — camera stalled during the episode"
            )
        elif c.frozen_pct > 5.0:
            notes.append(f"{c.key}: {c.frozen_pct:.1f}% repeated frames (scattered, not a stall)")
    if duplicated:
        notes.append(
            f"cross-camera MAD {cross:.2f} — the two streams carry the SAME picture; "
            "one feature key is wrong"
        )

    verdict = "FAIL" if (duplicated or any(c.longest_frozen_run > MAX_FROZEN_RUN for c in cams)) \
        else ("WARN" if notes else "OK")
    return SegmentReport(segment, [asdict(c) for c in cams], cross, duplicated, verdict, notes)


def find_segments(root: Path) -> dict:
    """Map video-file index -> {feature_key: path} for a LeRobotDataset v3 tree."""
    videos = root / "videos"
    if not videos.is_dir():
        raise SystemExit(f"no videos/ under {root} — is this a LeRobotDataset?")
    out: dict = {}
    for path in sorted(videos.rglob("*.mp4")):
        rel = path.relative_to(videos)
        parts = list(rel.parts)
        key = next((p for p in parts if p.startswith("observation.images.")), None)
        if key is None:
            continue
        stem = path.stem
        digits = "".join(ch for ch in stem if ch.isdigit())
        seg = int(digits) if digits else 0
        out.setdefault(seg, {})[key] = str(path)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Health-gate a LeRobot dataset's camera streams")
    ap.add_argument("root", help="dataset root (contains videos/, data/, meta/)")
    ap.add_argument("--stride", type=int, default=5, help="decode every Nth frame")
    ap.add_argument("--max-frames", type=int, default=400)
    ap.add_argument("--segments", type=int, default=0, help="limit to the first N video files")
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args()

    root = Path(os.path.expanduser(args.root))
    segments = find_segments(root)
    if not segments:
        raise SystemExit(f"no observation.images.* videos found under {root}")
    keys = sorted(segments)
    if args.segments:
        keys = keys[: args.segments]

    reports, bad, scanned = [], 0, 0
    for seg in keys:
        rep = check_segment(segments[seg], seg, args.stride, args.max_frames)
        reports.append(asdict(rep))
        bad += rep.verdict == "FAIL"
        scanned += max((c["frames"] for c in rep.cameras), default=0)
        cross = f"{rep.cross_mad:.1f}" if rep.cross_mad is not None else "-"
        per = "  ".join(
            f"{c['key'].split('.')[-1]}: frz_run={c['longest_frozen_run']} "
            f"mad={c['mean_mad']:.1f}" for c in rep.cameras
        )
        print(f"file {seg:>3}  {rep.verdict:<4} cross_mad={cross:>6}  {per}")
        for n in rep.notes:
            print(f"           ! {n}")

    if args.json:
        Path(args.json).write_text(json.dumps({"root": str(root), "segments": reports}, indent=2))
        print(f"\nwrote {args.json}")

    print(f"\n{len(reports)} video files, {scanned} frames sampled, {bad} FAIL")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
