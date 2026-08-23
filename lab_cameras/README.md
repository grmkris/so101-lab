# `lab_cameras` — one owner for the lab's cameras

Two cameras, three consumers (lerobot recording, the vision loop, previews), one
kernel owner per V4L2 device. Everything that touches `/dev/cam_*` goes through
here.

```python
from lab_cameras import CameraOwner

with CameraOwner(mode="vision") as cams:
    f = cams.latest("workspace")        # raises if the newest frame is stale
    bgr, seq, age = f.bgr, f.seq, f.age_ms
```

**Rule: no code outside this package may call `cv2.VideoCapture` on `/dev/cam_*`.**
That rule, not the architecture, is what prevents a stray YUYV open.

## CLI

```bash
python -m lab_cameras probe      # what the kernel offers; is MJPG really available
python -m lab_cameras who        # who owns the cameras right now
python -m lab_cameras snap       # one JPEG per camera
python -m lab_cameras watch      # live fps / repeat / stall counters
python -m lab_cameras recover    # the documented fix after a UVC hang
```

Dataset health gate (offline, run before trusting a dataset):

```bash
python -m lab_cameras.health <dataset-root> --stride 3
```

## What it guarantees, and why each one is here

| Guarantee | The failure it prevents |
|---|---|
| **MJPG is asserted after open**, not merely requested | YUYV at 640×480 exceeds the USB 2.0 isochronous budget through a hub; the Innomaker hangs outright (0/1800 frames, kernel `EPROTO`) and takes the healthy C922 through a USB reset with it |
| **`flock` on `/run/lock/lab-cams.lock`** | the kernel releases it on `kill -9`; a PID file does not (verified: SIGKILL the owner, the next process opens cleanly) |
| **monotonic per-camera seq + real capture timestamp** | a camera that dies quietly otherwise repeats its last frame into a dataset and nothing notices |
| **`latest()` raises past `max_age_ms`** | a stale frame is the failure this module exists to surface, so it is never returned quietly |
| **byte-identical-frame counter** | catches a frozen sensor live, not three weeks later at training time |
| **`/data/session.json`** | `~/labstatus.py` already reads it, so the LCD shows ownership for free |

## Measured on `lab-pi` (2026-08-23)

Both cameras, MJPG 640×480, direct-attached, 20 s:

| camera | fps | read failures | repeated frames |
|---|---|---|---|
| workspace (C922) | 30.9 | 0 | 0 |
| wrist (Innomaker) | 29.5 | 0 | 0 |

**Do not set `CAP_PROP_BUFFERSIZE=1`.** Measured: it halves the Innomaker
(74 → 37 frames per 3 s) and does nothing for the C922. The reader thread already
drains the queue continuously, so latest-wins comes from the loop, not from
starving the driver. This cost an afternoon — the symptom is the wrist camera
opening as MJPG and then delivering nothing at all.

## Health-gate baselines

Both existing training datasets are clean — the Innomaker's known frame loss did
**not** corrupt them:

| dataset | frozen runs | cross-camera MAD |
|---|---|---|
| `kris0/so101_pickplace_wall_v1_20260722_174720` | 0 | 85.5–88.1 |
| `kris0/so101_blue_pegs_v1_20260723_171824` | 0 | 86.0 |

Cross-camera MAD near zero would mean the two feature keys carry the same
picture. ~86 means they are genuinely different views.

Note: LeRobotDataset **v3 packs many episodes into one `file-NNN.mp4` per camera**,
so the gate reports per video *file*, not per episode.
