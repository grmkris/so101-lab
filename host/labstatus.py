#!/usr/bin/env python3
"""so101-lab status display - Waveshare 3.5in ILI9486 (320x480) via fbtft /dev/fb0.
Large type: the panel is ~180 DPI, so anything under ~18px is unreadable across a room.
"""
import os, mmap, time, json, socket, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FB = "/dev/fb0"
W, H = [int(v) for v in open("/sys/class/graphics/fb0/virtual_size").read().strip().split(",")]
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
F_HOST = ImageFont.truetype(SANS, 34)
F_VAL = ImageFont.truetype(MONO, 23)
F_LBL = ImageFont.truetype(SANS, 17)
F_DEV = ImageFont.truetype(SANS, 19)
F_REC = ImageFont.truetype(SANS, 27)
F_FOOT = ImageFont.truetype(MONO, 15)

BG = (0, 0, 0)
FG = (255, 255, 255)
DIM = (150, 160, 180)
OK = (0, 255, 110)
WARN = (255, 200, 0)
BAD = (255, 60, 70)
ACC = (80, 190, 255)


def sh(cmd, default=""):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or default
    except Exception:
        return default


_c = {"t": 0.0, "ts": "-", "thr": "?", "up": "-"}


def slow():
    now = time.time()
    if now - _c["t"] > 30:
        _c["ts"] = sh("tailscale ip -4 2>/dev/null | head -1", "-")
        _c["thr"] = sh("vcgencmd get_throttled", "throttled=?").split("=")[-1]
        secs = float(open("/proc/uptime").read().split()[0])
        d, r = divmod(int(secs), 86400)
        h, m = divmod(r, 3600)
        _c["up"] = ("%dd%dh" % (d, h)) if d else ("%dh%02dm" % (h, m // 60))
        _c["t"] = now
    return _c


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.86.1", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "-"


def stats():
    c = slow()
    s = {"host": socket.gethostname(), "ts": c["ts"], "lan": lan_ip(),
         "thr": c["thr"], "up": c["up"]}
    try:
        s["link"] = open("/sys/class/net/eth0/operstate").read().strip()
    except Exception:
        s["link"] = "?"
    try:
        s["temp"] = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except Exception:
        s["temp"] = 0
    s["load"] = os.getloadavg()[0]
    try:
        v = os.statvfs("/data")
        s["dfree"] = v.f_bavail * v.f_frsize / 1e9
    except Exception:
        s["dfree"] = 0
    s["cam_ctx"] = os.path.exists("/dev/cam_context")
    s["cam_wr"] = os.path.exists("/dev/cam_wrist")
    s["arm_l"] = os.path.exists("/dev/so101_leader")
    s["arm_f"] = os.path.exists("/dev/so101_follower")
    # session.json is written by lab_cameras. A SIGKILLed owner leaves the file
    # behind (flock is the real truth, not this file), so trust the heartbeat:
    # a stale banner claiming RECORDING is worse than no banner at all.
    s["rec"] = None
    try:
        if os.path.exists("/data/session.json"):
            doc = json.load(open("/data/session.json"))
            if time.time() - float(doc.get("heartbeat", 0)) < 10:
                s["rec"] = doc
    except Exception:
        pass
    return s


def draw(s):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    y = 0

    # header
    d.rectangle([0, 0, W - 1, 46], fill=(18, 24, 38))
    d.text((10, 5), s["host"], font=F_HOST, fill=ACC)
    up = "UP" if s["link"] == "up" else "DOWN"
    col = OK if s["link"] == "up" else BAD
    d.text((W - 12 - d.textlength(up, font=F_DEV), 16), up, font=F_DEV, fill=col)
    y = 56

    # tailscale - the number you actually want to read
    d.text((10, y), "TAILSCALE", font=F_LBL, fill=DIM)
    y += 21
    d.text((10, y), s["ts"], font=F_VAL, fill=ACC)
    y += 32
    d.text((10, y), "LAN", font=F_LBL, fill=DIM)
    y += 21
    d.text((10, y), s["lan"], font=F_VAL, fill=FG)
    y += 36

    d.line([8, y, W - 8, y], fill=(60, 70, 95))
    y += 12

    # vitals - two per line, big
    tcol = OK if s["temp"] < 60 else (WARN if s["temp"] < 70 else BAD)
    dcol = OK if s["dfree"] > 100 else (WARN if s["dfree"] > 20 else BAD)
    d.text((10, y), "%.0fC" % s["temp"], font=F_VAL, fill=tcol)
    d.text((110, y), "ld %.1f" % s["load"], font=F_VAL, fill=FG)
    y += 30
    d.text((10, y), "%.0fGB free" % s["dfree"], font=F_VAL, fill=dcol)
    y += 30
    thr = int(s["thr"], 16) if s["thr"].startswith("0x") else 0
    if thr & 0xF:  # happening right now
        d.text((10, y), "THROTTLED NOW", font=F_VAL, fill=BAD)
        y += 30
    elif thr:      # happened since boot - worth knowing, not worth alarming
        d.text((10, y), "thr since boot " + s["thr"], font=F_LBL, fill=WARN)
        y += 22

    d.line([8, y, W - 8, y], fill=(60, 70, 95))
    y += 12

    # devices - 2x2 grid of big pills
    cells = [("CAM CTX", s["cam_ctx"]), ("CAM WRIST", s["cam_wr"]),
             ("ARM LEAD", s["arm_l"]), ("ARM FOLL", s["arm_f"])]
    cw, ch = (W - 24) // 2, 38
    for i, (lbl, ok) in enumerate(cells):
        cx = 10 + (i % 2) * (cw + 4)
        cy = y + (i // 2) * (ch + 5)
        d.rectangle([cx, cy, cx + cw - 1, cy + ch - 1],
                    fill=(0, 55, 25) if ok else (60, 12, 16),
                    outline=OK if ok else BAD)
        tw = d.textlength(lbl, font=F_DEV)
        d.text((cx + (cw - tw) / 2, cy + 9), lbl, font=F_DEV, fill=OK if ok else BAD)
    y += 2 * ch + 5 + 14

    # session banner
    if s["rec"]:
        r = s["rec"]
        mode = str(r.get("mode", "")).upper()
        recording = mode == "RECORD" or "episode" in r
        head = "RECORDING" if recording else (mode or "CAMS BUSY")
        d.rectangle([8, y, W - 9, y + 74],
                    fill=(0, 70, 30) if recording else (20, 45, 70),
                    outline=OK if recording else ACC, width=3)
        d.text((18, y + 6), head[:12], font=F_REC, fill=OK if recording else ACC)
        if recording:
            sub = "ep %s/%s" % (r.get("episode", "?"), r.get("total", "?"))
        else:
            fps = [h.get("fps") for h in (r.get("health") or {}).values() if h.get("fps")]
            sub = ("%s  %.0f/%.0ffps" % (r.get("host", ""), fps[0], fps[-1])) if len(fps) >= 2                 else str(r.get("owner", ""))[:16]
        d.text((18, y + 42), sub[:17], font=F_VAL, fill=FG)
    else:
        d.rectangle([8, y, W - 9, y + 44], fill=(26, 28, 36))
        t = "IDLE"
        d.text((8 + (W - 17 - d.textlength(t, font=F_REC)) / 2, y + 6), t,
               font=F_REC, fill=DIM)

    d.text((10, H - 22), "up " + s["up"], font=F_FOOT, fill=DIM)
    ts = time.strftime("%H:%M:%S")
    d.text((W - 10 - d.textlength(ts, font=F_FOOT), H - 22), ts, font=F_FOOT, fill=DIM)
    return im


# The framebuffer is mmapped and only CHANGED ROWS are written back.
#
# Why it matters: a full 320x480x16bpp frame is 300 KiB, which at this panel's
# 16 MHz SPI takes ~154 ms to shift out - but the fbtft worker re-fires every
# 33 ms (fps=30). Rewriting the whole buffer every refresh dirties all 75 pages
# and starts a full push that the next tick interrupts, which is where the torn
# frames with a stale band came from. A clock-only update touches two rows, so
# fbtft pushes two rows.
_FB_FD = os.open(FB, os.O_RDWR)
_FB_MAP = mmap.mmap(_FB_FD, W * H * 2)
_PREV = None


def _runs(rows):
    """Contiguous [start, end] spans in a sorted row index array."""
    out, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r != prev + 1:
            out.append((start, prev))
            start = r
        prev = r
    out.append((start, prev))
    return out


def push(im):
    global _PREV
    a = np.asarray(im.convert("RGB"), dtype=np.uint16)
    # round rather than truncate - keeps antialiased edges closer to intent
    r = np.minimum((a[:, :, 0] + 4) >> 3, 31)
    g = np.minimum((a[:, :, 1] + 2) >> 2, 63)
    b = np.minimum((a[:, :, 2] + 4) >> 3, 31)
    v = ((r << 11) | (g << 5) | b).astype("<u2")

    if _PREV is None:
        _FB_MAP[:] = v.tobytes()
        _PREV = v
        return
    changed = np.flatnonzero((v != _PREV).any(axis=1))
    if not changed.size:
        return
    buf = v.tobytes()
    for lo, hi in _runs(changed):
        off, n = lo * W * 2, (hi - lo + 1) * W * 2
        _FB_MAP[off:off + n] = buf[off:off + n]
    _PREV = v


if __name__ == "__main__":
    while True:
        try:
            push(draw(stats()))
        except Exception as e:
            print("err:", e, flush=True)
        time.sleep(2)
