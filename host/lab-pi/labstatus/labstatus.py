#!/usr/bin/env python3
"""Read-only 320x480 lab-pi touchscreen dashboard. No camera or motor device access."""
import argparse
import fcntl
import json
import math
import mmap
import os
from pathlib import Path
import re
import select
import socket
import struct
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 320, 480
TABS = ('Overview', 'Cameras', 'System', 'Session')
BG, PANEL = '#0a101a', '#152235'
FG, DIM, ACC, OK, WARN, BAD = '#f0f5fc', '#a4b2c8', '#69caff', '#6fe0aa', '#ffd27a', '#ff858e'
NAV_Y = 380


def font(size, mono=False):
    name = 'DejaVuSansMono' if mono else 'DejaVuSans'
    for path in (f'/usr/share/fonts/truetype/dejavu/{name}.ttf', f'{name}.ttf',
                 '/System/Library/Fonts/Supplemental/Arial.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


FONTS = {size: font(size) for size in (14, 16, 18, 20, 24, 30)}


def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def command(args, default='unknown'):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=2).stdout.strip() or default
    except (OSError, subprocess.SubprocessError):
        return default


def fresh_session(doc, now):
    """A stale or future heartbeat never claims active ownership or recording."""
    try:
        age = now - float(doc['heartbeat'])
        return doc if 0 <= age < 10 else None
    except (TypeError, KeyError, ValueError):
        return None


def camera_status(session, name, now):
    if not fresh_session(session, now):
        return 'No fresh report', WARN
    health = session.get('health') or {}
    item = health.get(name) or (health.get('context') if name == 'workspace' else None) or {}
    try:
        # age_ms was sampled at heartbeat time, so add the time since that sample.
        age = float(item['age_ms']) + 1000 * (now - float(session['heartbeat']))
        if not math.isfinite(age) or age < 0:
            raise ValueError('invalid age')
        fps = float(item.get('fps', 0))
        if not math.isfinite(fps):
            raise ValueError('invalid fps')
        return (f'{fps:.0f} fps / {age / 1000:.1f}s old', OK if age < 2000 else BAD)
    except (TypeError, KeyError, ValueError):
        return 'Frame age unknown', WARN


def throttle_status(value):
    try:
        flags = int(value, 16)
    except (TypeError, ValueError):
        return 'Flags unavailable', WARN
    if flags & 1:
        return 'Undervoltage NOW', BAD
    if flags & 4:
        return 'Throttling NOW', BAD
    if flags & 10:
        return 'Clock/temp limited', WARN
    if flags:
        return 'Past event this boot', WARN
    return 'OK', OK


class PiStatsSampler:
    """Read cheap local metrics and calculate CPU percentage from two samples."""

    def __init__(self):
        self._previous_cpu = None

    @staticmethod
    def _read(path, default=""):
        try:
            return Path(path).read_text().strip()
        except OSError:
            return default

    @staticmethod
    def _command(args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def _cpu_usage(self):
        try:
            fields = self._read("/proc/stat").splitlines()
            if not fields or not fields[0].startswith("cpu "):
                return None
            values = [int(value) for value in fields[0].split()[1:9]]
        except (IndexError, ValueError):
            return None
        if len(values) < 5:
            return None
        idle = values[3] + values[4]
        total = sum(values)
        previous = self._previous_cpu
        self._previous_cpu = (total, idle)
        if previous is None or total <= previous[0]:
            return None
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))

    def sample(self):
        temp = None
        try:
            temp = float(self._read("/sys/class/thermal/thermal_zone0/temp")) / 1000
        except (TypeError, ValueError):
            match = re.search(r"(-?\d+(?:\.\d+)?)", self._command(["vcgencmd", "measure_temp"]))
            if match:
                temp = float(match.group(1))

        mem = {}
        for line in self._read("/proc/meminfo").splitlines():
            key, _, value = line.partition(":")
            if value:
                try:
                    mem[key] = int(value.strip().split()[0]) * 1024
                except (TypeError, ValueError):
                    pass
        total_mem = mem.get("MemTotal")
        available_mem = mem.get("MemAvailable", mem.get("MemFree"))
        stat = None
        try:
            stat = os.statvfs("/")
        except OSError:
            pass
        total_disk = stat.f_blocks * stat.f_frsize if stat else None
        free_disk = stat.f_bavail * stat.f_frsize if stat else None
        used_disk = (stat.f_blocks - stat.f_bfree) * stat.f_frsize if stat else None
        uptime = None
        try:
            uptime = float(self._read("/proc/uptime").split()[0])
        except (IndexError, TypeError, ValueError):
            pass
        throttled = self._command(["vcgencmd", "get_throttled"]).split("=")[-1] or None
        try:
            load = os.getloadavg()[0]
        except OSError:
            load = None
        return {
            "cpu_temp": temp,
            "cpu_pct": self._cpu_usage(),
            "load": load,
            "ram_total": total_mem,
            "ram_used": total_mem - available_mem if total_mem is not None and available_mem is not None else None,
            "disk_total": total_disk,
            "disk_free": free_disk,
            "disk_used": used_disk,
            "uptime": uptime,
            "throttled": throttled,
        }


def power_status(value):
    """Return a label and severity, including flags recording past power events."""
    try:
        flags = int(str(value), 16)
    except (ValueError, TypeError):
        return "UNAVAILABLE", "warning"
    names = ("undervoltage", "frequency capped", "throttled", "soft temp limit")
    current = [name for bit, name in enumerate(names) if flags & (1 << bit)]
    past = [name for bit, name in enumerate(names) if flags & (1 << (bit + 16))]
    if current:
        return "NOW: " + ", ".join(current), "bad"
    if past:
        return "Past: " + ", ".join(past), "warning"
    return ("OK", "ok") if flags == 0 else (f"Flags: {hex(flags)}", "warning")


def draw_stats(text, stats, y=166, palette=None):
    """Draw the same compact two-column metrics on any 320px Pillow dashboard.

    `text(x, y, value, size, color, width=...)` is supplied by the host dashboard.
    No Pillow dependency or device actions; robot dashboards can copy this module.
    """
    colors = dict(fg="#f0f5fc", dim="#a4b2c8", ok="#6fe0aa", warning="#ffd27a", bad="#ff858e")
    colors.update(palette or {})

    def cell(x, top, label, value, color=None):
        text(x, top, label, 14, colors["dim"], width=144)
        text(x, top + 18, value, 18, color or colors["fg"], width=144)

    temp, cpu = stats.get("cpu_temp"), stats.get("cpu_pct")
    cell(12, y, "CPU TEMP", f"{temp:.1f} °C" if temp is not None else "unknown",
         colors["bad"] if temp is not None and temp > 70 else colors["fg"])
    cell(164, y, "CPU USAGE", f"{cpu:.1f}%" if cpu is not None else "sampling…")
    ram, used = stats.get("ram_total"), stats.get("ram_used")
    cell(12, y + 44, "RAM USED / TOTAL", f"{used / 2**30:.1f} / {ram / 2**30:.1f}G" if ram and used is not None else "unknown")
    load = stats.get("load")
    cell(164, y + 44, "LOAD (1 MIN)", f"{load:.2f}" if load is not None else "unknown")
    used, free = stats.get("disk_used"), stats.get("disk_free")
    cell(12, y + 88, "SD / USED", f"{used / 2**30:.1f} GiB" if used is not None else "unknown")
    cell(164, y + 88, "SD / FREE", f"{free / 2**30:.1f} GiB" if free is not None else "unknown")
    uptime = stats.get("uptime")
    if uptime is None:
        uptime_text = "unknown"
    else:
        days, hours = divmod(int(uptime) // 3600, 24)
        uptime_text = f"{days}d {hours}h" if days else f"{hours}h {int(uptime) % 3600 // 60}m"
    cell(12, y + 132, "UPTIME", uptime_text)
    label, severity = power_status(stats.get("throttled"))
    power = "OK" if severity == "ok" else stats.get("throttled") or "unknown"
    cell(164, y + 132, "POWER / THROTTLE", power, colors[severity])
    text(12, y + 180, "Local metrics · refresh ~5 s" if severity == "ok" else label, 14,
         colors["dim"] if severity == "ok" else colors[severity], width=296)


class Collector:
    def __init__(self, session_path='/data/session.json', debug=False):
        self.session_path = session_path
        self.debug = debug
        self.stats_logged = False
        self.cached = {}
        self.next_slow = 0
        self.stats = PiStatsSampler()

    def sample(self):
        if time.monotonic() >= self.next_slow:
            self.next_slow = time.monotonic() + 6
            self.cached = {
                'ts': command(['tailscale', 'ip', '-4'], '-').splitlines()[0],
                'preview': command(['systemctl', 'is-active', 'labcam-preview']),
                'motor': command(['systemctl', 'is-active', 'robo-io']),
            }
        now = time.time()
        s = dict(self.cached, host=socket.gethostname(), now=now)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(('192.0.2.1', 1))  # route lookup only, no packet sent
                s['lan'] = sock.getsockname()[0]
        except OSError:
            s['lan'] = '-'
        s['link'] = read('/sys/class/net/eth0/operstate', 'unknown')
        stats = self.stats.sample()
        s['stats'] = stats
        s.update(temp=stats['cpu_temp'], cpu=stats['cpu_pct'], load=stats['load'],
                 up=stats['uptime'], thr=stats['throttled'])
        for target, source in (('free', 'disk_free'), ('total', 'disk_total'), ('used', 'disk_used'),
                               ('ram_total', 'ram_total'), ('ram_used', 'ram_used')):
            s[target] = stats[source] / 2**30 if stats[source] is not None else None
        try:
            s['data_on_root'] = os.stat('/data').st_dev == os.stat('/').st_dev
        except OSError:
            s['data_on_root'] = False
        if self.debug and not self.stats_logged and s.get('cpu') is not None:
            print(
                'Stats sample: '
                f"temp={s.get('temp')}C cpu={s.get('cpu')}% load={s.get('load')} "
                f"ram={s.get('ram_used')}/{s.get('ram_total')}GiB "
                f"disk_used={s.get('used')}GiB disk_free={s.get('free')}GiB disk_total={s.get('total')}GiB "
                f"uptime={s.get('up')}s throttling={s.get('thr')}",
                flush=True,
            )
            self.stats_logged = True
        for key, path in (('cam_ctx', 'cam_context'), ('cam_wr', 'cam_wrist'),
                          ('arm_l', 'so101_leader'), ('arm_f', 'so101_follower')):
            s[key] = os.path.exists('/dev/' + path)
        try:
            doc = json.loads(read(self.session_path))
            s['session'] = fresh_session(doc, now)
        except (ValueError, TypeError):
            s['session'] = None
        return s


def tab_at(x, y):
    if not (0 <= x < W and NAV_Y <= y < H):
        return None
    return TABS[min(int((y - NAV_Y) // 50), 1) * 2 + int(x // 160)]


def draw(s, tab='Overview', touch=True):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)

    def text(x, y, value, size=20, color=FG, width=296):
        value = str(value)
        while value and d.textlength(value, font=FONTS[size]) > width:
            value = value[:-2] + '…' if len(value) > 2 else ''
        d.text((x, y), value, font=FONTS[size], fill=color)

    def row(y, label, value, color=FG):
        text(12, y, label.upper(), 14, DIM)
        text(12, y + 19, value, 24, color)

    d.rectangle((0, 0, W, 48), fill=PANEL)
    text(12, 8, s.get('host', 'lab-pi'), 24, ACC, 204)
    text(238, 16, 'ETH UP' if s.get('link') == 'up' else 'NO ETH', 14,
         OK if s.get('link') == 'up' else WARN, 78)
    text(12, 57, tab, 30)
    session = fresh_session(s.get('session'), s['now'])
    mode = str(session.get('mode', 'active')).upper() if session else 'NO FRESH OWNER'
    if tab == 'Overview':
        text(12, 103, 'Camera session: ' + mode, 16, ACC if session else WARN)
        text(12, 128, 'Motor service: ' + s.get('motor', 'unknown'), 16)
        draw_stats(text, s.get('stats') or {}, y=157)
        text(12, 354, 'Power / motion readiness unknown', 16, DIM)
    elif tab == 'Cameras':
        for y, label, key, name in ((105, 'Context', 'cam_ctx', 'workspace'), (186, 'Wrist', 'cam_wr', 'wrist')):
            text(12, y, label, 24, ACC)
            text(172, y + 5, 'USB present' if s.get(key) else 'USB missing', 16, DIM, 142)
            value, color = camera_status(session, name, s['now'])
            text(12, y + 33, value, 20, color)
        text(12, 275, 'Preview: ' + s.get('preview', 'unknown'), 20)
        text(12, 307, 'Owner: ' + str(session.get('owner', '?') if session else 'unconfirmed'), 18, DIM)
        text(12, 347, 'USB presence ≠ fresh camera frames', 16, DIM)
    elif tab == 'System':
        row(102, 'Tailscale', s.get('ts', '-'), ACC)
        row(157, 'LAN', s.get('lan', '-'))
        text(12, 219, 'Leader USB: ' + ('present' if s.get('arm_l') else 'missing'), 20)
        text(12, 249, 'Follower USB: ' + ('present' if s.get('arm_f') else 'missing'), 20)
        text(12, 282, '/data: ' + ('SD root filesystem' if s.get('data_on_root') else 'check mount'), 18,
             OK if s.get('data_on_root') else WARN)
        hours, minutes = divmod(int(s.get('up') or 0) // 60, 60)
        load = f"{s['load']:.1f}" if s.get('load') is not None else 'unknown'
        text(12, 314, f"Up {hours}h {minutes:02d}m · load {load}", 18, DIM)
        text(12, 347, 'Touch: ready' if touch else 'Touch unavailable', 18, DIM if touch else WARN)
    elif tab == 'Session':
        row(104, 'Reported mode', mode, ACC if session else WARN)
        row(166, 'Camera owner', session.get('owner', '?') if session else 'Unconfirmed')
        if session:
            text(12, 231, f"Heartbeat {s['now'] - float(session['heartbeat']):.1f}s ago", 20, DIM)
            if 'episode' in session:
                text(12, 264, f"Episode {session['episode']} / {session.get('total', '?')}", 24, ACC)
        else:
            text(12, 231, 'No heartbeat within 10 seconds.', 18, DIM)
        text(12, 311, 'Status only · no motion controls', 18, DIM)
        text(12, 347, 'Motor power is not measured', 18, WARN)
    for i, title in enumerate(TABS):
        x, y = (i % 2) * 160, NAV_Y + (i // 2) * 50
        selected = title == tab
        d.rectangle((x + 3, y + 3, x + 156, y + 46), fill='#214668' if selected else PANEL)
        width = d.textlength(title, font=FONTS[20])
        text(x + (160 - width) / 2, y + 11, title, 20, ACC if selected else FG, 150)
    return im


class Touch:
    """Read only the named touchscreen. Never grab it or open camera/servo ports."""
    EVENT = struct.Struct('llHHi')

    def __init__(self, calibration=None, debug=False):
        self.debug = debug
        self.fd = None
        self.device = None
        self.x = self.y = None
        self.down = False
        self.pending_release = False
        self.matrix = None
        if calibration:
            doc = json.loads(Path(calibration).read_text())
            if doc.get('size') != [W, H] or len(doc['records']) < 3:
                raise ValueError('Touch calibration must describe this 320x480 screen')
            raw = np.array([[*r['raw'], 1] for r in doc['records']])
            targets = np.array([r['target'] for r in doc['records']])
            self.matrix = np.linalg.lstsq(raw, targets, rcond=None)[0]
        self.ranges = [(0, 4095), (0, 4095)]
        self.connect()

    def connect(self):
        for event in sorted(Path('/sys/class/input').glob('event*')):
            if read(event / 'device/name') != 'ADS7846 Touchscreen':
                continue
            fd = os.open('/dev/input/' + event.name, os.O_RDONLY | os.O_NONBLOCK)
            try:
                for axis in (0, 1):
                    buf = bytearray(24)
                    fcntl.ioctl(fd, 0x80184540 + axis, buf, True)  # EVIOCGABS(axis)
                    _, lo, hi, _, _, _ = struct.unpack('iiiiii', buf)
                    if hi <= lo:
                        raise ValueError('Invalid touch axis range')
                    self.ranges[axis] = lo, hi
                self.fd = fd
                self.device = '/dev/input/' + event.name
                if self.debug:
                    print(f'Touch connected: /dev/input/{event.name}, ranges={self.ranges}, calibrated={self.matrix is not None}', flush=True)
                return
            except Exception:
                os.close(fd)
                raise
        raise FileNotFoundError('ADS7846 Touchscreen not found')

    def feed(self, kind, code, value, raw=False):
        if kind == 0 and code == 3:  # SYN_DROPPED: don't invent a tap
            self.down = self.pending_release = False
            self.x = self.y = None
        elif kind == 3 and code == 0:
            self.x = value
        elif kind == 3 and code == 1:
            self.y = value
        elif kind == 1 and code == 330:  # BTN_TOUCH
            if value:
                self.down = True
            elif self.down:
                self.down = False
                self.pending_release = True
        elif kind == 0 and code == 0 and self.pending_release:
            self.pending_release = False
            if self.x is None or self.y is None:
                return None
            if raw:
                return self.x, self.y
            if self.matrix is not None:
                x, y = np.array([self.x, self.y, 1]) @ self.matrix
            else:
                x = (self.x - self.ranges[0][0]) / (self.ranges[0][1] - self.ranges[0][0]) * (W - 1)
                y = (self.y - self.ranges[1][0]) / (self.ranges[1][1] - self.ranges[1][0]) * (H - 1)
            point = max(0, min(W - 1, x)), max(0, min(H - 1, y))
            if self.debug:
                print(f'Touch released: raw=({self.x},{self.y}), screen=({point[0]:.1f},{point[1]:.1f}), tab={tab_at(*point)}', flush=True)
            return point
        return None

    def poll(self, timeout, raw=False):
        if self.fd is None:
            time.sleep(timeout)
            return []
        if not select.select([self.fd], [], [], timeout)[0]:
            return []
        buf = os.read(self.fd, self.EVENT.size * 64)
        if not buf:
            raise OSError('Touchscreen disconnected')
        taps = []
        for offset in range(0, len(buf) - self.EVENT.size + 1, self.EVENT.size):
            _, _, kind, code, value = self.EVENT.unpack_from(buf, offset)
            tap = self.feed(kind, code, value, raw=raw)
            if tap:
                taps.append(tap)
        return taps

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def calibrate(path, framebuffer_path):
    screen = Framebuffer(framebuffer_path)
    touch = None
    records = []
    try:
        touch = Touch(debug=True)
        for index, target in enumerate(((35, 65), (285, 65), (285, 415), (35, 415))):
            image = Image.new('RGB', (W, H), BG)
            painter = ImageDraw.Draw(image)
            painter.text((12, 120), 'TOUCH SETUP', font=FONTS[24], fill=ACC)
            painter.text((12, 162), f'Tap target {index + 1} / 4', font=FONTS[24], fill=FG)
            painter.text((12, 207), 'Release between taps.', font=FONTS[18], fill=DIM)
            painter.text((12, 239), '45 seconds per target.', font=FONTS[18], fill=DIM)
            target_x, target_y = target
            painter.line((target_x - 18, target_y, target_x + 18, target_y), fill=OK, width=3)
            painter.line((target_x, target_y - 18, target_x, target_y + 18), fill=OK, width=3)
            screen.push(image)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                points = touch.poll(.25, raw=True)
                if points:
                    records.append({'target': list(target), 'raw': list(points[0])})
                    break
            else:
                raise TimeoutError('Calibration timed out; existing calibration kept')
        raw = np.array([[*record['raw'], 1] for record in records], dtype=float)
        targets = np.array([record['target'] for record in records], dtype=float)
        matrix, _, rank, _ = np.linalg.lstsq(raw, targets, rcond=None)
        if rank != 3 or not np.isfinite(matrix).all() or np.max(np.linalg.norm(raw @ matrix - targets, axis=1)) > 30:
            raise ValueError('Inconsistent calibration taps; existing calibration kept')
        document = dict(status='complete', input_device=touch.device, size=[W, H],
                        records=records, method='four-corner-affine')
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=Path(path).parent, prefix='.labstatus-touch-', delete=False) as calibration_file:
                temporary_path = calibration_file.name
                json.dump(document, calibration_file, indent=2)
                calibration_file.write('\n')
                calibration_file.flush()
                os.fsync(calibration_file.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        image = Image.new('RGB', (W, H), BG)
        painter = ImageDraw.Draw(image)
        painter.text((12, 155), 'Calibration complete', font=FONTS[24], fill=OK)
        screen.push(image)
        time.sleep(1)
    finally:
        if touch:
            touch.close()
        screen.close()


def _runs(rows):
    if not len(rows):
        return []
    out, start, prev = [], rows[0], rows[0]
    for row in rows[1:]:
        if row != prev + 1:
            out.append((start, prev))
            start = row
        prev = row
    return out + [(start, prev)]


class Framebuffer:
    def __init__(self, path='/dev/fb0'):
        name = Path(path).name
        size = read(f'/sys/class/graphics/{name}/virtual_size')
        depth = read(f'/sys/class/graphics/{name}/bits_per_pixel')
        stride = read(f'/sys/class/graphics/{name}/stride')
        if size != f'{W},{H}' or depth != '16' or stride not in ('', str(W * 2)):
            raise RuntimeError('Expected packed 320x480 RGB565 framebuffer')
        self.fd = os.open(path, os.O_RDWR)
        self.mapping = mmap.mmap(self.fd, W * H * 2)
        self.previous = None

    def push(self, im):
        a = np.asarray(im.convert('RGB'), dtype=np.uint16)
        r = np.minimum((a[:, :, 0] + 4) >> 3, 31)
        g = np.minimum((a[:, :, 1] + 2) >> 2, 63)
        b = np.minimum((a[:, :, 2] + 4) >> 3, 31)
        packed = ((r << 11) | (g << 5) | b).astype('<u2')
        # Keep SPI traffic bounded: unchanged rows must never be rewritten.
        rows = np.arange(H) if self.previous is None else np.flatnonzero((packed != self.previous).any(axis=1))
        buf = packed.tobytes()
        for lo, hi in _runs(rows):
            start, end = lo * W * 2, (hi + 1) * W * 2
            self.mapping[start:end] = buf[start:end]
        self.previous = packed

    def close(self):
        self.mapping.close()
        os.close(self.fd)


def demo():
    now = time.time()
    return dict(host='lab-pi', now=now, temp=61.8, cpu=34, load=1.2, up=7342,
                stats=dict(cpu_temp=61.8, cpu_pct=34, load=1.2, uptime=7342, throttled='0x0',
                           ram_used=.8 * 2**30, ram_total=3.7 * 2**30,
                           disk_used=19 * 2**30, disk_free=216 * 2**30, disk_total=235 * 2**30),
                free=216, total=235, used=19, ram_used=.8, ram_total=3.7,
                data_on_root=True, link='up', ts='100.77.154.45',
                lan='192.168.1.52', thr='0x0', preview='active', motor='inactive',
                cam_ctx=True, cam_wr=True, arm_l=True, arm_f=True,
                session=dict(heartbeat=now - .3, owner='labcam-preview', mode='preview',
                             health={name: {'fps': 30, 'age_ms': 24} for name in ('workspace', 'wrist')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', metavar='PNG', help='Render a demo without reading any Pi devices')
    parser.add_argument('--snapshot', metavar='JSON', help='Offline state for --render, instead of demo data')
    parser.add_argument('--tab', choices=TABS, default='Overview')
    parser.add_argument('--touch-calibration', metavar='JSON', help='Optional existing four-corner raw/target measurements')
    parser.add_argument('--calibrate', action='store_true', help='Show four targets; abort after 45 seconds without a tap')
    parser.add_argument('--no-touch', action='store_true')
    parser.add_argument('--debug-touch', action='store_true', help='Log input discovery and released-tap coordinates')
    parser.add_argument('--framebuffer', default='/dev/fb0')
    args = parser.parse_args()
    if args.calibrate:
        if not args.touch_calibration:
            parser.error('--calibrate requires --touch-calibration')
        calibrate(args.touch_calibration, args.framebuffer)
        return
    if args.render:
        state = json.loads(Path(args.snapshot).read_text()) if args.snapshot else demo()
        draw(state, args.tab).save(args.render)
        return
    collector, screen = Collector(debug=args.debug_touch), Framebuffer(args.framebuffer)
    touch, next_touch, next_sample, state = None, 0, 0, None
    tab = args.tab
    try:
        while True:
            now = time.monotonic()
            if not args.no_touch and (touch is None or touch.fd is None) and now >= next_touch:
                next_touch = now + 10
                try:
                    touch = Touch(args.touch_calibration, debug=args.debug_touch)
                except (OSError, ValueError, KeyError) as exc:
                    print('Touch unavailable:', exc, flush=True)
            if now >= next_sample:
                state = collector.sample()
                next_sample = time.monotonic() + 5
                screen.push(draw(state, tab, touch is not None and touch.fd is not None))
            try:
                taps = touch.poll(.1) if touch else (time.sleep(.1) or [])
                for x, y in taps:
                    selected = tab_at(x, y)
                    if selected and selected != tab:
                        if args.debug_touch:
                            print(f'Tab switched: {tab} -> {selected}', flush=True)
                        tab = selected
                        screen.push(draw(state, tab, True))
            except OSError as exc:
                print('Touch disconnected:', exc, flush=True)
                if touch:
                    touch.close()
    finally:
        if touch:
            touch.close()
        screen.close()


if __name__ == '__main__':
    main()
