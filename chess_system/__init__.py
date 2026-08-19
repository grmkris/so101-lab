"""SO-101 micro-chess system.

The package intentionally keeps its core dependency-free. Simulator adapters and
the python-chess controller are optional layers around the shared geometry and
backend contracts.
"""

from .geometry import ChessGeometry, load_geometry
from .model import ManipulationResult, MovePlan, MoveStep, ResultStatus

__all__ = [
    "ChessGeometry",
    "ManipulationResult",
    "MovePlan",
    "MoveStep",
    "ResultStatus",
    "load_geometry",
]
