# `host/` — what runs on the room host (`lab-pi`)

`labstatus.py` → `~/labstatus.py` on the Pi, run by `labstatus.service`.
Shows hostname, Tailscale + LAN IP, link state, temp/throttle, load, `/data` free,
presence of both cameras and both arms, and the live camera session (it reads
`/data/session.json`, which `lab_cameras` writes).

Two things in it are load-bearing and easy to undo by accident:

- **Only changed rows are pushed.** A full 320×480×16bpp frame is 300 KiB, which at this
  panel's 16 MHz SPI takes ~154 ms to shift out, while the fbtft worker re-fires every
  33 ms (`fps=30`). Rewriting the whole buffer every refresh produced torn frames with a
  stale band that persisted for the full 2 s refresh. Measured after: **11–28 rows per
  refresh instead of 480.**
- **The session banner requires a heartbeat younger than 10 s.** `flock` is the real
  ownership truth; a `kill -9`d owner leaves `session.json` behind, and a screen that
  claims RECORDING when nothing is recording is worse than no banner.

Panel config lives in `/boot/firmware/config.txt` (one line, see
`notes/lab-setup-2026-08.md`). `bgr=1` was removed 2026-08-23 after a labelled test
pattern measured drawn-RED appearing as blue (B=234, R=3) and drawn-BLUE as red (R=142).
Backup at `/boot/firmware/config.txt.bak-bgr`.
