"""Small, dependency-free Raspberry Pi health sampler for local dashboards."""
import re
import os
import subprocess
from pathlib import Path


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
            # guest/guest_nice are already counted in user/nice (Linux proc_stat).
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
