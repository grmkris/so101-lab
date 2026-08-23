# Dedicated lab setup — host topology + room layout (2026-08-21)

Decision doc for the move into a dedicated room. Two independent questions:
**(A) what owns the USB**, and **(B) where the cameras go**.

---

# A. Host topology

> **Revised 2026-08-21 (v2)** after constraints landed: no local GPU (rent on
> demand), a CPU server in Germany, a MacBook — and **the arm now lives in a
> different room**. That last one is not a detail: it makes remote access a
> requirement, not a convenience, and it kills the "swap the USB-C cable" plan.

## The shape: three layers, and the USB never moves

```
  ROOM (24/7)                YOU                    RENTED, ON DEMAND
  ┌───────────────┐          ┌──────────┐           ┌─────────────────┐
  │ mini PC       │◄─Tailscale─┤ MacBook  │           │ GPU box (EU)    │
  │  ├ follower   │          │ ssh +    │           │ policy_server   │
  │  ├ leader     │          │ browser  │           │ lerobot-train   │
  │  ├ cam ctx    │          └──────────┘           │ Isaac Lab       │
  │  ├ cam wrist  │◄───────────────────────────────►│                 │
  │  └ room cam   │      robot_client ⇄ chunks      └─────────────────┘
  └───────────────┘
          ▲
   smart plug on servo PSU (remote hard e-stop)

  DE server: Tailscale subnet/exit node, hub, HF dataset mirror. NOT in the loop.
```

**Nothing is ever unplugged or swapped.** The room host owns the USB permanently.

## Drop the "one hub → swap between MacBook and Pi" idea

It was the right ergonomic goal before the arm moved rooms. Now it is
self-defeating: swapping the cable means *walking to the other room*, which is the
exact thing you are trying to stop doing. And it still costs:

- **Re-enumeration on every flip** → camera indexes shuffle (hard-won lever #4).
- **Two lerobot envs to keep pinned at 0.6.0** → drift (hard-won lever #1).
- Two different camera-control stories (macOS can't set exposure or MJPG; Linux can),
  so a dataset recorded "from the Mac" is not comparable to one recorded "from the Pi".

The hub agent you already built *is* the swap. Mac drives the rig over the network.

## Room host: it is an **ODROID-HC4**, not an H4. Different board entirely.

> **Correction (2026-08-22).** Earlier revisions of this note assumed an ODROID-**H4**
> (x86 Alder Lake-N). The actual hardware is an ODROID-**HC4**. Everything about x86,
> QuickSync, DDR5 and 2×USB3+2×USB2 is void.

| | ODROID-HC4 (actual) | what v2 assumed (H4) |
|---|---|---|
| SoC | Amlogic S905X3, **4× Cortex-A55 @ 1.8 GHz, ARM64** | Intel N97 x86 |
| RAM | **4 GB DDR4, not upgradable** | up to 48 GB DDR5 |
| USB | **1 × USB 2.0 host port. That is all.** | 2×USB3 + 2×USB2 + 3 on header |
| Storage | 2× SATA, microSD, SPI/petitboot | M.2 NVMe |
| Video encode | **none** | QuickSync H.264/HEVC |
| Net | 1× GbE | 2× 2.5 GbE |
| Power | DC 15 V / 4 A | DC 11–20 V |

Cortex-A55 is an *efficiency* core — this is **slower than a Raspberry Pi 4** (A72) and
far slower than a Pi 5 (A76). It is a NAS board, and a good one. It is a poor robot host.

### What this means for the USB question

**Everything goes through one USB 2.0 port.** One hub, one 480 Mbps bus (~384 Mbps
isochronous), no second controller to split across. Budget at 640×480@30:

| Load | Cost | Verdict |
|---|---|---|
| 2 arms (full-speed serial) | <2 Mbps | negligible |
| 2 cameras **YUYV** | ~295 Mbps | **77% — marginal. This is the bug.** |
| 2 cameras **MJPG** | ~60 Mbps | ~16% — comfortable |
| 4 cameras **MJPG** | ~120 Mbps | still fits (the ablation is viable) |
| 4 cameras YUYV | ~590 Mbps | impossible |

**So: yes, 2 arms + 2 cameras fit — but MJPG is now mandatory, not advisory.** And the
"put the servo bus on its own controller" rule from v2 is **unavailable**: there is only
one port. Compensate with a **powered multi-TT hub** so the two full-speed arm boards get
separate transaction translators instead of sharing one with each other.

### The three real risks

1. **ARM64 wheels.** lerobot #1738 is a bare `Illegal instruction` on ARM. Cortex-A55 is
   ARMv8.2 so it may be fine — but this is unproven and it is the **kill criterion**.
2. **No hardware video encoder**, on a weak CPU. lerobot defaults to **libsvtav1** (AV1).
   Encoding two 640×480@30 streams on four A55 cores will be painful. Mitigations, in
   order: switch to `libx264 -preset ultrafast`; record frames as images and encode later
   on the Mac/DE server; or accept long gaps between episodes.
3. **4 GB RAM, fixed.** No local policy inference. Async policy server only.

### Verdict: split the roles, and time-box it

The HC4 is genuinely good at being a **dataset NAS + always-on Tailscale node** — two
SATA bays, low power. Let it do that regardless.

As a **robot host**, give it a bounded trial:

- ✅ **Phase 1 (likely fine):** owns the USB, runs the hub agent, MJPEG re-serve, remote
  teleop, arm safety. Low CPU. This alone solves "the arm is in another room".
- ⚠️ **Phase 2 (the trial):** lerobot dataset recording. Kill criteria — if lerobot 0.6.0
  won't import/run on ARM64, or per-episode encode time is worse than ~10 s, stop.
- ❌ **Never:** ACT/VLA inference, training, Isaac. Those were always off-box anyway.

If Phase 2 fails, the fallback is unchanged from v2 — a ~€150 N100-class x86 box — and
the HC4 keeps the NAS job it is actually built for. Recording is the *only* thing at risk,
and it is the thing the whole lab exists to do, so find out early.

### Boot notes

- The SSD came out of a Raspberry Pi, so it holds an **ARM64 Pi image with the Pi's
  bootloader** — it will not boot the HC4 (different SoC, u-boot and device tree).
  Physically fine; needs a fresh install. **Back up anything on it first.**
- **If it is a 2.5" SATA SSD it drops straight into the HC4 bay.** If it is an M.2 NVMe
  (a Pi 5 HAT drive) it **does not fit the HC4 at all** — no M.2 slot.
- Use **Hardkernel's own Ubuntu 24.04 image**, not Armbian: recent Armbian on HC4 has
  documented breakage (petitboot conflicts, SATA not detected, USB keyboard dead).
- Easiest reliable path: **image a microSD, boot from that**, get SSH up, then move root
  to SATA later via petitboot if wanted.

## The hub problem — what actually went wrong, and what fixes it

Short answer: **partly the hub, mostly the format, and it is only fixable on Linux.**

**1. Every USB3 hub funnels all your USB2 devices onto ONE 480 Mbps bus.**
The C922 and the Innomaker are USB 2.0 high-speed devices. Plugging them into a
"10 Gbps USB-C hub" does not give them SuperSpeed lanes — they sit on the hub's
single high-speed upstream, sharing 480 Mbps (isochronous capped at ~80% ⇒ ~384 Mbps).
**No hub brand changes this.** So yes — this part would have happened with any hub.

**2. The format is the real culprit.** At 640×480@30:

| Format | Per camera | Two cameras vs ~384 Mbps budget |
|---|---|---|
| YUY2 / raw | 640·480·2·30 = 18.4 MB/s ≈ **147 Mbps** | ~295 Mbps — *fits on paper* |
| MJPG | ≈ 3–5 MB/s ≈ **25–40 Mbps** | ~10× headroom |

"Fits on paper" is exactly why our own test passed **60/60 paired reads** and the
session still wedged 20 minutes later (`recording-session-v1.md` A.1: *"intermittent,
not a bandwidth ceiling"*). uvcvideo/AVFoundation reserve against the endpoint's
**declared** max payload, which webcams over-declare — so allocation fails
unpredictably rather than cleanly. Add a third stream for the camera ablation and it
stops being marginal and starts being impossible.

**MJPG is the fix, and macOS cannot set it** — measured: `CAP_PROP_FOURCC`→MJPG
returns `False`, lerobot's `fourcc:` is a no-op there (A.1). On Linux,
`backend=V4L2` + `fourcc="MJPG"` is exactly what resolved lerobot #3198, the same
symptom. **This single fact is the strongest argument for the room host.**

**3. The arms are a *different* problem — that one IS the hub.** The SO-101 boards
enumerate as `usbmodem`/CDC serial: almost certainly **full-speed (12 Mbps)** devices.
Full-speed devices below a high-speed hub go through its **transaction translator**.
A **single-TT** hub shares one TT across *all* full-speed devices — two arm boards
plus anything else, sharing one scheduler. That produces latency jitter on the servo
link, which is precisely how Feetech read timeouts and mid-episode arm drops happen.
Confirm with `lsusb -t` (look for `12M`) and `lsusb -v` (`bDeviceProtocol 02` = multi-TT).

**4. Bus power.** Two cameras + two servo boards off a bus-powered hub will brown out.

## Hub buying rules

1. **Self-powered**, its own PSU, ≥ 3 A (60 W-class is safer with 4+ devices).
2. **Multi-TT** — matters for the arms, not the cameras.
3. **uhubctl-compatible (per-port power switching).** This is the sleeper feature
   given the arm is in another room: when a camera wedges you power-cycle *that port*
   over SSH instead of walking upstairs. Check the compatibility table at
   [mvp/uhubctl](https://github.com/mvp/uhubctl), or `lsusb -v | grep -i "per-port power"`.
   Very few hubs qualify — buy from the list, not from Amazon reviews.
4. **Cameras and arms on separate hubs**, or arms straight into host ports. Ideally
   split across the two root controllers so a camera storm cannot starve the servo bus.
5. **Force MJPG on every camera** via V4L2 and verify the *delivered* frame size — the
   C922 renegotiates to 640×360/320×180 after re-cabling (journal 2026-08-13).
6. Sanity-check the resulting tree with `lsusb -t` before believing any of it.

## Scaling to three arms: **arms are free, cameras are expensive**

This is the whole law. One SO-101 serial bus is a **full-speed 12 Mbps device using
~0% CPU**. One raw camera is **147 Mbps**. So you size hosts by *camera count*, never
by arm count. Three arms on the H4 is six serial devices — irrelevant. Three arms with
six cameras is the actual question.

**First, which kind of "two more arms"?** It forks hard:

- **Cooperating / bimanual — one task, one dataset.** Then they **must** share one
  host. A lerobot episode is one synchronized observation+action vector; splitting
  arms across machines injects clock skew straight into the training data. The H4
  handles this: arms onto the USB2 header pigtails, cameras onto hubs.
- **Independent rigs** (a chess opponent, a second station, a friend's arm). Then they
  are separate rigs and **your hub already does multi-rig natively** — `kris-sim` and
  `kris-arm` register independently today. Each gets its own brain.

**When you do need more brains, in order of preference:**

1. **Nothing.** Hang them off the H4 until the camera budget actually breaks.
2. **Something you already own** — an old laptop, the megabook. Any x86 + Linux.
3. **A Pi for a camera-less rig only.** If a rig is pure actuation and its cameras live
   on a neighbouring host, a Pi 4 / Zero 2 W is plenty — it's 12 Mbps of serial.
   (Caveat: this only works for teleop/eval. For *dataset recording*, the cameras and
   the arm must be in the same process, so a recording rig owns its own cameras.)
4. Buy a box. Last resort.

**And when the USB2 bus does fill up, the upgrade is cameras, not computers.** A
**USB 3.0 (SuperSpeed) camera gets its own 5 Gbps lane** and never touches the
480 Mbps USB 2.0 bus at all. Budget with MJPG at ~25–40 Mbps/stream: 4–6 USB2 cameras
at 640×480@30 is realistic on one root bus; past that, buy SuperSpeed cameras.

## Because the arm is unattended in another room

- **Tailscale** on room host + MacBook + DE server. SSH by name from anywhere.
- **systemd units** for the hub agent (`Restart=always`) so a reboot self-heals.
- **Smart plug on the servo PSU** — remote hard e-stop and power cycle. €15. The
  software e-stop cannot save you from a wedged process.
- **A third, wide-angle "room cam"** that is *not* a training camera, streaming to the
  hub. Rule: **never command an arm you cannot see.** The existing camera watchdog
  (caught an Innomaker death in 13 s) stays.
- Wake-on-LAN or a BIOS "restore power state = on" setting so the smart plug can also
  recover the mini PC itself.
- Door closed. Cat out. Arm clamped, not resting on the desk.

## Renting the GPU: use lerobot's async split

lerobot ships exactly the architecture this calls for: **`policy_server` on the rented
GPU, `robot_client` on the room host.** Action chunks are latency-tolerant by
construction (that is the whole point of async), so a WAN hop is acceptable — pick an
**EU region** to keep RTT ~20–40 ms, and tune `chunk_size_threshold` (start 0.5–0.6)
with `--debug_visualize_queue_size`.

**Test it for free first:** MacBook as the policy server over Tailscale (MPS measured
~12 Hz), room host as the client. If that loop holds, renting is just a faster server —
no new architecture. Do this before paying anyone.

Training and Isaac Lab stay entirely on the rented box; they never touch the arm.
Isaac needs Linux + **RT cores** — so rent RTX, not A100/H100 (explicitly excluded).

The German server is a **coordinator, not a compute node**: Tailscale subnet/exit node,
optionally the hub (replacing Railway, which loses in-memory state on redeploy anyway),
and an HF dataset mirror/backup. CPU-only training is not viable — don't try.

## Shopping list (approx, EUR)

| Item | ~€ | Note |
|---|---|---|
| ~~Mini PC~~ **already owned: ODROID-H4** | **0** | add RAM/NVMe only if short |
| Powered multi-TT, uhubctl-capable USB3 hub | 30–60 | buy from the uhubctl list |
| Replacement wrist camera (2nd C922 or fixed-focus UVC) | 40–90 | Innomaker condemned |
| Wide-angle room/safety cam | 20–40 | not a training camera |
| Smart plug (servo PSU) | 15 | remote hard e-stop |
| Short right-angle USB cables + velcro | 20 | strain relief, cables behind the arm |
| Ethernet run / powerline to the robot room | 0–40 | H4 has no WiFi; wired beats a dongle |
| **Total** | **~125–265** | GPU stays rented; no new computer |

## Open question

You mentioned both a "megabook" and a MacBook. If the megabook is an **x86
Windows/Linux laptop**, it is a better free policy server and MuJoCo box than the Mac
(and could even be the room host if you're willing to leave it there). If it was
dictation for "MacBook", ignore this.

---

# B. Room layout

## What's wrong with the room today (photo, 2026-08-21)

Fix these before any geometry decisions — they dominate everything below:

1. **The window.** Direct daylight varying by hour and season is the single largest
   uncontrolled variable, and lever #2 says brightness is load-bearing (~120 works,
   ~50 fails). **Blackout blind or heavy curtain, non-negotiable.** Otherwise every
   dataset is silently timestamped by the sun and cross-dataset comparison dies.
2. **Litter box under the desk.** Dust on lenses and in servo gears; plus a cat that
   will absolutely investigate a moving arm. Move both out of the room.
3. **Drying rack.** Changing background + humidity. Out.
4. **The desk is a sit-stand.** If cameras mount to the *walls* and the arm sits on
   the desk, changing desk height silently changes every extrinsic → policy
   collapses (ACT viewpoint sensitivity is measured: 0.80 → 0.13 under viewpoint
   shift; ICRA 2026 "Do You Know Where Your Camera Is?" shows ACT/DP/SmolVLA all
   latch onto viewpoint shortcuts). **So do not mount cameras to the walls.**

## The core layout idea: your two walls ARE the lightbox

NVIDIA's foam box exists to fix the background and the light. A corner gives you two
matte white walls for free. Add the floor (mat) and the top (one diffuse bar +
optional white bounce panel) and you have replicated the box without building it.

Critical orientation detail: **the cameras must look INTO the corner.** Arm base at
the *front* edge of the desk near the operator, workspace on the desk between the
arm and the two walls, cameras on a boom reaching forward over the operator side.
The background is then two white walls. If you flip it — cameras on the walls
looking outward — the background becomes the room, and the room changes daily.

```
                 back wall (white)
   ┌──────────────────────────────────────────┐
   │   ▒▒▒▒▒▒▒ LED bar + white bounce ▒▒▒▒▒▒   │
   │                                          │  side
   │        ┌───── workspace ─────┐           │  wall
   │        │  black mat  ~40×30  │           │ (white)
   │        └─────────────────────┘           │
   │                 🤖 arm base              │
   └──────────────────────────────────────────┘
            ▲ CAM-B near-overhead (boom)
       ▲ CAM-A front-oblique 45°, offset ~25°
                   👤 operator + leader arm
```

## Mount the whole rig to one baseplate, not to the room

**Build the lab as a board, not as a room.** 12–18 mm plywood or an aluminium plate,
~80 × 50 cm, with:

- arm bolted at a permanently marked position
- 2020/2040 extrusion uprights clamped/bolted to the *baseplate*, carrying the
  camera boom
- black EVA mat area, taped workspace rectangle
- ChArUco board stored flat next to it

Why this beats wall rails **in this specific room**: it is immune to desk height, it
survives a flat move, it needs no drilling in a rented attic, and — the real reason —
**camera-to-arm extrinsics become a rigid-body property of the rig, not of the
building.** That is exactly what viewpoint-sensitive policies need.

Still add index marks on the extrusion (A1…A5) + a printed protractor on the
articulating heads, and record `rail_position / pan / tilt` with every dataset.

## Camera geometry

Our own measured reach (FK over the URDF): **well-conditioned 63–300 mm** from the
pan axis, pan ±110°. The scene is therefore only about **40 × 30 cm**. Frame for
that, not for the desk.

| Cam | Pose | Job |
|---|---|---|
| **A — context** | ~45° down, offset **20–30° to the side opposite the operator's dominant hand**, ~40–50 cm from workspace centre, ~78° HFoV | "What is happening" — matches NVIDIA's 45°/78° spec, keeps sim-to-real option open |
| **B — near-overhead** | 60–80° down, ~55–65 cm above the mat, on the boom | "Where is everything" — XY/orientation localisation |
| **C — wrist** | on the arm | "Where is my gripper relative to this object" |

Rules of thumb that matter more than the exact angles:

- **Dead-centre is only OK if it is near-overhead.** A centred 30–45° camera puts
  the arm between the lens and the object on most approaches. Oblique → offset it.
- Frame so the image contains the full workspace, the gripper through its whole
  range, source *and* destination, plus ~10–20% margin.
- **Acceptance test (NVIDIA + lerobot both state it): teleoperate the task looking
  only at the camera feeds.** If you can't, the placement is wrong. If you can but
  used a glance at the real arm, the policy will never have that information.
- Pick left vs right by which side yields fewer arm occlusions **for our actual
  tasks** (chess reach-across is asymmetric — test with the pick rectangle occupied).

## Cheap experiment that settles it empirically

Do not pick the position by argument. Mount **three temporary external cams**
(left-oblique / near-overhead / right-oblique) + wrist, record **one** dataset with
all four streams, then ablate at train time — no re-collection needed:

| Run | Inputs |
|---|---|
| A | wrist + left |
| B | wrist + overhead |
| C | wrist + right |
| D | wrist + overhead + left |
| E | wrist + left + right |

Prereq: this is 4 simultaneous streams. On the Mac that is exactly what killed the
Innomaker. On the Linux host with MJPG + split controllers it is routine. **Another
reason the host decision comes first.**

## Calibration + provenance (do this from day one)

Per dataset, save alongside it:

```
camera serial / by-id path, resolution, fps, fourcc
intrinsics + distortion (ChArUco)
camera→robot-base extrinsic
rig index marks (rail pos, pan, tilt)
locked exposure / WB / focus values
lamp setting + measured mean frame brightness
timestamp, lerobot version
```

Two payoffs: (1) datasets become mergeable and comparable — the whole point of
`journal.md`; (2) it is the prerequisite for camera-extrinsics conditioning
(Plücker ray maps), which the ICRA 2026 paper shows restores viewpoint
generalisation for ACT / Diffusion Policy / SmolVLA. Cheap insurance, taken now.

## Lighting

- Two diffuse sources beats one harsh lamp — but our proven config is one dominant
  desk lamp (ggando rule). Compromise: **one dimmable LED bar above/front as the
  dominant source + a white bounce panel** on the open side. ~4000 K, CRI >90.
- Matte white walls already correct. Keep the black EVA mat for contrast.
- Lock camera exposure to the lamp setting (only possible on Linux — see §A).
- Later, vary brightness **deliberately** as augmentation. The goal is not constancy
  forever, it is *intentional* variation.

## Also worth doing

- **Replace the Innomaker wrist cam.** Condemned after 5 deaths across 3 port
  arrangements. A second C922 or any fixed-focus UVC module. Retest on Linux with
  MJPG before writing it off entirely — raw YUYV over a shared controller may have
  been half the problem.
- **Removable 3-sided foam mini-lightbox** that drops onto the baseplate when you
  specifically want NVIDIA-reproducible conditions (their box: 30"W × 20"H × 20"D,
  5 sheets of 20×30" 3/16" foam board). Not the permanent architecture — NVIDIA
  themselves note their checkpoint overfits to box-specific layout.
- **Leave floor space for a second arm** (bimanual / chess opponent) and for an
  active-vision cam arm later.
- Route all cables out of the workspace and behind the arm — NVIDIA flags snagging
  cables as a source of *false calibration limits*, not merely visual noise.

---

## Recommended build order

1. Empty the room (litter box, drying rack). Blackout the window.
2. Buy the Linux box (tier 2 if budget allows, tier 0 if not) + a wrist cam.
3. Ubuntu, lerobot 0.6.0 pinned, udev by-id rules, V4L2+MJPG, systemd agent
   autostart, Tailscale. Verify: 3 cams + arm streaming simultaneously, exposure
   locked, `lsusb -t` shows split controllers.
4. Build the baseplate + extrusion boom. Mark everything.
5. ChArUco calibrate, write the provenance dump script.
6. Record the 4-stream ablation dataset. Train A–E. Lock the winner.
7. Then, and only then, restart the chess / SmolVLA queue on a rig that is finally
   reproducible.

## Sources

- NVIDIA SO-101 sim-to-real: [workspace build](https://docs.nvidia.com/learning/physical-ai/sim-to-real-so-101/latest/05-building-workspace.html), [course index](https://docs.nvidia.com/learning/physical-ai/sim-to-real-so-101/latest/index.html)
- [lerobot async inference](https://huggingface.co/docs/lerobot/en/async) · [LeKiwi (Pi host + ZMQ)](https://huggingface.co/docs/lerobot/lekiwi)
- [lerobot #3198 — V4L2+MJPG fixes dual-cam 640×480@30](https://github.com/huggingface/lerobot/issues/3198) · [#1738 — Pi 4 illegal instruction](https://github.com/huggingface/lerobot/issues/1738)
- [Multiple UVC cameras on Linux — ENOSPC = isochronous bandwidth](https://www.thegoodpenguin.co.uk/blog/multiple-uvc-cameras-on-linux/)
- [Pi 5 RP1: two independent xHCI controllers](https://www.raspberrypi.com/documentation/computers/io-controllers.html)
- [Do You Know Where Your Camera Is? (ICRA 2026)](https://arxiv.org/abs/2510.02268) · [project page](https://ripl.github.io/know_your_camera/)
- [DROID](https://droid-dataset.github.io/) · [ALOHA](https://github.com/tonyzhaozh/aloha)
- Ours: `notes/recording-session-v1.md` (reach FK, macOS camera-control measurements), `journal.md` 2026-08-13

---

# Session plan — first H4 day

**Goal / stop condition:** leader→follower teleop running *on the H4*, driven over SSH
from the Mac, both cameras streaming **MJPG at locked exposure**. Everything else is
next session. **Deliverables that gate the shopping list: the `lsusb -t` tree and the
YUYV-vs-MJPG A/B result.**

### 0. While you are physically at the box (you only get this chance cheaply)
- BIOS: **restore power state after AC loss = ON** (lets the smart plug recover it).
- BIOS: boot order, disable secure boot if it fights you.
- Plug **Ethernet**. Note the MAC.
- Note which H4 variant it is (H4 / H4+ / Ultra) and what's already installed on it.

### 1. Get on it
```bash
ping odroid.local || arp -a | grep -i <mac>
ssh <user>@<ip>
lsb_release -a && uname -m && free -h && lsblk     # expect x86_64
sudo apt update && sudo apt install -y v4l-utils usbutils ffmpeg vainfo git curl
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --ssh
```
If the OS on it is old/unknown: reinstall **Ubuntu 24.04 LTS**. Don't nurse it.

### 2. USB survey — THE deliverable
Plug follower, leader, both cameras. Then:
```bash
lsusb -t                       # arms should show 12M; cameras 480M. Count root buses.
ls -l /dev/serial/by-id/ /dev/v4l/by-id/
sudo lsusb -v 2>/dev/null | grep -iE "per-port power|bDeviceProtocol"
```
Read off: are all 4 ports on one xHCI? Are the arm boards full-speed (`12M`)?
→ answers whether we need a **multi-TT** hub and how many cameras fit.

### 3. Camera capability — the thing macOS cannot do
```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext      # confirm MJPG modes exist
v4l2-ctl -d /dev/video0 --list-ctrls            # confirm exposure/WB/focus are WRITABLE
v4l2-ctl -d /dev/video0 --set-ctrl=auto_exposure=1 \
  --set-ctrl=exposure_time_absolute=250 \
  --set-ctrl=white_balance_automatic=0 \
  --set-ctrl=focus_automatic_continuous=0
```
If those `set-ctrl`s stick, **lever #2 just closed** — we can lock the camera, not only the lamp.

### 4. The money experiment: reproduce the wedge, then fix it
Run both cameras **simultaneously**, 60 s, raw first:
```bash
for d in 0 1; do ffmpeg -hide_banner -f v4l2 -input_format yuyv422 \
  -video_size 640x480 -framerate 30 -i /dev/video$d -t 60 -f null - & done; wait
```
Expect `ENOSPC` / "No space left on device" or dropped frames. Then MJPG:
```bash
for d in 0 1; do ffmpeg -hide_banner -f v4l2 -input_format mjpeg \
  -video_size 640x480 -framerate 30 -i /dev/video$d -t 60 -f null - & done; wait
```
Expect clean. **That A/B is the proof the Innomaker deaths were format, not hardware** —
and it tells us whether 3–4 streams for the camera ablation are viable.

### 5. Codec benchmark (decides the recording config)
```bash
vainfo | grep -i enc          # confirm H264/HEVC entrypoints exist
for c in "libsvtav1" "libx264 -preset ultrafast" "h264_qsv"; do
  echo "== $c"; ffmpeg -hide_banner -f lavfi -i testsrc=size=640x480:rate=30 \
    -t 20 -c:v $c -f null - 2>&1 | tail -1; done
```
Compare the `speed=` figures. Anything under ~2× realtime for two streams means
configure lerobot away from AV1.

### 6. lerobot
```bash
uv venv && uv pip install "lerobot==0.6.0"    # SAME version as the Mac — lever #1
lerobot-find-port          # both arms
lerobot-find-cameras opencv
```
**Copy the calibration from the Mac** rather than recalibrating:
```bash
find ~/.cache/huggingface/lerobot -path "*calib*" -name "*.json"   # on the Mac
scp -r <those files> odroid:~/.cache/huggingface/lerobot/...
```
Then local teleop on the H4 (leader → follower), watched over SSH.

### 7. Lock it down
- udev rules → `/dev/so101_follower`, `/dev/so101_leader`, `/dev/cam_context`, `/dev/cam_wrist`
  (from the `by-id` paths in step 2). Kills lever #4 permanently.
- systemd unit for the hub agent, `Restart=always`, `LAB_AUTOCONNECT=real`.

### 8. Close out
Append a dated `journal.md` entry: H4 variant, OS, lsusb tree, MJPG A/B result, codec
numbers, what worked. That log is the point.

### Deliberately NOT tomorrow
Hub purchase (step 2 decides it), room/wrist cameras, baseplate build, camera geometry.

---

# Pi bring-up gotchas (2026-08-22/23) — learned the hard way

Room host ended up being the **Raspberry Pi 4 4GB**, not the HC4 (which is an ARM NAS
board with one USB 2.0 port — see the correction above).

1. **A malformed password hash silently kills the whole `custom.toml`.** Ours was
   truncated to 13 bytes (`$6UJwvVo/8t7s`) because `${H:0:12}` in a shell string ate the
   `$6$`. Result: Pi booted, sshd ran (the separate `ssh` flag file works independently),
   but **no user and no hostname change** — locked out entirely. Always verify:
   a valid SHA-512 crypt hash is **106 chars and starts with `$6$`**.
   - macOS `crypt.crypt()` cannot verify `$6$` hashes — it has no SHA-512 support, so a
     round-trip check always reports False. Use
     `openssl passwd -6 -salt <salt> <pw>` and compare to the original instead.
   - Generate with `openssl passwd -6`, not python's `crypt` on macOS.
2. **Belt-and-braces the preseed.** Ship BOTH `custom.toml` and `userconf.txt`
   (`user:$6$...`) — the latter is handled by a separate service and doesn't depend on
   the firstboot TOML path.
3. **`diskutil eraseVolume` sets MBR type `0x0B` (`DOS_FAT_32`)**, but the Pi firmware
   wants **`0x0C` (`Windows_FAT_32`)**. A boot partition made that way is invisible to
   the bootloader even with perfect contents. This killed an attempt to build a
   boot-on-SD + root-on-USB card without sudo.
4. **PARTUUID collides across Raspberry Pi OS images** — they ship a fixed MBR disk
   signature, so two Pi OS disks both answer to `PARTUUID=041bba91-02`. Boot with only
   one attached, or root by explicit device.
5. **Pi 4 USB boot needs EEPROM ≥ 2020-06-15.** Chicken-and-egg: you need an SD card to
   fix the inability to boot without one. `sudo rpi-eeprom-update -a` once running.
6. **Dying SD cards present as everything else.** A card writing at 3 MB/s (vs 38 MB/s
   for the SSD) with NUL bytes in FAT directory entries produced: intermittent boots,
   DHCP falling to link-local, blank screens, SSH that worked an hour earlier. We chased
   four "separate" faults that were one failing card.

---

# ✅ KILL CRITERION PASSED (2026-08-23)

**lerobot 0.6.0 imports cleanly on the Pi 4 (aarch64, Debian 13 Trixie, Python 3.12).**
`lerobot 0.6.0 / torch 2.11.0+cpu / aarch64` — no `Illegal instruction` (cf. lerobot #1738).
The Pi 4 4GB is confirmed viable as the room host.

## THE INSTALL TRAP — do not repeat

`uv pip install lerobot==0.6.0` on ARM64 Linux pulls the **CUDA stack**: PyPI's aarch64
torch wheels depend on `nvidia-cublas`, `nvidia-cudnn-cu13`, `nvidia-cusolver` … built
for Jetson/GH200, useless on a Pi, **~3.6 GB**. On a 14 GB card that nearly filled the
root filesystem (hit 66% with *nothing* installed).

**Correct recipe — install CPU torch FIRST, inside lerobot's pinned range:**
```bash
uv venv --python 3.12          # distro Trixie ships 3.13; fewer aarch64 wheels
uv pip install --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.7,<2.12" "torchvision>=0.22,<0.27"
uv pip install "lerobot==0.6.0"
```
- lerobot 0.6.0 requires **`torch<2.12.0,>=2.7`**, **`torchvision<0.27.0,>=0.22.0`**.
  Installing torch *newer* than that (e.g. 2.13.0+cpu) makes uv resolve a fresh torch
  from PyPI — which is exactly how the CUDA stack sneaks back in. The `+cpu` pin only
  works if the version is also inside lerobot's window.
- Verify with `uv pip list | grep -ci nvidia` → must be **0**.
- Result: ~900 MB installed, 7.3 GB free.

## Pi 4 facts (measured)
- EEPROM **Nov 2025** → USB boot supported all along; the earlier USB-boot failure was
  never a firmware issue.
- USB topology: **Bus 001 = 480M** (all USB 2.0 devices share it), **Bus 002 = 5000M**.
  Single VL805 controller. MJPG for cameras remains mandatory.
- `userconf.txt` is the reliable preseed path; `custom.toml` silently fails if any
  field is malformed (see the password-hash entry above).

---

# Room host BUILT — `lab-pi` (2026-08-23)

Raspberry Pi 4B 4GB, Debian 13 Trixie, `kris@lab-pi`, key auth + NOPASSWD sudo.
Reachable on Tailscale at **100.77.154.45**.

## Storage layout (deliberate)
- **microSD = OS root only.** It's the card that wrote at 3 MB/s and had a corrupt FAT;
  treat as consumable. `journald Storage=volatile` so logs stop hammering it.
- **SSD (Samsung 860 QVO 1TB) = `/data`**, ext4, mounted by UUID with `nofail` so the Pi
  still boots if the enclosure drops.
- Datasets/caches forced off the card:
  `HF_LEROBOT_HOME=/data/lerobot`, `HF_LEROBOT_CALIBRATION=/data/lerobot/calibration`,
  `HF_HOME=/data/hf-cache`, `TORCH_HOME=/data/models`.
- ⚠️ These must go in **`/etc/environment`**, not `~/.profile` — non-interactive ssh
  (which is how everything is driven) does not source profile files.

## Deferred: root-on-SSD
EEPROM is Nov 2025 so USB boot IS supported. NOT doing it yet: the JMicron JMS576
enclosure will only negotiate **USB 2.0** (~30 MB/s) across 4 cables and 2 hosts. A link
that flaky as *root* means a USB reset kills the OS on a headless box. As `/data` a reset
costs one write. Revisit once a working USB 3 enclosure/cable exists.

## udev — hard-won lever #4 is retired
`/etc/udev/rules.d/99-so101-lab.rules` gives permanent, serial-based names:
`/dev/so101_follower` `/dev/so101_leader` `/dev/cam_context` `/dev/cam_wrist`.
No more verifying camera indexes before every session.

## lerobot 0.6.0 API names (they are NOT `so101_*`)
```python
from lerobot.robots.so_follower      import SO101Follower, SO101FollowerConfig
from lerobot.teleoperators.so_leader import SO101Leader,  SO101LeaderConfig
```
CLI still uses `--robot.type=so101_follower`, and calibration lives at
`calibration/robots/so101_follower/arm.json`.

## 🎯 THE MJPG A/B — the answer, and it reconciles the whole macOS saga

Both cameras, 640×480@30, 60 s, simultaneous, on the Pi's single 480 Mbps bus:

| format | C922 | Innomaker |
|---|---|---|
| **YUYV (raw)** | **1800/1800** flawless | **0/1800 — TOTAL HANG** |
| **MJPG** | **1800/1800** flawless | **1763/1800 (98%)**, no hang |

**Format, not bandwidth, and not (only) a bad camera.**
- Bandwidth was never the constraint at two cameras — the C922 delivered a perfect raw
  YUYV stream (147 Mbps) on the same bus the Innomaker was choking on.
- The Innomaker hangs *only* in YUYV: 0 frames, ffmpeg at 99% CPU for 18 min, kernel
  `usb 1-1.1.1-port2: cannot reset (err = -71)` (EPROTO) ×4 +
  `uvcvideo: Failed to query (GET_INFO) UVC control 16`. It also forced a USB reset on the
  **C922** — a sick device on the bus damages healthy ones.
- In MJPG it simply works, ~2% frame loss, zero kernel errors.

**This explains all five "Innomaker deaths" on macOS.** macOS/AVFoundation cannot select
MJPG (`CAP_PROP_FOURCC` → `False`, lerobot's `fourcc:` is a no-op there), so on the Mac
that camera was *always* running raw YUYV — the mode that hangs it. It was never a
mysterious hardware death; it was the one format it cannot survive.

**Practical consequences**
1. **MJPG is mandatory**, and on Linux it is actually settable. Never record raw.
2. The Innomaker is **usable but marginal** — 2% frame loss is real. Fine for a
   secondary/context view; I would not trust it as the wrist cam in a dataset that
   matters. A second C922 remains the safe buy.
3. After any hang the video nodes stay held (`Device or resource busy`); needs
   `pkill -9 ffmpeg` + ~5 s before anything can reopen them.

## Calibration paths — the class name is NOT the directory name
lerobot 0.6.0 classes are `SO101Leader` / `SO101Follower`, but their `.name` is
**`so_leader`** / **`so_follower`**, and that is what the calibration path uses:
```
$HF_LEROBOT_CALIBRATION/teleoperators/so_leader/<id>.json
$HF_LEROBOT_CALIBRATION/robots/so_follower/<id>.json
```
NOT `so101_leader/` — a stale Mac cache had both, and copying the `so101_*` ones
produced "has no calibration registered". Check with `robot.calibration_fpath`.

Extras needed beyond the base install (install the packages directly, NOT via
`lerobot[extra]`, which re-resolves torch and drags CUDA back in):
```bash
uv pip install feetech-servo-sdk deepdiff
```

## Verified working (2026-08-23)
- Leader arm reads all 6 joints through `/dev/so101_leader` with calibration applied.
- Cameras: MJPG dual-stream 3563/3600 (C922 100%, Innomaker 97%) direct-attached.
- `/data` survives unclean unmount (journal replay); mounted by UUID so it doesn't care
  that the SSD moves between `sda`/`sdb`.
- ⚠ `sudo umount /data` BEFORE unplugging the SSD — hot-unplug aborts the journal.

## ⚠️ TORQUE-ON SNAP — check before every `robot.connect()` on a cold arm
On a power-cycled SO-101 the servos' stored `Goal_Position` can be **0** while the arm
physically sits anywhere. Enabling torque then slams every joint toward 0 at full speed.
Measured on 2026-08-23 (follower, cold):

```
joint            present   goal   delta
shoulder_pan       2036      0   -2036
elbow_flex         3151      0   -3151   <-- ~277 degrees of travel
wrist_flex         2378      0   -2378
```

`robot.connect()` enables torque, so calling it blind on a cold arm whips the whole arm
across the workspace. **Safe sequence** (verified: 0 ticks of movement on torque-on):
```python
bus = SO101Follower(cfg).bus
bus.connect()                                             # opens port, NO torque
pres = bus.sync_read("Present_Position", normalize=False)
bus.sync_write("Goal_Position", pres, normalize=False)    # goal := where it already is
for m in bus.motors:
    bus.write("Torque_Enable", m, 1, normalize=False)     # now safe
```
Reading `Present_Position` with the bus open but torque never written is completely
safe — no motion is physically possible.

## ✅ FIRST COMMANDED MOTION ON `lab-pi` (2026-08-23)
shoulder_pan ±5°, 4-point sequence: tracking error 3–10 ticks (0.3–0.9°, normal STS3215
deadband), return drift **-3 ticks (0.26°)**. Full chain verified:
udev → CDC serial → feetech-servo-sdk → lerobot 0.6.0 → calibration → accurate motion.

---

# Waveshare 3.5" LCD — SOLVED (2026-08-23)

Panel: **Waveshare 3.5" (A) / `waveshare35a`, ILI9486, 320×480, SPI**, touch IRQ on GPIO17.

**It works on Pi OS Trixie / kernel 6.18 with ONE line in config.txt.** Every guide that
says otherwise is wrong: fbtft was NOT removed — `fb_ili9486.ko` and a generic
parameterised `fbtft.dtbo` both ship with Pi OS. No vendor script, no compiled overlay,
no fbcp, no kernel module hacking.

```
dtparam=spi=on
dtoverlay=fbtft,spi0-0,ili9486,reset_pin=25,dc_pin=24,speed=16000000,rotate=0,fps=30,txbuflen=32768,bgr=1
```
→ `/dev/fb0`, `fb_ili9486`, 320×480, 16bpp, 300 KiB, spi0.0 @16 MHz.

## What cost hours (don't repeat)
1. **The panel is WRITE-ONLY — MISO is not wired.** Every read returns zeros: display ID
   register, XPT2046 touch on CE1, everything. I nearly condemned the hardware. You
   cannot identify these panels by probing; you can only write and look.
2. **No touch found** — nothing on SPI CE1, and I²C bus 1 is empty. Either this revision
   has no touch or it needs the `ads7846` overlay; unresolved, display works regardless.
3. `rotate=90` gives a 480×320 fb which **wraps** on this 320×480 panel (repeated vertical
   lines, ~60% filled). Use **`rotate=0`**. The upstream `.dts` says `rotate = <0>`.
4. **Colours are BGR** — red and blue transpose without `bgr=1`.
5. Pin numbers came from the upstream source `swkim01/waveshare-dtoverlays`:
   `brcm,pins = <17 25 24>` → touch IRQ 17, **reset 25, dc 24**, `spi-max-frequency 16 MHz`.

## Status display — `~/labstatus.py`, `labstatus.service`
Shows: hostname, Tailscale IP, LAN IP, eth link, CPU temp + throttle flags, load, mem,
`/data` free, presence of both cameras and both arms, recording banner (reads
`/data/session.json` if a session writes one), uptime, clock.

**Cost: 16.5 ms/frame at 2 s refresh ≈ 0.8% of one core.** Getting there mattered:
- naive per-pixel RGB565 loop = 232 ms → **numpy vectorised = 6.7 ms**
- subprocess calls every frame (tailscale/vcgencmd/uptime) = 587 ms → **cached 30 s = 0.9 ms**
- Total 855 ms → 16.5 ms, a 50× win. SPI0 is otherwise unused, so zero contention with
  cameras (USB) or arms (USB).

---

# Vision experiment — YOLO-Depth + classical CV + IK (2026-08-23)

Goal: frontier model directly commanding servos, using metric depth from ONE camera.
Verdict: **viable, and every piece works except camera↔arm registration.**

## The five links assessed
| source | verdict |
|---|---|
| **[Ultralytics YOLO-Depth #25695](https://github.com/ultralytics/ultralytics/issues/25695)** | ✅ **USE IT.** Native depth task in YOLO26, metric per-pixel from single RGB, <10M params at nano, 20× faster than Depth Anything V2. Ships `model.calibrate()` for scale. |
| [Flex-π](https://github.com/geyan21/flex-pi) | ✗ 6B, needs 16–26 GB on RTX 4090/5090. YAM bimanual, no SO-101. MIT. Revisit if we rent a GPU. |
| [NVIDIA video_to_data](https://nvidia-isaac.github.io/video_to_data/) | ✗ Isaac Lab pipeline → needs RT-core GPU. Same blocker as the whole sim track. |
| [Ludi 0.1](https://www.ludorobotics.ai/research/ludi-0-1) | ✗ Qwen3.5 brain + GR00T N1.7, onsite GPU workstation, **no weights released**. |
| X/Kangwook_Lee post | ✗ paywalled (HTTP 402), unread. |

## Measured on this rig (Mac M-series, MPS)
- `yolo26n-depth.pt` loads, `task=depth`, output `(1080,1920) float32` metres.
- **Cold inference 11.6 s (MPS compile) → WARM 29 ms.** Only the warm number matters.
- Depth *ordering* verified correct against the real scene:
  ChArUco 1.19 m < white block 1.57 m < arms 2.18–2.20 m. ✅
- **Absolute scale is WRONG by ~2.2–2.5×.** ChArUco geometry (11 markers, `DICT_4X4_50`,
  median side 49.4 px, nominal C922 fx≈1186–1360) puts the board at **0.48–0.55 m** if the
  markers are 20 mm, vs YOLO's 1.19 m. Monocular depth is scale-ambiguous by nature —
  this is what `model.calibrate()` exists for.
  **BLOCKING INPUT: measure one marker square in mm.**
- COCO detection is useless here — called the tub a "sink", the ChArUco a "keyboard".
  **A white block on a black mat is trivial classical CV** (threshold + connected
  components found it cleanly at px (960,606)). Don't reach for ML where a threshold works.
- **Full loop Pi→Mac: 1.75 s** = capture 1154 ms + transfer 450 ms + depth 88 ms.
  Bottleneck is **ffmpeg process startup per call**, not the camera or model. A persistent
  MJPEG stream would cut this to ~300 ms. Fine for look-think-act; useless for 30 Hz.
- **IK works**: `ikpy` on `phone_teleop/SO101/so101_new_calib.urdf`, 6 revolute joints.
  4/5 mat-plane targets solved to **0.0 mm**; the 5th correctly failed as unreachable.

## The pipeline, and the one missing link
```
1 camera frame            ✅ Pi captures, cam_context
2 target in pixels        ✅ threshold + connected components (white on black)
3 pixels -> 3D camera     ⚠  needs intrinsics + YOLO scale calibration (1 measurement)
4 camera -> arm base      ❌ HAND-EYE CALIBRATION - needs the arm to MOVE
5 3D -> joint angles      ✅ ikpy, 0.0 mm on reachable targets
6 joints -> servos        ✅ verified, with the goal=present torque-on sequence
```

## Also observed
The C922 is **1.5–2.2 m from the workspace**. The arm's well-conditioned reach is
63–300 mm, so the useful scene is a ~40×30 cm patch occupying a small part of the frame.
NVIDIA's spec puts the context camera at ~40 cm. **Moving the camera much closer would
improve pixel resolution on the workspace by several times** — the cheapest accuracy win
available, and it costs nothing.

---

# STEP 0 — recording feasibility on `lab-pi` (2026-08-23)

Gate before building any camera daemon. **Result: the Pi CAN record, but ONLY if the video
encoder is changed. The lerobot default is unusable here.**

## Missing dependencies found (recording would have failed mid-session)
Base `lerobot==0.6.0` does NOT install the recording path. `av`, `torchcodec`, `datasets`,
`pandas`, `pyarrow`, `jsonlines` were all absent — `import lerobot` succeeding proves
nothing about `lerobot-record`. Fixed with a torch pin so CUDA cannot creep back:
```bash
printf 'torch==2.11.0+cpu\ntorchvision==0.26.0+cpu\n' > /tmp/pin.txt
uv pip install -c /tmp/pin.txt "lerobot[dataset]==0.6.0"
# -> av 15.1.0, torchcodec 0.11.1, torch still 2.11.0+cpu, nvidia pkgs: 0
```
Also needed earlier, install the packages directly (NOT via `lerobot[extra]`):
`uv pip install feetech-servo-sdk deepdiff`.

## The encoder is the bottleneck — measured with lerobot's REAL settings
lerobot defaults to `vcodec=libsvtav1, g=2, crf=30`. **`g=2` means a keyframe every two
frames** (nearly all-intra, for fast random access in training) — this dominates cost and
invalidates any benchmark that omits it. Measured via PyAV (lerobot uses PyAV, not
subprocess ffmpeg), 600 frames 640x480 = one 20 s episode, one camera, noisy frames:

| config | time | vs realtime | size |
|---|---|---|---|
| **libsvtav1 g=2 crf=30 — THE DEFAULT** | **47.48 s** | **0.4x** | 76.2 MB |
| libx264 threads=1 | 49.24 s | 0.41x | 37.0 MB |
| libx264 threads=2 | 27.68 s | 0.72x | 37.1 MB |
| libx264 threads=4 | 18.50 s | 1.08x | 37.4 MB |
| **libx264 threads=4 preset=ultrafast** | **6.95 s** | **2.88x** | 43.3 MB |
| libx264 threads=4 preset=superfast | 9.84 s | 2.03x | 35.2 MB |
| `h264_v4l2m2m` (Pi HW encoder) | 5.05 s | 4.0x | 9.5 MB |

**On the default, 2 cameras cost ~95 s of encoding per 20 s episode.** A 50-episode session
= 17 min recording + ~79 min encoding. Not viable.

**Use this instead** (6.8x faster AND smaller files — `g=2` throws away AV1's advantage
while keeping its cost):
```
--dataset.rgb_encoder.vcodec=h264
--dataset.rgb_encoder.preset=ultrafast
--dataset.encoder_threads=4
--dataset.streaming_encoding=true
--dataset.num_image_writer_threads_per_camera=2
# and NEVER --display_data=true on the Pi
```
At 2.88x realtime for one camera, two cameras run at 1.44x — **streaming encoding keeps up
live, so there is no inter-episode encoding gap at all.**
Verified through lerobot's own path: `VideoEncoderConfig(vcodec="h264", preset="ultrafast",
g=2, crf=30).get_codec_options(4)` -> `{'g':'2','crf':'30','preset':'ultrafast','threads':'4'}`.

## The Pi's hardware encoder is unreachable from lerobot
`h264_v4l2m2m` IS present in both system ffmpeg and PyAV, and is the fastest option by far
(4.0x realtime, 9.5 MB). But lerobot validates against an allowlist in `configs/video.py:33`:
`HW_VIDEO_CODECS = [h264_nvenc, h264_qsv, h264_vaapi, h264_videotoolbox, hevc_nvenc,
hevc_videotoolbox]` — NVIDIA / Intel / Apple only, **no V4L2 M2M (the ARM one)**. Adding
`"h264_v4l2m2m"` to that list is a one-line change and worth an upstream PR; until then
`h264 + ultrafast` is the supported answer.

## Caveat
Benchmarks used random-noise frames (worst case, incompressible). Real footage of a mostly
static scene will be faster and smaller for every codec. The ordering and ratios hold.

---

# PHASE 2 — `lab_cameras/` built and verified on `lab-pi` (2026-08-23)

One owner for both cameras, so lerobot recording / the vision loop / previews stop
fighting over `/dev/video*`. Package is `lab_cameras/` in this repo; full rationale and
API in `lab_cameras/README.md`.

## ⚠️ THE BUG THAT COST THE EVENING: `CAP_PROP_BUFFERSIZE = 1`

Setting `cv2.CAP_PROP_BUFFERSIZE = 1` on V4L2 **halves the Innomaker** and, with the C922
already streaming, stops it delivering **entirely** (1916 consecutive failed reads, camera
opened as MJPG 640×480, no error anywhere). The C922 is unaffected, so it looks exactly
like "the Innomaker is dying again" — which is how it nearly got condemned a third time.

Isolated by varying one setter at a time, 3 s per trial:

| open sequence | Innomaker | C922 |
|---|---|---|
| bare open (no sets) | YUYV, 74 frames | YUYV, 83 frames |
| + fourcc MJPG | 74 | 82 |
| + size | 74 | 82 |
| + fps | 74 | 82 |
| **+ BUFFERSIZE=1** | **37** | 82 |

The reader thread already drains the queue continuously, so latest-wins comes from the
loop — starving the driver buys nothing. **Never set BUFFERSIZE on this rig.**

Second nuance worth recording: **bare-open YUYV at 640×480 works fine for ONE camera**
(74 frames/3 s). The YUYV hang is a *dual-camera bandwidth* failure, not a format failure.
MJPG is still asserted on open, because the failure it prevents is catastrophic and silent.

Third: a Python `threading.Thread` subclass must not name an attribute `_stop` —
`Thread._stop` is a real method and `join()` calls it. The symptom is
`TypeError: 'Event' object is not callable` inside `threading.py`, nowhere near the cause.

## Measured (both cameras, MJPG 640×480, direct-attached, 20 s)

| camera | fps | read failures | repeated frames |
|---|---|---|---|
| workspace (C922) | **30.87** | 0 | 0 |
| wrist (Innomaker) | **29.53** | 0 | 0 |

Dual-stream on the Pi is *clean* — 0 failures, 0 duplicate frames. Compare the Mac, where
this combination was unreliable for a year.

## Ownership verified the way it matters

`flock` on `/run/lock/lab-cams.lock` (world-writable tmpfs — no root needed, unlike
`/run/lab`). Tested:
- second opener while held → refused, **with the current owner's session and live health
  counters in the error message**
- `kill -9` the owner → next process opens cleanly. This is the whole reason it is `flock`
  and not a PID file.

## Snap latency: 1839 ms → 5.3 ms

| path | time |
|---|---|
| `subprocess capture.py` (what `desk.py::snap()` did) | **1839 ms** |
| in-process `latest()` + `cv2.imwrite` | **5.3 ms** |
| `latest()` alone | **0.003 ms** |

347×. The 1.8 s was interpreter startup + 30 warmup reads, paid on every snap inside the
primary agent-facing tool. `desk.py serve` now holds a `CameraOwner` for its lifetime
(`DESK_HOLD_CAMS=0` opts out; it falls back to the subprocess path if another process owns
the cameras, e.g. during a recording).

## Health-gate baselines on the datasets we already trained on

`python -m lab_cameras.health <dataset-root> --stride 3`

| dataset | frozen runs | cross-camera MAD |
|---|---|---|
| `kris0/so101_pickplace_wall_v1_20260722_174720` | 0 | 85.5–88.1 |
| `kris0/so101_blue_pegs_v1_20260723_171824` | 0 | 86.0 |

**The Innomaker's known 2–3% frame loss did not corrupt either dataset.** Cross-camera MAD
near 0 would mean both feature keys carry the same picture; ~86 means genuinely different
views. Note LeRobotDataset **v3 packs many episodes into one `file-NNN.mp4`**, so the gate
reports per video file, not per episode.

## `gemini_er/` is now host-portable

New `gemini_er/devices.py` resolves every device by role, same file on both hosts:

| | Mac | `lab-pi` |
|---|---|---|
| follower | `/dev/tty.usbmodem5AE60832001` | `/dev/so101_follower` |
| cameras | ints 0 / 1 (from `calib.json`) | `/dev/cam_context` / `/dev/cam_wrist` |

Order is env override → udev name if present → the old Mac default, so **nothing about the
Mac workflow changes**. `capture.py::grab()` routes legacy integer indexes through the
resolver too, which fixes every consumer still reading `calib["camera_index"]`
(`pick.py`, `cycle.py`, `touch_map.py`, `move_board.py`, `pick_board.py`, `live_agent.py`)
without touching them. The three scripts that opened `cv2.VideoCapture` directly
(`calibrate.py`, `wrist_calibrate.py`, `grip_test.py`) now go through a shared `_open()`
that asserts MJPG; they keep their cv2 GUI windows and stay Mac-only for now.

## `placo` installs on aarch64 — IK runs on the Pi ✅

This was the one thing that could have forced the vision loop back onto the Mac. It didn't:
`uv pip install placo` on the Pi works, `RobotKinematics` loads
`phone_teleop/SO101/so101_new_calib.urdf`, and `arm.ik_to_xyz` solves in **1–6 ms**
(0.05 mm on an in-plane target; 17–20 mm on targets that fight the held orientation, which
is what `settle_to` iterates away). Combined with cv2 4.13 (`aruco` + `findHomography`)
already present, **the whole perceive→IK→command loop can run on the Pi** — no Mac
transfer, no relay, old Step 4 deleted.

Gotchas: `uv` is not on the PATH of a non-interactive ssh (use `~/.local/bin/uv`), and the
venv has no `pip` (it is uv-created — use `uv pip install --python ~/lab/.venv/bin/python`).

---

# ⚠️ THERMAL — the Pi throttles under exactly the load recording puts on it (2026-08-23)

Found while adding a throttle indicator to the LCD: the Pi was already showing
`throttled=0x80000` (soft temperature limit **has occurred**) at **63°C idle**. Stress-tested
with 4 busy threads — the same shape as a 2-camera h264 encode:

| elapsed | temp | ARM clock | flags |
|---|---|---|---|
| 0 s (idle) | 63.3 °C | 1500 MHz | `0x80000` |
| 30 s | 81.3 °C | 1500 MHz | `0x80000` |
| **40 s** | 82.3 °C | 1475 MHz | `0x80008` ← **throttling starts** |
| 60 s | 83.7 °C | 1231 MHz | `0x80008` |
| 100–180 s | **84.7 °C** | **1231 MHz** | `0xe0008` |
| +5 s idle | 78.8 °C | — | `0xe0000` |

Steady state is **1231 MHz — an 18% clock loss** — and it arrives after ~1 minute.

**This invalidates the headroom in the encoder benchmark above.** Those numbers
(h264 ultrafast = 2.88× realtime, 2 cameras = 1.44×) were measured on a *cold* Pi at
1500 MHz. At the throttled clock the same config is ~2.4× / **~1.2× for two cameras** —
still faster than realtime, so streaming encoding still keeps up, but the margin is thin
and anything else competing for CPU can push it under 1.0×.

Mitigations, cheapest first:
1. **Cooling.** The Pi is in a closed case with an LCD board over the SoC. A heatsink and a
   fan is the whole fix; nothing else here buys 18% back.
2. `--dataset.encoder_threads=3` instead of 4 — leaves a core for the camera reader threads
   and the control loop, and generates less heat.
3. Watch the LCD: it now shows **THROTTLED NOW** only when bits 0–3 are set (happening
   *now*), and a quieter `thr since boot` for the historical bits. `0x80000` at idle was
   previously displayed as a scary red THROTTLED, which is why it was ignored.

---

# LCD — the renderer is fine; the panel is the limit (2026-08-23)

Diagnosed by rendering the exact frame the panel receives (including the RGB565 round-trip)
and looking at it 3× magnified rather than guessing from a photo of the screen. **The render
is clean**: large type, hard edges, high contrast, nothing truncated. So "the text is very
bad" is not a rendering problem, and changing fonts/dithering would have been churn.

What is left, in order:
1. **The protective film may still be on the panel** — the photo shows a hazy layer with
   dust and blotch texture over the whole surface. Free to check, and it is the single most
   likely cause.
2. **Viewing angle.** These ILI9486 panels wash out badly off-axis — in the earlier test
   photo, "black" renders as bright blue-grey. If the panel is being read from below/above
   its good axis, `rotate=180` in `config.txt` flips the image so the good axis faces the
   operator. One line, worth trying.
3. The generic `fbtft` `ili9486` driver does not send Waveshare's gamma init sequence. This
   is the only genuinely hard one, and it is not worth touching before 1 and 2.

Changed anyway, because they are correctness rather than cosmetics:
- **A stale `session.json` no longer reads as RECORDING.** `lab_cameras` writes it and a
  `kill -9`d owner leaves it behind (flock is the truth, not the file), so the banner now
  requires a heartbeat younger than 10 s.
- The banner shows **what actually owns the cameras** (`DESK`, `PREVIEW`, `RECORDING`) plus
  live fps from the session's health block, instead of only ever saying RECORDING.

---

# PREVIEW + the headless click UI — `lab_cameras/preview.py` (2026-08-23)

One server, two jobs:
- **Aim the cameras.** `python -m lab_cameras.preview` → `http://lab-pi:8088/` streams both
  cameras live. This is the tool for Phase 1: reposition the C922 while watching the frame
  it will actually record.
- **Click a pixel.** `cv2` on the Pi is the headless build, so `calibrate.py`'s
  click-a-window UI cannot run there at all. The page returns the clicked pixel in
  **full-resolution coordinates**, which is everything calibration needs.

Verified on `lab-pi`: `/snap/<name>` valid JPEG, `/cam/<name>` MJPEG (~385 KB/s, one viewer),
`/health` live counters, `POST /click` → `{"px": 320, "py": 120, "width": 640, "height": 480}`
for a click at (0.5, 0.25). ~64% of one core while streaming to one viewer — measured while
the Pi was thermally throttled to 1231 MHz, so it is a pessimistic number, but do not leave
a browser tab streaming during a recording.

`RecordTee` is the `observation_tap` for `record_loop`, ported from the driver repo's
battle-tested version: latest-wins single-slot mailbox, encode off-loop, 25 fps ceiling, and
it swallows every exception — **a dead preview beats a dead recording**. During a recording
the server never touches the hardware; the recorder owns the cameras and frames arrive
through `publish()`.

---

# OPTICS LOCK — `python -m lab_cameras.lock` (2026-08-23)

Autofocus and auto-exposure make a rig unreproducible: a homography (and any intrinsics) is
only valid at ONE focus, and hard-won lever #2 is that a policy trained at one brightness
fails at another. macOS never exposed these controls; Linux does — that is half the reason
the room host exists. Both cameras take full manual control.

```
python -m lab_cameras.lock show      # what the cameras are doing right now
python -m lab_cameras.lock apply     # let auto settle, then reproduce that picture, pinned
python -m lab_cameras.lock apply --install-service   # ...and survive replug + reboot
python -m lab_cameras.lock rig-json  # provenance only
```

## Why it matches the picture instead of reading the registers

**You cannot read back what auto-exposure chose.** In auto mode UVC reports the control's
*default* and marks it `inactive` — the C922 says `exposure_time_absolute=250` no matter what
the room looks like. So `apply` streams for a few seconds, measures the picture auto produces
(mean brightness, channel cast, Laplacian-variance sharpness), then sweeps each control to
reproduce *that picture* with everything pinned.

## ⚠️ ORDER MATTERS, and getting it wrong is silent

First attempt reproduced 104.7 mean brightness as **21.2** — a nearly black frame, with every
control apparently "locked" and no error anywhere.

Cause: **the C922's auto-exposure drives `gain` internally while reporting `gain=0` the whole
time.** Pinning gain to its reported value *after* matching exposure throws away most of the
light. The working order is:

1. **focus, while auto-exposure is still ON** — otherwise the sharpness metric is scoring a
   dark frame rather than a blurry one
2. **gain, before exposure** (the bug above)
3. **exposure**, matched to auto's mean brightness (geometric ladder — exposure is
   multiplicative in its effect)
4. **white balance**, matched to auto's `b − r` cast
5. **re-measure, and re-tune exposure once** if step 4 moved it more than 10%

## Result (at the camera's CURRENT position — re-run after moving it)

| camera | mean (auto → locked) | sharpness (auto → locked) |
|---|---|---|
| workspace C922 | 103.7 → **104.8** (+1%) | 544 → **547** |
| wrist Innomaker | 72.5 → **67.0** (−7.6%) | 335 → 300 (no focus control) |

Locked: C922 `plf=1(50Hz) focus=5 gain=0 exposure=200 wb=2750`, Innomaker
`plf=1 gain=0 exposure=221 wb=3108`. Note the C922 was on **`power_line_frequency=2` (60 Hz)**
out of the box — wrong for Europe, and a source of rolling banding under LED light.

Written to **`/data/rig.json`** with resolution, fourcc, serial device paths, mean brightness
and lerobot version — the provenance block that makes two datasets comparable.

**Not installed as a service yet**, deliberately: these values belong to the camera's current
(wrong) position. Re-run `apply --install-service` once the C922 is at its final 40–50 cm
pose, under the working lamp.
