"""Play a complete game of chess with the simulated SO-101.

The arm plays both colours: it is the only actuator on the board, so every move
of the game is a physical transfer it has to plan, execute and verify. The
engine proposes moves in rank order and the controller walks that list until it
finds one the arm can mechanically reach, which is the loop that turns the
motion planner and the rule layer into an actual game.

Run headless:

    sim/.venv/bin/python -m chess_system.mujoco.play_game --max-moves 20

Run with the native viewer (macOS needs ``mjpython``):

    sim/.venv/bin/mjpython -m chess_system.mujoco.play_game --viewer
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import chess

from chess_system.controller import ChessController
from chess_system.engine import rank_moves
from chess_system.model import ResultStatus
from chess_system.mujoco.backend import DEFAULT_SCENE
from chess_system.mujoco.trajectory_executor import (
    DEFAULT_LIBRARY,
    PlannedMujocoChessBackend,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = (
    ROOT / "chess_system" / "mujoco" / "generated" / "game_report.json"
)


@dataclass
class MoveRecord:
    ply: int
    color: str
    uci: str
    san: str
    status: str
    message: str
    engine_rank: int
    rejected: list[dict[str, Any]] = field(default_factory=list)
    planning_seconds: float = 0.0
    execution_seconds: float = 0.0


@dataclass
class GameReport:
    status: str
    result: str
    termination: str
    plies: int
    final_fen: str
    elapsed_seconds: float
    unreachable_rejections: int
    moves: list[MoveRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["moves"] = [asdict(m) if not isinstance(m, dict) else m for m in self.moves]
        return payload


def _termination(board: chess.Board) -> str:
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return "in_progress"
    return outcome.termination.name.lower()


def play_game(
    *,
    max_moves: int = 200,
    depth: int = 3,
    scene: str | Path = DEFAULT_SCENE,
    library: str | Path = DEFAULT_LIBRARY,
    frame_callback=None,
    backend: PlannedMujocoChessBackend | None = None,
    verbose: bool = True,
) -> GameReport:
    if backend is None:
        backend = PlannedMujocoChessBackend(
            scene, library, frame_callback=frame_callback
        )

    def auto_promotion(square: str, piece_type: str) -> bool:
        # The physical system pauses for an operator swap. In simulation the
        # piece is already the promoted type, so the pause resolves itself —
        # recorded explicitly so the runbook difference stays visible.
        if verbose:
            print(f"  promotion at {square} -> {piece_type} (auto-resolved in sim)")
        return True

    controller = ChessController(backend, promotion_handler=auto_promotion)
    board = controller.board
    started = time.time()
    records: list[MoveRecord] = []
    rejections = 0
    status = "complete"

    while not board.is_game_over(claim_draw=True) and len(records) < max_moves:
        ranked = rank_moves(board, depth=depth)
        plan_started = time.time()
        move, rejected = controller.select_move(ranked)
        planning_seconds = time.time() - plan_started
        rejections += len(rejected)

        if move is None:
            status = "no_executable_move"
            if verbose:
                print(
                    f"stopped at ply {len(records)}: every legal move is "
                    f"mechanically unreachable ({len(rejected)} rejected)"
                )
            break

        colour = "white" if board.turn == chess.WHITE else "black"
        san = board.san(move)
        execute_started = time.time()
        result = controller.execute_uci(move.uci())
        execution_seconds = time.time() - execute_started

        records.append(
            MoveRecord(
                ply=len(records) + 1,
                color=colour,
                uci=move.uci(),
                san=san,
                status=str(result.status),
                message=result.message,
                engine_rank=len(rejected),
                rejected=[asdict(r) for r in rejected],
                planning_seconds=planning_seconds,
                execution_seconds=execution_seconds,
            )
        )
        if verbose:
            note = f" (engine choice #{len(rejected) + 1})" if rejected else ""
            print(
                f"{len(records):3d}. {colour:5s} {san:8s} {result.status}"
                f" plan {planning_seconds:5.1f}s exec {execution_seconds:5.1f}s{note}"
            )

        if result.status != ResultStatus.VERIFIED:
            status = f"halted_{result.status}"
            if verbose:
                print(f"halted: {result.message}")
            break

    outcome = board.outcome(claim_draw=True)
    return GameReport(
        status=status,
        result=outcome.result() if outcome else "*",
        termination=_termination(board),
        plies=len(records),
        final_fen=board.fen(),
        elapsed_seconds=time.time() - started,
        unreachable_rejections=rejections,
        moves=records,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-moves", type=int, default=200)
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--scene", default=str(DEFAULT_SCENE))
    parser.add_argument("--library", default=str(DEFAULT_LIBRARY))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--viewer",
        action="store_true",
        help="open the native MuJoCo viewer (requires mjpython on macOS)",
    )
    args = parser.parse_args()

    if args.viewer:
        import mujoco.viewer

        holder: dict[str, Any] = {}

        def frame_callback() -> None:
            viewer = holder.get("viewer")
            if viewer is not None and viewer.is_running():
                viewer.sync()

        backend = PlannedMujocoChessBackend(args.scene, args.library)
        with mujoco.viewer.launch_passive(backend.model, backend.data) as viewer:
            holder["viewer"] = viewer
            backend.executor.frame_callback = frame_callback
            report = play_game(
                max_moves=args.max_moves,
                depth=args.depth,
                backend=backend,
            )
    else:
        report = play_game(
            max_moves=args.max_moves,
            depth=args.depth,
            scene=args.scene,
            library=args.library,
        )

    Path(args.report).write_text(json.dumps(report.to_dict(), indent=2))
    print(
        f"\n{report.status}: {report.plies} plies, result {report.result}"
        f" ({report.termination}), {report.unreachable_rejections} unreachable"
        f" rejections, {report.elapsed_seconds:.1f}s"
    )
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
