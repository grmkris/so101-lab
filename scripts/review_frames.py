"""Extract 3 frames (start/mid/end) per episode for VLM review."""
from pathlib import Path
from PIL import Image
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

ROOT = "/Users/kristjangrm/.cache/huggingface/lerobot/kris0/so101_pick_place"
OUT = Path("/tmp/ep_review"); OUT.mkdir(exist_ok=True)

ds = LeRobotDataset("kris0/so101_pick_place", root=ROOT)
n = ds.meta.total_episodes
print("episodes:", n)

# episode frame boundaries
try:
    efrom = ds.episode_data_index["from"]
    eto = ds.episode_data_index["to"]
    bounds = [(int(efrom[e]), int(eto[e])) for e in range(n)]
except Exception as ex:
    print("episode_data_index unavailable, scanning episode_index column:", ex)
    epcol = ds.hf_dataset["episode_index"]
    bounds = []
    for e in range(n):
        idxs = [i for i, v in enumerate(epcol) if int(v) == e]
        bounds.append((idxs[0], idxs[-1] + 1))

LIMIT = 3  # test on first 3 episodes; set to n for full run
for e in range(min(LIMIT, n)):
    a, b = bounds[e]
    for j, fi in enumerate([a, (a + b) // 2, b - 1]):
        img = ds[fi]["observation.images.front"]
        arr = (img.permute(1, 2, 0).numpy() * 255).astype("uint8")
        Image.fromarray(arr).save(OUT / f"ep{e:03d}_{j}.jpg")
    print("episode", e, "-> 3 frames saved")
print("done. frames in", OUT)
