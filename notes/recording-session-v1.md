# Recording session v1 — cube ↔ box dataset

**Goal:** ~51 teleop demos on a standardised rig that feed **three** models off one
dataset — ACT (control), SmolVLA (the queued plan), and a MolmoAct2 fine-tune from
`lerobot/MolmoAct2-SO100_101-LeRobot`.

**Why this task:** Ai2's paper (arXiv 2605.02881, Table 7, 15 trials each) scores
this checkpoint on SO-100/101 real tasks — Pen-on-notebook 86.7%, Tissues 73.3%,
Fork-on-plate 70.0%, **Block-in-box 33.3%**, Stack-blocks 20.0%. We aim at its
documented weak spot and get a published baseline to beat.

**Scale check:** that checkpoint was pretrained on **1,222 public LeRobot datasets
from 377 users** — 38,059 episodes, 19.8M frames, ~184 h, TOPReward-gated. Our 51
episodes are ~0.13%. This is a **nudge, not a re-teach**. There is also therefore
*no canonical setup to match* — the prior is maximally diverse. Optimise for
internal consistency and signal quality, and for record ↔ rollout matching.

---

## Part 0 — Bill of materials

Already owned: SO-101 follower + leader, C922 (external), Innomaker (wrist),
black mat, white cube, container.

| Buy | Spec | ~Cost |
|---|---|---|
| White foam board ×5 | 20×30", 3/16". EU: A1 (594×841 mm) works, cut down | €25–40 |
| LED video light bar | **dimmable, diffuse, CRI ≥90, 4000–5600 K** (Neewer/Godox/Ulanzi class) | €35–50 |
| White gaffer tape | or 3D-printed foam-board corners (reusable) | €8 |
| *Optional* opaque container | replaces the translucent box — see §2.4 | €5 |
| *Optional* spare cubes | one went missing off-camera last session | €5 |

**Total ~€70–100.**

### Why a *video* light and not a desk lamp

Cheap LED dimmers use low-frequency PWM, which beats against a 30 fps rolling
shutter and produces **banding that varies frame to frame** — random noise injected
into every image, undiagnosable after the fact. Video lights are engineered
flicker-free for exactly this.

### Why the light is not optional

macOS gives zero UVC control (§A.2), so **scene brightness is the only lever you
have over exposure time**, and exposure time is what determines motion blur during
the grasp. This is the one purchase that improves image *quality* rather than
consistency.

---

## Part 1 — Build the rig

Follows NVIDIA's SO-101 workspace spec. Matching their numbers costs nothing extra
and keeps the sim2real option open (see §B).

### 1.1 Lightbox

- **30" W × 20" H × 20" D** (76 × 51 × 51 cm), front open — that's how you see in,
  teleoperate, and how the camera looks in.
- 5 panels: back (30×20), two sides cut to 20×20, top, bottom.
- Tape (fast, destroys the board later) or printed corners (reusable).
- **Arm pivot 12 cm from the back wall.** That leaves ~27 cm of enclosed depth in
  front of it — the region's far edge is at 27 cm, so it fits with margin.
- No camera slot needed: the camera lives outside the open front (§1.2).

*(An earlier draft said to rotate the box 90° for depth. That was a consequence of
mis-placing the camera behind the arm — with it in front, the standard orientation
fits fine.)*

Purpose: uniform diffuse light, neutral background, daylight eliminated. It turns
"lock the lighting" from a discipline problem into a structural one, and the white
walls bounce light onto the black mat, which fixes the dark wrist view.

⚠ **Ceiling clearance.** Worst-case arm height is **527 mm** (full vertical: lift
−17°, elbow −73°) vs a **508 mm** interior. Normal pick-and-place is nowhere near —
the MolmoAct2 ready pose peaks at 237 mm — but **do not hang the light inside the
top**. Use the open-top / external-mount option, or verify your home pose.

### 1.2 External camera — stays IN FRONT, just raised and tilted

⚠ NVIDIA's "27 cm from back of robot" reads as a rear mount, but their camera hole
is cut in a **20×20" panel** — a *side* panel in their build. Their external camera
is side-mounted looking diagonally across, not behind. Either way:

**The azimuth barely matters. The 45° tilt is the load-bearing part.** Keep the
camera in front, where it already is and where there is room.

> **Rule: height above the mat = horizontal distance to the region centre (0, 21).**
> That is 45°.

| Height | Place the lens at |
|---|---|
| 40 cm | Y = +61 cm |
| 30 cm | Y = +51 cm |
| 25 cm | Y = +46 cm |
| 20 cm | Y = +41 cm |

Pick whatever height the desk allows — the *ratio* is what matters. Mount at the top
of the front opening, looking down and back; you reach in underneath it at mat level.
C922, ~78° HFOV. Rigid mount, not a clamp arm that drifts.

**Why this matters more than anything else about the camera.** Measured from the
current low front view via `calib.json`:

- forward resolution **8.2 px/cm** (rows 300→479 span 10.5→32.2 cm)
- lateral resolution **16.8 px/cm** (row 380 spans −22.2→+14.2 cm)

**Forward distance is resolved at half the fidelity of sideways position** — and
forward distance is exactly what the policy must judge to reach the cube and clear
the box rim. A 45° tilt equalises them.

Geometry check for our layout: at 40 cm / 45°, ground coverage runs ~10 cm behind
the base to ~65 cm forward, ~90 cm wide at the region. Our 15–27 cm region sits
comfortably inside.

Rigid mount beats adjustable — repeatability is the whole point. Take a reference
screenshot once aimed.

⚠ Moving the camera **invalidates `gemini_er/calib.json`**. Re-shoot the ChArUco
calibration afterwards. That only affects the geometric fallback path, not any VLA.

### 1.3 Light

Diffuse LED bar, CRI ≥90, 4000–5600 K, dimmable, **50–100% brightness**, target
**~800 lux at the mat** (phone lux app is fine). Mounted above the open top, angled
to illuminate evenly.

Light from the front-side, not from behind the arm, so the arm's own shadow doesn't
land on the cube at the moment it matters. Diffuse is the operative word — it kills
the specular highlights on the container, which otherwise move with the arm and act
as distractors.

Lights get warm. Don't leave them on overnight.

### 1.4 Cameras: exactly two

`MolmoAct2-SO100_101` expects exactly `cam0`/`cam1`; a third view has nowhere to go
in that processor. DROID uses three and the SmolVLA paper says top/wrist/side, but
for this checkpoint the answer is **two**.

Record with descriptive names, remap per model at train/rollout:

| Model | Expected keys | Note |
|---|---|---|
| ACT | any | no language input at all |
| SmolVLA | `camera1` = top/front, `camera2` = wrist | pretraining convention; needs `--rename_map` |
| MolmoAct2 | `cam0`, `cam1` | `--rename_map` at rollout |

Keep the recording names `workspace_cam` / `wrist_cam` and map from there.

### 1.5 Cables

Route camera and robot cables **out of the workspace and behind the arm**. NVIDIA
flags this as worse than visual noise: snagging cables *"can create false
calibration limits"*. There are currently several draped across the right side.

---

## Part 2 — Workspace layout

### 2.1 Reach — measured from our own URDF

No published workspace standard exists for SO-101 data collection, so geometry comes
from the arm. FK over `phone_teleop/SO101/so101_new_calib.urdf`, radii from the
**centre of the rotating base** (pan axis, 38.8 mm forward of base_link), TCP 0–35 mm
above the mat (`calib.json` puts the mat 17.4 mm *below* the base plane):

| Condition | Reachable radius |
|---|---|
| Geometric limit | 13 – 306 mm |
| Well-conditioned (joints ≥30° inside limits) | **63 – 300 mm** |

Links: upper arm 116 mm, forearm 135 mm, wrist→TCP ~162 mm. Pan ±110°. Vendor spec
says 300 mm reach / 200 g payload — matches. Cross-check: a ~34 cm chessboard was
judged out of reach. 340 > 306 ✓

**Working band: 150–270 mm.** Below ~80 mm the arm's own body is in the way; above
~280 mm it sags and loses precision.

Validation: the MolmoAct2 ready pose puts the TCP at **x = 253 mm, y = −11 mm** —
the checkpoint already likes to start over the far edge of this region.

### 2.2 The region

**150 mm wide × 120 mm deep**, near edge 150 mm, far edge 270 mm from the base
centre, on the forward axis. Far corners ~280 mm — inside the band.

3×3 grid → cells **50 × 40 mm**.

```
                 <- X ->
        -7.5   -5   0   +5   +7.5  cm
          +-----+-----+-----+         Y=27   far edge
          |     |     |     |
          +-----+--o--+-----+         Y=23   (o = cell centre)
          |     |     |     |
          +-----+-----+-----+         Y=19
          |     |     |     |
          +-----+-----+-----+         Y=15   near edge
                  ^
                  |  15 cm of nothing
                  o  base pivot (0,0)
```

- **(0,0)** = the pivot of the rotating base. **Y** = forward, **X** = sideways.
- Cell centres: **Y = 17, 21, 25**; **X = −5, 0, +5**.
- **Not 7 cm.** 63 mm is where the arm stops colliding with itself, not where it
  works well — elbow folded back, wrist cramped.

**Design rule: vary position laterally, not radially.** Pan is cheap (±110°), reach
is expensive (120 mm of usable band).

Why small at all: ggando's SO-101 result — "50 demos across 30 cm just wasn't enough
density"; 75 eps in a ~10 cm workspace hit 100%. And our own `act_v3` failed
left-of-centre because only 5/20 episodes were left-of-centre.

### 2.3 Marking it — without contaminating the frames

**Nothing goes in the frame that helps *you* aim.** A visible grid is a coordinate
system the network memorises instead of learning the gripper-to-cube relationship
(camera-conditioning result, arXiv 2510.02268: policies infer pose from static
background cues and collapse when geometry shifts). **No ChArUco board, no printed
grid** during recording.

**Removable placement template:** print a 3×3 grid of 50×40 mm cells on card. Per
episode — lay it, place the cube, **lift it away**, then record. ~3 s per episode,
zero contaminated frames.

Keep: the black mat (NVIDIA uses black EVA foam too) and the tape border — a single
boundary is one feature, not a coordinate system. Flag the border as a v2 ablation.

### 2.4 The box — beside the region, not beyond it

Outside the region, offset laterally, **same radial band**: centre ~**X = ±17,
Y = 14** (≈22 cm from the pivot). Pan covers it for free.

- **Not beyond the far edge** — that pushes the release, the most accuracy-critical
  moment, past 270 mm into the sag zone.
- **Not inside the region** — it would eat cells and occlude them.
- Adjust so the box's near edge clears the region by ≥3 cm; depends on box width.
- **Low-sided open container** — `box → mat` needs the cube *visible* inside.
- Mark the footprint **underneath the box** so it's restorable after a knock.
- Keep it on the **left**, where it already is (also matches NVIDIA's layout, which
  costs nothing and helps if the sim2real option is ever taken).

**Consider replacing the translucent box.** Clear plastic is low-contrast against
the black mat and shows the background through it. Box placement is the model's
documented weak spot and half the episodes target it — a matte, solid-coloured
container with a defined rim is a strictly easier visual target.

Fixed position for v1. Box position is a second variation axis 51 episodes can't
afford — that's v2.

---

## Part 3 — Verify before recording

1. **Camera indexes** — macOS reshuffles on replug, every session, no exceptions:

```bash
~/.local/share/uv/tools/lelab/bin/python -c "
import cv2
for i in range(3):
    c=cv2.VideoCapture(i); [c.read() for _ in range(30)]; ok,f=c.read(); c.release()
    print(i, round(f.mean(),1) if ok else 'FAIL')"
```

2. **Teleop reach check — blocking, before printing the template.** Drive the
   gripper down to all 9 cell centres and into the box. Confirm none is at the edge
   of travel or forces an awkward wrist pose. If a corner cell is bad, shrink the
   region or move the box. The FK assumes the base mounting plane sits at a known
   height; a riser or edge-clamp shifts every radius.
3. **Brightness** — log it, and re-check every ~10 episodes.
4. **Focus hunting** — record 60 s of teleop, scrub it, look for focus breathing or
   brightness jumps when the mat or box fills the frame. Only chase it if it's real
   (see §A.2 — there is no software fix on macOS).
5. **Reference screenshots** of both views, saved in the repo.

---

## Part 4 — Baseline measurement (BEFORE recording)

Do not skip. Without a "before" number the fine-tune is unfalsifiable, and both
directions currently have n≈1.

**10 trials `mat → box`, 10 trials `box → mat`**, zero-shot with the current
MolmoAct2 stack. Let the ER 2 orchestrator run and score them — it already does
run → verify → retry autonomously.

⚠ ER 2's success verification is ~87.7% accurate. Spot-check the tally by hand.

Log to `gemini_er/data/baseline_v1.jsonl`, copy the numbers into `journal.md`.

**These numbers decide the episode split.**

---

## Part 5 — Recording

### 5.1 Split (default; revise from Part 4)

| Dataset | Task string | Conditions | Eps |
|---|---|---|---|
| `mat → box` | `put the white cube in the box` | 9 cells × 3 orientations (full factorial) | **27** |
| `box → mat` | `take the white cube out of the box` | 6 in-box placements × 4 repeats | **24** |
| | | | **51** |

`mat → box` is a clean 3×3 × {0°, 45°, 90°} factorial — every position sees every
orientation. That's the fix for the `act_v3` confound where orientation and position
were tangled.

`box → mat` placements: centre, against each of the four walls, one corner. Vary
cube yaw across the 4 repeats.

Extraction gets **higher density per condition** automatically, because the box
constrains where the cube can be. If Part 4 comes back lopsided — say extraction at
20% and placement at 70% — shift to ~32/16 toward the weak side. Fine-tuning at
0.13% of pretraining volume buys the most where the base model is worst.

### 5.2 Orientation is varied, not taught

The old rule — "a 40-ep dataset can't learn position AND orientation invariance" —
was about **ACT trained from scratch**. It does not apply here. MolmoAct2 zero-shot
already grasped a ~45°-rotated cube; orientation invariance is in the prior.

Orientation variation here is **regularisation, not curriculum**: it stops the
fine-tune from collapsing a capability the base model already has onto whichever
single orientation you happened to record.

### 5.3 Two task strings, not one

One string across all 51 makes the language channel carry zero information, and the
action expert can learn to ignore it — costing the mid-episode steering that's
already verified on hardware. Two directional strings keep language informative
while sharing ~90% of the visual structure. It also gives ER 2 a second verb, which
is the difference between a planner and a button.

The A/B stays clean via the **evaluation** split, not the training split — see §8.

### 5.4 Per-episode routine

1. Lay template → place cube (cell + orientation from schedule) → lift template.
2. → to start.
3. Drive **slow**. Teleop lag degrades demo quality.
4. **One grasp strategy, every time.** Mixed strategies produce an erratic policy at
   identical training loss.
5. ~15–20 s. MolmoAct2's own training episodes average ~17 s; community SO-101
   episodes run 9–18 s.
6. Bad demo → ← and re-record. Do **not** keep it to delete later —
   `delete_episodes` is fragile on multi-resume datasets and gutted a dataset here
   once.
7. Every 10 episodes: re-check camera indexes and brightness.

### 5.5 Commands

```bash
# mat -> box (27 eps)
PATH="$HOME/.local/share/uv/tools/lelab/bin:$PATH" lerobot-record \
  --robot.type=so101_follower --robot.port=/dev/tty.usbmodem5AE60832001 --robot.id=arm \
  --robot.cameras="{ workspace_cam: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist_cam: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}" \
  --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodem5AE60538411 --teleop.id=arm \
  --display_data=true \
  --dataset.repo_id=kris0/so101_cube_box_v1_matbox \
  --dataset.single_task="put the white cube in the box" \
  --dataset.num_episodes=27 --dataset.episode_time_s=20 --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false

# box -> mat (24 eps) — same command, different repo_id + task string
  --dataset.repo_id=kris0/so101_cube_box_v1_boxmat \
  --dataset.single_task="take the white cube out of the box" \
  --dataset.num_episodes=24
```

`lerobot-record` takes one `--dataset.single_task` per run → two runs, two datasets.
Keys: → next, ← re-record, ESC stop.

*(No `fourcc: "MJPG"` — it is a no-op on macOS, see §A.1.)*

---

## Part 6 — Post-recording

1. **Push both to Hub before any editing.** A gutted dataset was recovered from a
   Hub copy once already.
2. **Merge** into one dataset — per-episode task strings are preserved:
   `lerobot-edit-dataset --operation.type merge ...` (check `--help` for arg names;
   unverified).
3. **Quantile stats** — MolmoAct2 normalises on quantiles, and recorded stats are
   the conservative min/max envelope, not true quantiles:

```bash
~/.local/share/uv/tools/lelab/bin/python \
  ~/.local/share/uv/tools/lelab/lib/python3.12/site-packages/lerobot/scripts/augment_dataset_quantile_stats.py \
  --repo-id=kris0/so101_cube_box_v1 --overwrite --skip-images
```

4. Eyeball episodes in the dataset viewer before spending GPU money. Check for
   glare, motion blur, occlusion, objects leaving frame.

---

## Part 7 — Training: three models, one dataset

### MolmoAct2 (the experiment)

From the **LeRobot-format SO-101 checkpoint**, so the joint-sign/offset correction,
processor and norm stats come along:

```
--policy.path=lerobot/MolmoAct2-SO100_101-LeRobot     # NOT --policy.checkpoint_path
--policy.train_action_expert_only=true                # requires action_mode=continuous
--policy.action_mode=continuous
--policy.device=cuda --policy.model_dtype=bfloat16
--policy.gradient_checkpointing=true
--batch_size=16                                       # docs: 16–32 for <200 real demos
```

- ~16.5 GiB @ bs 8, ~18.3 @ bs 16 → fits the L4; comfortable on A100.
- `train_action_expert_only` is **incompatible** with `enable_lora_vlm` — pick one.
  Expert-only first; LoRA-VLM (~20.2 GiB @ bs 8) is run two.
- **Not** the paper's 100k steps / batch 64 — that was 8×H100 on 38k episodes.

### SmolVLA (the queued plan)

51 eps is right at the proven floor of 50 (25 is documented insufficient). Batch 64,
20k steps ≈ 4 h A100, keep baked-in defaults (lr 1e-4, `freeze_vision_encoder`,
`train_expert_only`). **On 0.6.0 never set `train_expert_only=false`** — buggy until
0.6.1. `--rename_map` to `camera1`/`camera2`.

### ACT (the control)

Train on the **un-merged `mat → box` dataset** (27 eps), defaults, ~1 h on Colab.
No language input, so it can only ever learn one direction.

---

## Part 8 — Evaluation

- **15 trials per condition, partial credit** — Ai2's Table 7 protocol, so the
  number is directly comparable to their 33.3%.
- Evaluate **all models on `mat → box`** so the comparison is clean. The
  `box → mat` episodes are the VLAs' bonus and don't enter the A/B.
- Same lighting, camera positions and task strings, byte-identical.
- Record rollouts (`lerobot-rollout --strategy.type=episodic`) so failures are
  reviewable.
- Compare against the Part 4 baseline **and** against Ai2's 33.3%.

---

## Do NOT vary in v1 (v2 axes)

Box position · lighting level or lamp position · camera positions · cube
colour/size · distractors · surface.

Each is a real generalisation axis, and each one added to v1 halves the density of
everything else. **v2 = add ONE of them, plus DAgger corrections on whatever v1
fails at.**

---

## Appendix A — Measured facts (2026-08-13)

### A.1 MJPG does not work on this Mac

OpenCV uses the AVFOUNDATION backend. `set(CAP_PROP_FOURCC, MJPG)` → `False`;
`get()` → 0.00. LeRobot's `fourcc:` option goes through the same
`cv2.VideoCapture`, so it is a no-op. Don't add it.

**The wedge didn't reproduce:** both cameras at 640×480 simultaneously gave
**60/60 successful paired reads each**. The Innomaker wedging is *intermittent*,
not a bandwidth ceiling. Monitor dropped frames during the session; don't pre-fix.

### A.2 No exposure/focus control exists on macOS

Every property reads 0.00 and every `set()` returns `False` — BRIGHTNESS, CONTRAST,
SATURATION, GAIN, EXPOSURE, AUTO_EXPOSURE, AUTOFOCUS, FOCUS, AUTO_WB, TEMPERATURE.
Mean brightness stayed at 49.6 across the entire sweep.

Remaining options: **physical light** (the plan), `uvc-util`
(github.com/jtfrey/uvc-util — not installed, needs building), or taping the focus
ring.

### A.3 The Innomaker does 1080p

`journal.md` says "it only does 640x480". **False** — 640×480, 1280×720 and
1920×1080 all return the requested size, all at mean brightness ~43–50. The
darkness is the scene, not the mode. Recording stays 640×480@30 to match convention.

### A.4 The wrist "darkness" is a misleading metric

Mean 44 vs 129 looks alarming, but the black mat fills ~90% of the wrist view. The
task-relevant content is fine: the container is clearly resolved, the gripper
fingers are crisp, and a white cube on a black mat is about the highest-contrast
target available. More light is still worth it — for **motion blur and sensor
noise**, not visibility.

### A.5 The workspace camera was never overhead

Notes and crib-sheet both call cam 0 "overhead C922". It is a **low front view at
roughly desk height**. Fix the naming everywhere. Pre-move measurements via
`calib.json` (homography still accurate to 1.5–8.3 mm): forward extent ~10→32 cm,
lateral −22→+13 cm, aimed ~5 cm left of centreline, base origin at pixel (319, 230).

---

## Appendix B — Why the rig matches NVIDIA's spec

NVIDIA's SO-101 sim-to-real course publishes the only concrete SO-101 workspace
spec that exists. Matching it costs nothing and preserves an option:

- **Isaac Sim/Lab needs Linux or Windows** — no macOS — plus RTX 4080+ with RT
  cores. **"GPUs without RT Cores (A100, H100) are not supported"** — the Colab
  A100 is named in the exclusion.
- Their released checkpoints are **GR00T N1.6**; lerobot 0.6.0 supports N1.7 only.
- Their own Strategy 4 says the SO-101's **hobby servos introduce significant
  backlash that compounds through the kinematic chain** — the core reason sim2real
  is hard on this arm. Their fix (GapONet) is still research.
- Their best models are **75 sim + 50 real, co-trained**. Sim-only is the baseline
  Strategy 2 exists to beat.

**So real demonstrations are on the critical path either way** — this session is a
prerequisite for sim2real, not an alternative to it.

**Cheap sim2real without Isaac Sim:** their datasets are LeRobot-format on the Hub
(`sreetz-nv/so101_teleop_vials_rack_left*`, 75 sim / +5 real / Cosmos-augmented
+7 / +70). You could co-train GR00T N1.7 in lerobot on a rented A100 with no Isaac
Sim at all — but it means adopting *their* task (vials → yellow rack, ~€20 of
props). Worth noting that precise insertion into a slotted rack is arguably closer
to chess than dropping a cube in a box.

---

## Quick checklist

- [ ] Foam board, LED bar, tape ordered
- [ ] Lightbox built, camera slot cut, front open
- [ ] C922 at 40 cm / 27 cm behind / 45° down, rigid, reference screenshot taken
- [ ] Light mounted above open top, diffuse, ~800 lux at mat, brightness logged
- [ ] Cables routed out of the workspace and behind the arm
- [ ] Region taped: Y 15→27 cm, X ±7.5 cm; template printed
- [ ] Box placed left, ≥3 cm clear of the region, footprint marked underneath
- [ ] ChArUco re-shot (camera moved → old homography void)
- [ ] Camera indexes verified; teleop reach check on all 9 cells + box
- [ ] Baseline 10 + 10 zero-shot trials, hand-spot-checked, in `journal.md`
- [ ] Split revised if lopsided
- [ ] 27 + 24 episodes, slow, one grasp strategy, bad ones re-recorded
- [ ] Pushed to Hub, merged, quantile stats added, episodes eyeballed
- [ ] MolmoAct2 expert-only + SmolVLA + ACT trained
- [ ] 15-trial eval on `mat → box` vs baseline and vs Ai2's 33.3%
- [ ] `journal.md` entry
