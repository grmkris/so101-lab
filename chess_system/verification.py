"""Occupancy and board-pose verification shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import FILES, RANKS


ALL_SQUARES = tuple(f"{file_name}{rank}" for rank in RANKS for file_name in FILES)


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    board_moved: bool = False
    message: str = ""


def normalize_occupancy(observed: dict[str, bool]) -> dict[str, bool]:
    unknown = set(observed) - set(ALL_SQUARES)
    if unknown:
        raise ValueError(f"unknown occupancy keys: {sorted(unknown)}")
    return {square: bool(observed.get(square, False)) for square in ALL_SQUARES}


def verify_occupancy(
    expected: dict[str, bool],
    observed: dict[str, bool],
    *,
    translation_error: float = 0.0,
    rotation_error_degrees: float = 0.0,
    translation_abort: float = 0.002,
    rotation_abort_degrees: float = 0.5,
) -> VerificationReport:
    expected_full = normalize_occupancy(expected)
    observed_full = normalize_occupancy(observed)
    missing = tuple(s for s in ALL_SQUARES if expected_full[s] and not observed_full[s])
    unexpected = tuple(s for s in ALL_SQUARES if not expected_full[s] and observed_full[s])
    board_moved = (
        translation_error > translation_abort or abs(rotation_error_degrees) > rotation_abort_degrees
    )
    problems = []
    if missing:
        problems.append(f"missing occupancy at {', '.join(missing)}")
    if unexpected:
        problems.append(f"unexpected occupancy at {', '.join(unexpected)}")
    if board_moved:
        problems.append(
            f"board moved {translation_error * 1000:.1f} mm / {rotation_error_degrees:.2f} deg"
        )
    return VerificationReport(
        ok=not problems,
        missing=missing,
        unexpected=unexpected,
        board_moved=board_moved,
        message="; ".join(problems) if problems else "occupancy and board pose verified",
    )
