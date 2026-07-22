# Command crib sheet (LeLab / lerobot 0.6.0 stack)

**Env:** all `lerobot-*` binaries live in the LeLab uv tool env. Prefix so the rerun viewer is on PATH:
```bash
export PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH"
```
(add to `~/.zshrc` to make permanent)

**Ports:** follower `/dev/tty.usbmodem5AE60832001`, leader `/dev/tty.usbmodem5AE60538411`.
**IDs:** both `arm` (LeLab calibration name). **HF user:** `kris0`.
**Cameras (640×480@30):** ⚠️ macOS shuffles indexes on replug — VERIFY before every session with `curl -s http://localhost:8000/available-cameras`. Typical: overhead C922 = 0, wrist Innomaker = 1, but they SWAP.

## Verify camera indexes (do this first, every session)
```bash
~/.local/share/uv/tools/lelab/bin/python -c "
import cv2
for i in range(3):
    c=cv2.VideoCapture(i); [c.read() for _ in range(30)]; ok,f=c.read(); c.release()
    print(i, round(f.mean(),1) if ok else 'FAIL')"
# bright (~130) = overhead C922; dimmer (~40-110) = wrist; ~0 = disconnected
```

## Live camera viewer (aim/focus) — run in YOUR terminal
```bash
! ~/.local/share/uv/tools/lelab/bin/python ~/Code/github-com/so101-lab/scripts/camview.py 0   # Q to quit
```

## Calibrate (only if arm base/servos were physically remounted)
```bash
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=arm
lerobot-calibrate --teleop.type=so101_leader  --teleop.port=/dev/tty.usbmodem5AE60538411 --teleop.id=arm
# middle position first, then full range each joint; SQUEEZE gripper trigger fully on leader
```

## Teleop (both cameras + rerun viewer)
```bash
PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH" lerobot-teleoperate \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=arm \
  --robot.cameras="{ workspace_cam: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist_cam: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}" \
  --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodem5AE60538411 --teleop.id=arm \
  --display_data=true
```

## Record a dataset (teleop demos — data collection only in 0.6)
```bash
PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH" lerobot-record \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=arm \
  --robot.cameras="{ workspace_cam: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist_cam: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}" \
  --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodem5AE60538411 --teleop.id=arm \
  --display_data=true \
  --dataset.repo_id=kris0/<name> \
  --dataset.single_task="pick white block and put it into jar" \
  --dataset.num_episodes=50 --dataset.episode_time_s=20 --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false
```
Keys: right arrow = next episode, left arrow = re-record current, ESC = stop.
**Extend an existing dataset:** add `--resume=true --dataset.root=$HOME/.cache/huggingface/lerobot/kris0/<name>`.

## Run a policy on the arm (0.6: rollout, NOT record)
```bash
PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH" lerobot-rollout \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=arm \
  --robot.cameras="{ workspace_cam: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist_cam: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}" \
  --strategy.type=episodic --display_data=true \
  --dataset.repo_id=kris0/rollout_<name> \
  --dataset.single_task="pick white block and put it into jar" \
  --dataset.num_episodes=10 --dataset.episode_time_s=30 --dataset.reset_time_s=10 \
  --policy.path=kris0/<model> --policy.device=mps \
  --dataset.push_to_hub=false
```
Rollout dataset name MUST start with `rollout_`. `--strategy.type=dagger` + a teleop = grab leader to correct mistakes (tagged `intervention=True`).

## Replay a demo (debug: policy vs hardware)
```bash
PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH" lerobot-replay \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=arm \
  --dataset.repo_id=kris0/<name> --dataset.episode=0
```

## Push dataset to Hub
```bash
~/.local/share/uv/tools/lelab/bin/python -c "
from lerobot.datasets.lerobot_dataset import LeRobotDataset
LeRobotDataset('kris0/<name>').push_to_hub()"
```

## Train on Colab (A100, version-matched to 0.6.0)
```python
!git clone https://github.com/huggingface/lerobot.git
%cd lerobot
!git checkout v0.6.0
!pip install -e ".[dataset,training]"
!pip uninstall -y hf_xet
from huggingface_hub import notebook_login; notebook_login()   # REQUIRED or push 401s
!lerobot-train --dataset.repo_id=kris0/<dataset> \
  --dataset.image_transforms.enable=true --policy.type=act --policy.device=cuda \
  --output_dir=outputs/train/<name> --job_name=<name> \
  --batch_size=16 --steps=40000 --save_freq=5000 \
  --policy.push_to_hub=true --policy.repo_id=kris0/<model> --wandb.enable=false
```

## Import a trained model into LeLab (one-click inference)
```bash
curl -s -X POST http://localhost:8000/jobs/import -H 'Content-Type: application/json' \
  -d '{"source":"kris0/<model>","name":"<model>"}'
```

## Gotchas
- rerun `Failed to find Rerun Viewer` → missing PATH prefix (see top).
- Camera black / index shuffled after replug → re-verify indexes (block above).
- Motor "no status packet" → loose 3-pin cable, reseat; `Overload error` latches → power-cycle follower PSU.
- Leader gripper range tiny → didn't squeeze the trigger during calibration.
- `lerobot==0.6.0` is latest on PyPI; git `main` is ahead — only upgrade between dataset generations.
