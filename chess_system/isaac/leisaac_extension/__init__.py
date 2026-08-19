"""Registration module copied into ``leisaac.tasks.micro_chess`` on Runpod."""

import gymnasium as gym

gym.register(
    id="LeIsaac-SO101-MicroChess-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{__name__}.micro_chess_env_cfg:MicroChessEnvCfg",
    },
)
