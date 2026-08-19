"""Repeated physics-stepped validation of representative planned motions."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from chess_system.controller import ChessController
from chess_system.mujoco.trajectory_executor import PlannedMujocoChessBackend


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = (
    ROOT / "chess_system" / "mujoco" / "generated" / "dynamic_replay_report.json"
)


def _direct_move(source: str, target: str) -> None:
    backend = PlannedMujocoChessBackend()
    backend.executor.move_square(source, target)


def _capture_sequence() -> None:
    backend = PlannedMujocoChessBackend()
    controller = ChessController(backend)
    for move in ("e2e4", "d7d5", "e4d5"):
        result = controller.execute_uci(move)
        if not result.ok:
            raise RuntimeError(f"{move}: {result.message}")


def validate(trials: int = 10) -> dict:
    scenarios = {
        "near_rank": lambda: _direct_move("b1", "a3"),
        "center": lambda: _direct_move("e2", "e4"),
        "far_rank": lambda: _direct_move("b8", "a6"),
        "crowded_back_rank": lambda: _direct_move("g1", "f3"),
        "capture_bin": _capture_sequence,
    }
    started = time.perf_counter()
    details = []
    for scenario, action in scenarios.items():
        successes = 0
        failures = []
        for trial in range(trials):
            try:
                action()
                successes += 1
            except Exception as exc:
                failures.append({"trial": trial, "error": str(exc)})
        details.append(
            {
                "scenario": scenario,
                "trials": trials,
                "successes": successes,
                "failures": failures,
            }
        )
        print(f"{scenario}: {successes}/{trials}")
    failed = [detail["scenario"] for detail in details if detail["failures"]]
    return {
        "status": "pass" if not failed else "fail",
        "trials_per_scenario": trials,
        "total_trials": trials * len(scenarios),
        "failed_scenarios": failed,
        "elapsed_seconds": time.perf_counter() - started,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = validate(args.trials)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
