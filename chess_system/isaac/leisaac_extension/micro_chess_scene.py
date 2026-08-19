"""Scene asset installed as ``leisaac.assets.scenes.micro_chess``."""

from pathlib import Path

import isaaclab.sim as sim_utils
from isaaclab.assets import AssetBaseCfg

from leisaac.utils.constant import ASSETS_ROOT


MICRO_CHESS_USD_PATH = str(Path(ASSETS_ROOT) / "scenes" / "micro_chess" / "scene.usda")
MICRO_CHESS_SCENE_CFG = AssetBaseCfg(
    spawn=sim_utils.UsdFileCfg(usd_path=MICRO_CHESS_USD_PATH)
)
