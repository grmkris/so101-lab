# ODROID-HC4 → lab room host: setup

> Supersedes `odroid-h4-setup.md` (deleted — that was written for an x86 board we don't have).

**Board:** Amlogic S905X3, 4× Cortex-A55 @1.8 GHz **ARM64**, 4 GB DDR4 fixed,
**1× USB 2.0 host port**, 2× SATA, 1× GbE, microSD + SPI/petitboot, DC 15 V/4 A.

## 0. Two things to establish first

**a) Is `192.168.86.32` this board?** It can't be — the SSD holds a Raspberry Pi ARM
image with the Pi's bootloader, which the HC4 cannot boot, so it has no network stack.
Confirm in 30 s: unplug the HC4's Ethernet, then from the Mac `ping -c3 192.168.86.32`.
Still replies → it's some other device (that MAC's OUI is `00:1e:06` / WIBRAIN, the block
ODROID boards ship with — likely an older ODROID of yours, definitely not a Pi).

**b) What is the SSD, physically?**
- **2.5" SATA** → drops straight into the HC4 bay. ✅
- **M.2 NVMe** (from a Pi 5 HAT) → **does not fit the HC4 at all.** No M.2 slot.

Plug it into the Mac in whatever enclosure it used on the Pi and run:
```bash
diskutil list external physical
diskutil info /dev/diskN | egrep "Device / Media Name|Protocol|Disk Size|Solid State"
```

⚠️ **Back up anything you want off it before we go further** — install wipes it.

## 1. Get an OS on it

You need a **microSD card** (the one from the Pi works) and a card reader.

**Use Hardkernel's own Ubuntu image, NOT Armbian.** Recent Armbian on HC4 has documented
breakage: petitboot conflicts, SATA drives not detected, USB keyboard dead.

1. Download the HC4 Ubuntu 24.04 image from the Hardkernel wiki
   (`wiki.odroid.com/odroid-hc4/os_images/os_images` → `dn.odroid.com`). Both block
   scripted fetches, so grab it in a browser. File is a `.img.xz`.
2. Write it to the microSD:
```bash
cd ~/Downloads
xz -dk odroid-hc4-ubuntu-*.img.xz          # or use Raspberry Pi Imager / balenaEtcher

diskutil list external physical            # ← IDENTIFY THE CARD. Destructive.
diskutil unmountDisk /dev/diskN
sudo dd if=odroid-hc4-ubuntu-*.img of=/dev/rdiskN bs=4m
diskutil eject /dev/diskN
```
3. Card into the HC4, SATA SSD in the bay, Ethernet in, 15 V power on.
4. Find it (Hardkernel images ship with sshd enabled, user `root`/`odroid` or
   `odroid`/`odroid` depending on image — check the wiki page you downloaded from):
```bash
for i in $(seq 1 254); do (ping -c1 -W 200 192.168.86.$i >/dev/null 2>&1 &); done
sleep 5; arp -an | grep -i "0:1e:6"
```

If it doesn't appear: HDMI monitor + USB keyboard, watch petitboot. (Note: the single
USB port means keyboard *or* hub, not both — plan for that.)

## 2. First login

```bash
ssh <user>@<ip>
sudo apt update && sudo apt install -y v4l-utils usbutils ffmpeg git curl
sudo usermod -aG dialout,video,plugdev $USER      # serial + camera access; re-login
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --ssh
uname -m                                          # expect aarch64
```
Give it a **DHCP reservation** on the router.

## 3. THE KILL CRITERION — do this before anything else

Everything downstream depends on lerobot working on ARM64. Find out in 30 minutes, not
after a day of cabling.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv && uv pip install "lerobot==0.6.0"
uv run python -c "import lerobot; print(lerobot.__version__)"
```
A bare `Illegal instruction` here is the documented ARM failure (lerobot #1738).
**If this fails → stop. The HC4 is a NAS, and the room host becomes a ~€150 N100 box.**

## 4. USB survey + the MJPG A/B

Single USB 2.0 port, so: **powered multi-TT hub**, then everything into it.

```bash
lsusb -t                    # arms should be 12M; cameras 480M; all under one root
ls -l /dev/serial/by-id/ /dev/v4l/by-id/
v4l2-ctl -d /dev/video0 --list-formats-ext      # confirm MJPG @640x480x30 exists
v4l2-ctl -d /dev/video0 --list-ctrls            # confirm exposure/WB/focus WRITABLE
```

Then the decisive test — both cameras at once, raw first, then MJPG:
```bash
for d in 0 1; do ffmpeg -hide_banner -f v4l2 -input_format yuyv422 \
  -video_size 640x480 -framerate 30 -i /dev/video$d -t 60 -f null - & done; wait
for d in 0 1; do ffmpeg -hide_banner -f v4l2 -input_format mjpeg \
  -video_size 640x480 -framerate 30 -i /dev/video$d -t 60 -f null - & done; wait
```
Expected: YUYV = ~295 Mbps of a ~384 Mbps budget → wedges or drops. MJPG = ~60 Mbps → clean.

## 5. Encoding check (the second risk)

No hardware encoder, four A55 cores, and lerobot defaults to **libsvtav1** (AV1):
```bash
for c in "libsvtav1" "libx264 -preset ultrafast"; do
  echo "== $c"; ffmpeg -hide_banner -f lavfi -i testsrc=size=640x480:rate=30 \
    -t 20 -c:v $c -f null - 2>&1 | tail -1; done
```
Need comfortably >1× realtime per stream. If AV1 is hopeless: switch to x264 ultrafast,
or record frames as images and encode later on the Mac/DE server.

## 6. Then
udev rules for stable device names, systemd unit for the hub agent, and back to the
session plan in `lab-setup-2026-08.md`.
