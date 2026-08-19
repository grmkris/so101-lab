"""Deterministic five-joint bidirectional RRT-Connect."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


StateValid = Callable[[np.ndarray], bool]
EdgeValid = Callable[[np.ndarray, np.ndarray], bool]


@dataclass
class _Node:
    q: np.ndarray
    parent: int | None


@dataclass
class _Tree:
    root_kind: str
    nodes: list[_Node]

    @classmethod
    def create(cls, root_kind: str, q: np.ndarray) -> "_Tree":
        return cls(root_kind, [_Node(np.asarray(q, dtype=float).copy(), None)])

    def nearest(self, target: np.ndarray, spans: np.ndarray) -> int:
        query = np.asarray(target)
        values = np.asarray([node.q for node in self.nodes])
        distances = np.linalg.norm((values - query) / spans, axis=1)
        return int(np.argmin(distances))

    def append(self, q: np.ndarray, parent: int) -> int:
        self.nodes.append(_Node(np.asarray(q, dtype=float).copy(), parent))
        return len(self.nodes) - 1

    def path_to(self, index: int) -> list[np.ndarray]:
        result = []
        current: int | None = index
        while current is not None:
            node = self.nodes[current]
            result.append(node.q.copy())
            current = node.parent
        return list(reversed(result))


@dataclass(frozen=True)
class PlanResult:
    path: tuple[np.ndarray, ...]
    iterations: int
    direct: bool


class RRTConnect:
    def __init__(
        self,
        lower: np.ndarray,
        upper: np.ndarray,
        state_valid: StateValid,
        edge_valid: EdgeValid,
        *,
        step_radians: float,
        goal_bias: float,
        maximum_iterations: int,
    ):
        self.lower = np.asarray(lower, dtype=float)
        self.upper = np.asarray(upper, dtype=float)
        self.spans = self.upper - self.lower
        self.state_valid = state_valid
        self.edge_valid = edge_valid
        self.step = float(step_radians)
        self.goal_bias = float(goal_bias)
        self.maximum_iterations = int(maximum_iterations)

    def _steer(self, source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, bool]:
        delta = target - source
        largest = float(np.max(np.abs(delta)))
        if largest <= self.step:
            return target.copy(), True
        return source + delta * (self.step / largest), False

    def _extend(self, tree: _Tree, target: np.ndarray) -> tuple[str, int | None]:
        nearest = tree.nearest(target, self.spans)
        candidate, reached = self._steer(tree.nodes[nearest].q, target)
        if not self.state_valid(candidate) or not self.edge_valid(tree.nodes[nearest].q, candidate):
            return "trapped", None
        index = tree.append(candidate, nearest)
        return ("reached" if reached else "advanced"), index

    def _connect(self, tree: _Tree, target: np.ndarray) -> tuple[str, int | None]:
        last = None
        while True:
            status, index = self._extend(tree, target)
            if status == "trapped":
                return ("advanced" if last is not None else "trapped"), last
            last = index
            if status == "reached":
                return "reached", index

    @staticmethod
    def _join(first: _Tree, first_index: int, second: _Tree, second_index: int) -> tuple[np.ndarray, ...]:
        first_path = first.path_to(first_index)
        second_path = second.path_to(second_index)
        if first.root_kind == "start":
            start_path, goal_path = first_path, second_path
        else:
            start_path, goal_path = second_path, first_path
        return tuple(start_path + list(reversed(goal_path[:-1])))

    def plan(self, start: np.ndarray, goal: np.ndarray, *, seed: int) -> PlanResult | None:
        start = np.asarray(start, dtype=float)
        goal = np.asarray(goal, dtype=float)
        if not self.state_valid(start):
            raise ValueError("RRT start state is invalid")
        if not self.state_valid(goal):
            raise ValueError("RRT goal state is invalid")
        if self.edge_valid(start, goal):
            return PlanResult((start.copy(), goal.copy()), 0, True)

        rng = np.random.default_rng(seed)
        first = _Tree.create("start", start)
        second = _Tree.create("goal", goal)
        for iteration in range(1, self.maximum_iterations + 1):
            if rng.random() < self.goal_bias:
                sample = second.nodes[0].q.copy()
            else:
                sample = rng.uniform(self.lower, self.upper)
            status, first_index = self._extend(first, sample)
            if status != "trapped" and first_index is not None:
                reached, second_index = self._connect(second, first.nodes[first_index].q)
                if reached == "reached" and second_index is not None:
                    return PlanResult(
                        self._join(first, first_index, second, second_index), iteration, False
                    )
            first, second = second, first
        return None


def shortcut_path(
    path: tuple[np.ndarray, ...],
    edge_valid: EdgeValid,
    *,
    attempts: int,
    seed: int,
) -> tuple[np.ndarray, ...]:
    result = [q.copy() for q in path]
    rng = np.random.default_rng(seed)
    for _ in range(attempts):
        if len(result) < 3:
            break
        first, second = sorted(rng.choice(len(result), size=2, replace=False).tolist())
        if second <= first + 1:
            continue
        if edge_valid(result[first], result[second]):
            result = result[: first + 1] + result[second:]
    return tuple(result)


def resample_path(path: tuple[np.ndarray, ...], maximum_step_radians: float) -> tuple[np.ndarray, ...]:
    result = [path[0].copy()]
    for start, end in zip(path, path[1:]):
        count = max(1, int(np.ceil(np.max(np.abs(end - start)) / maximum_step_radians)))
        for index in range(1, count + 1):
            result.append(start + (end - start) * index / count)
    return tuple(result)
