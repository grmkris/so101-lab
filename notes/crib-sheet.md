# Command crib sheet (0.5.2 legacy stack)

Ports: follower `/dev/tty.usbmodem5AE60832001`, leader `/dev/tty.usbmodem5AE60538411`.
IDs: `robo_arm_follower` / `robo_arm_leader`. HF user: `kris0`. Camera: C922 → **640×360** (never 480).

## Teleop

```bash
lerobot-teleoperate \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=robo_arm_follower \
  --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodem5AE60538411 --teleop.id=robo_arm_leader
```

## Record

```bash
lerobot-record \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=robo_arm_follower \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 360, fps: 30}}" \
  --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodem5AE60538411 --teleop.id=robo_arm_leader \
  --display_data=true --dataset.repo_id=kris0/<name> \
  --dataset.single_task="Pick up the object and place it in the bowl" \
  --dataset.num_episodes=60 --dataset.episode_time_s=20 --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false
```

## Eval (run a policy)

```bash
rm -rf ~/.cache/huggingface/lerobot/kris0/eval_*
lerobot-record ... --policy.path=<local pretrained_model dir> --policy.device=mps \
  --dataset.repo_id=kris0/eval_<name>
```

## Replay (debug hardware vs policy)

```bash
lerobot-replay --robot.type=so101_follower --robot.port=... --robot.id=robo_arm_follower \
  --dataset.repo_id=kris0/<name> --dataset.episode=0
```

## Colab version-matched train (0.5.2)

```python
!git clone https://github.com/huggingface/lerobot.git
%cd lerobot
!git checkout 05a52238
!pip install -e ".[dataset,training]"
!pip uninstall -y hf_xet
from huggingface_hub import notebook_login; notebook_login()  # REQUIRED or push 401s
!lerobot-train --dataset.repo_id=kris0/<dataset> \
  --dataset.image_transforms.enable=true --policy.type=act --policy.device=cuda \
  --output_dir=outputs/train/<name> --job_name=<name> \
  --batch_size=16 --steps=50000 --save_freq=10000 \
  --policy.push_to_hub=true --policy.repo_id=kris0/<policy> --wandb.enable=false
```

## Gotchas

- `pretrained_revision not valid for ACTConfig` when loading cross-version → strip unknown keys from config.json (dataclasses.fields filter).
- hf_xet 403 on Mac push → `pip uninstall hf_xet`, re-push as plain LFS.
- Motor "no status packet" → loose 3-pin cable, reseat; `Overload error` latches → power-cycle follower PSU.
- Leader gripper calibration: SQUEEZE THE TRIGGER during range recording.

## LeLab (new stack, latest lerobot)

```bash
lelab          # opens browser UI: calibrate, teleop, record, train (HF Jobs), eval
lelab --dev    # hot-reload dev mode (Vite :8080 + uvicorn :8000)
```
