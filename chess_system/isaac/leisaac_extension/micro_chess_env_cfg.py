"""LeIsaac SO-101 environment for leader-driven micro-chess recording."""

from isaaclab.assets import AssetBaseCfg
from isaaclab.utils import configclass

from leisaac.assets.scenes.micro_chess import MICRO_CHESS_SCENE_CFG, MICRO_CHESS_USD_PATH
from leisaac.utils.general_assets import parse_usd_and_create_subassets

from ..template import (
    SingleArmObservationsCfg,
    SingleArmTaskEnvCfg,
    SingleArmTaskSceneCfg,
    SingleArmTerminationsCfg,
)


@configclass
class MicroChessSceneCfg(SingleArmTaskSceneCfg):
    scene: AssetBaseCfg = MICRO_CHESS_SCENE_CFG.replace(prim_path="{ENV_REGEX_NS}/Scene")


@configclass
class MicroChessEnvCfg(SingleArmTaskEnvCfg):
    scene: MicroChessSceneCfg = MicroChessSceneCfg(env_spacing=2.0)
    observations: SingleArmObservationsCfg = SingleArmObservationsCfg()
    terminations: SingleArmTerminationsCfg = SingleArmTerminationsCfg()
    task_description: str = "Move one engineered chess piece from its source square to its legal destination."

    def __post_init__(self) -> None:
        super().__post_init__()
        self.viewer.eye = (0.42, -0.48, 0.38)
        self.viewer.lookat = (0.17, 0.0, 0.03)
        self.scene.robot.init_state.pos = (0.0, 0.0, 0.0)
        parse_usd_and_create_subassets(MICRO_CHESS_USD_PATH, self)
