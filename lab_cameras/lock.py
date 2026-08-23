"""Freeze the cameras' optics, and record what they were frozen to.

Autofocus, auto-exposure and auto-white-balance make a rig unreproducible: the
homography is only valid at a fixed focus, and hard-won lever #2 is that a
policy trained at one brightness fails at another. macOS never exposed these
controls; Linux does, which is half the reason the room host exists.

    python -m lab_cameras.lock show     # what the cameras are doing right now
    python -m lab_cameras.lock apply    # let auto settle, then freeze it there
    python -m lab_cameras.lock apply --install-service   # ...and survive replug
    python -m lab_cameras.lock rig-json # write /data/rig.json provenance

`apply` deliberately does not invent values: it streams for a few seconds, reads
what the camera's own auto modes settled on under the working lamp, and pins
those. Do it once, with the camera in its final position and the lighting set.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from lab_cameras.owner import DEFAULT_CAMERAS, CameraOwner

RIG_JSON = os.environ.get("LAB_RIG_JSON", "/data/rig.json")
SERVICE = "/etc/systemd/system/labcam-lock.service"
LOCK_SCRIPT = "/usr/local/bin/labcam-lock"

MAINS_HZ = int(os.environ.get("LAB_MAINS_HZ", "50"))
PLF = {50: 1, 60: 2}[MAINS_HZ]


def _v4l2(dev: str, *args) -> str:
    out = subprocess.run(["v4l2-ctl", "-d", dev, *args], capture_output=True, text=True, timeout=15)
    return out.stdout


def _set(dev: str, ctrl: str, value) -> None:
    subprocess.run(["v4l2-ctl", "-d", dev, "--set-ctrl", f"{ctrl}={value}"], capture_output=True)


def controls(dev: str) -> dict:
    """Parse `v4l2-ctl -l` into {name: {value, min, max, inactive}}."""
    out = {}
    for line in _v4l2(dev, "-l").splitlines():
        if "0x" not in line or ":" not in line:
            continue
        name = line.split()[0]
        body = line.split(":", 1)[1]
        rec = {}
        for tok in body.replace(",", " ").split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                rec[k] = int(v) if v.lstrip("-").isdigit() else v
        rec["inactive"] = "inactive" in body
        out[name] = rec
    return out


def _measure(name: str, cams: CameraOwner, n: int = 4, settle: float = 0.45) -> dict:
    """Mean brightness, channel means and a sharpness score, averaged over n frames."""
    import cv2
    import numpy as np

    time.sleep(settle)  # UVC needs a few frames for a control change to appear
    b = g = r = sharp = 0.0
    seen = set()
    for _ in range(n * 4):
        f = cams.latest(name, max_age_ms=3000)
        if f.seq in seen:
            time.sleep(0.02)
            continue
        seen.add(f.seq)
        m = f.bgr.reshape(-1, 3).mean(axis=0)
        b += m[0]; g += m[1]; r += m[2]
        sharp += cv2.Laplacian(cv2.cvtColor(f.bgr, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        if len(seen) >= n:
            break
    k = max(1, len(seen))
    return {"mean": (b + g + r) / (3 * k), "b": b / k, "g": g / k, "r": r / k, "sharp": sharp / k}


def brightness(name: str, cams: CameraOwner) -> float:
    """Mean frame brightness — the number that makes a lighting note comparable."""
    return round(_measure(name, cams, n=3, settle=0.1)["mean"], 1)


def _hill(dev, ctrl, lo, hi, step, score, log):
    """Coarse sweep for the best control value. Deliberately not a binary search:
    focus sharpness is not monotonic, and neither is exposure once a highlight
    clips."""
    best, best_s = None, None
    v = lo
    while v <= hi:
        _set(dev, ctrl, v)
        s = score()
        log.append((v, round(s, 2)))
        if best_s is None or s > best_s:
            best, best_s = v, s
        v += step
    _set(dev, ctrl, best)
    return best, best_s


def _tune_exposure(name, dev, cams, ctl, target, log) -> int | None:
    """Pin exposure to whatever matches the brightness auto-mode was producing.

    Reading the auto-chosen value back does not work: UVC reports the *default*
    with the control marked inactive (measured — the C922 says 250 whatever the
    room looks like). So match the picture, not the register.
    """
    spec = ctl.get("exposure_time_absolute")
    if not spec:
        return None
    lo, hi = max(1, spec.get("min", 1)), spec.get("max", 2047)
    _set(dev, "auto_exposure", 1)  # manual — from here the picture is ours to match
    # geometric ladder: exposure is multiplicative in its effect on brightness
    cands, v = [], lo
    while v <= hi:
        cands.append(int(v))
        v *= 1.35
    best, best_err = None, None
    for v in cands:
        _set(dev, "exposure_time_absolute", v)
        got = _measure(name, cams, n=2)["mean"]
        log.append((v, round(got, 1)))
        err = abs(got - target)
        if best_err is None or err < best_err:
            best, best_err = v, err
        if got > target * 1.6 and best_err < target * 0.05:
            break  # well past the target and already close enough
    _set(dev, "exposure_time_absolute", best)
    return best


def _tune_wb(name, dev, cams, ctl, ref, log) -> int | None:
    """Pin white balance to the temperature whose colour cast matches auto's."""
    spec = ctl.get("white_balance_temperature")
    if not spec:
        return None
    lo, hi = spec.get("min", 2800), spec.get("max", 6500)
    _set(dev, "white_balance_automatic", 0)
    target = ref["b"] - ref["r"]
    best, best_err = None, None
    for v in range(lo, hi + 1, max(100, (hi - lo) // 12)):
        _set(dev, "white_balance_temperature", v)
        m = _measure(name, cams, n=2)
        err = abs((m["b"] - m["r"]) - target)
        log.append((v, round(m["b"] - m["r"], 1)))
        if best_err is None or err < best_err:
            best, best_err = v, err
    _set(dev, "white_balance_temperature", best)
    return best


def _tune_focus(name, dev, cams, ctl, log) -> int | None:
    """Maximise sharpness, then never move again.

    This is the control that matters most: a homography and any intrinsics are
    only valid at one focus, so autofocus quietly invalidates every calibration
    the moment something enters the frame.
    """
    spec = ctl.get("focus_absolute")
    if not spec or "focus_automatic_continuous" not in ctl:
        return None
    _set(dev, "focus_automatic_continuous", 0)
    lo, hi = spec.get("min", 0), spec.get("max", 250)
    step = max(spec.get("step", 5), (hi - lo) // 25)
    best, _ = _hill(dev, "focus_absolute", lo, hi, step,
                    lambda: _measure(name, cams, n=2)["sharp"], log)
    # refine around the peak
    fine = max(spec.get("step", 5), step // 4)
    best, _ = _hill(dev, "focus_absolute", max(lo, best - step), min(hi, best + step), fine,
                    lambda: _measure(name, cams, n=2)["sharp"], log)
    return best


def freeze_one(name: str, dev: str, settle: float, cams: CameraOwner) -> dict:
    """Let the camera's own auto modes settle, measure the picture they produce,
    then reproduce that picture with every control pinned.

    ORDER MATTERS, and getting it wrong is silent:

    1. focus while auto-exposure is still ON — otherwise the sharpness metric is
       measuring a dark frame, not a blurry one;
    2. **gain before exposure** — the C922's auto-exposure drives gain internally
       and reports `gain=0` the whole time, so pinning gain afterwards throws away
       most of the light. Measured: it took a matched 104.7 mean down to 21.2.
    3. exposure, matched to the brightness auto was producing;
    4. white balance, matched to the colour cast auto was producing;
    5. re-measure and re-tune exposure once if anything drifted.
    """
    ctl = controls(dev)
    _set(dev, "power_line_frequency", PLF)
    time.sleep(settle)                      # auto exposure/WB/focus converge on live frames
    ref = _measure(name, cams, n=5, settle=0.5)
    print(f"  auto reference: mean={ref['mean']:.1f} b-r={ref['b']-ref['r']:+.1f} "
          f"sharp={ref['sharp']:.0f}", flush=True)

    sweeps: dict = {}
    locked = {"power_line_frequency": PLF}

    log: list = []
    foc = _tune_focus(name, dev, cams, ctl, log)
    if foc is not None:
        locked["focus_automatic_continuous"] = 0
        locked["focus_absolute"] = foc
        sweeps["focus"] = log
        print(f"  focus  -> {foc}", flush=True)

    if "gain" in ctl:
        locked["gain"] = ctl["gain"].get("value", 0)
        _set(dev, "gain", locked["gain"])

    log = []
    exp = _tune_exposure(name, dev, cams, ctl, ref["mean"], log)
    if exp is not None:
        locked["auto_exposure"] = 1
        locked["exposure_time_absolute"] = exp
        sweeps["exposure"] = log
        print(f"  expo   -> {exp}", flush=True)

    log = []
    wb = _tune_wb(name, dev, cams, ctl, ref, log)
    if wb is not None:
        locked["white_balance_automatic"] = 0
        locked["white_balance_temperature"] = wb
        sweeps["white_balance"] = log
        print(f"  wb     -> {wb}", flush=True)

    final = _measure(name, cams, n=5, settle=0.6)
    if exp is not None and abs(final["mean"] - ref["mean"]) > 0.1 * max(ref["mean"], 1):
        print(f"  drifted to {final['mean']:.1f} after WB — retuning exposure", flush=True)
        log = []
        exp = _tune_exposure(name, dev, cams, ctl, ref["mean"], log)
        locked["exposure_time_absolute"] = exp
        sweeps["exposure_retune"] = log
        final = _measure(name, cams, n=5, settle=0.6)

    after = controls(dev)
    mismatch = {k: (v, after.get(k, {}).get("value"))
                for k, v in locked.items() if after.get(k, {}).get("value") != v}
    return {
        "device": dev,
        "real_device": os.path.realpath(dev),
        "locked": locked,
        "readback_mismatch": mismatch,
        "auto_reference": {k: round(v, 1) for k, v in ref.items()},
        "after_lock": {k: round(v, 1) for k, v in final.items()},
        "mean_brightness": round(final["mean"], 1),
        "brightness_error_pct": round(100 * (final["mean"] - ref["mean"]) / max(ref["mean"], 1), 1),
        "sweeps": sweeps,
    }


def cmd_show(args) -> int:
    with CameraOwner(mode="lock-show") as cams:
        time.sleep(2.0)
        for name, dev in DEFAULT_CAMERAS.items():
            c = controls(dev)
            m = _measure(name, cams, n=4)
            print(f"\n=== {name}  {dev}  mean={m['mean']:.1f}  sharp={m['sharp']:.0f}")
            for k in ("power_line_frequency", "auto_exposure", "exposure_time_absolute",
                      "gain", "white_balance_automatic", "white_balance_temperature",
                      "focus_automatic_continuous", "focus_absolute"):
                if k in c:
                    flag = " (inactive — camera is in auto)" if c[k].get("inactive") else ""
                    print(f"  {k:<32} {c[k].get('value')}{flag}")
    return 0


def cmd_apply(args) -> int:
    result = {}
    with CameraOwner(mode="lock-apply") as cams:
        for name, dev in DEFAULT_CAMERAS.items():
            print(f"\n=== {name}  {dev}", flush=True)
            r = freeze_one(name, dev, args.settle, cams)
            result[name] = r
            print(f"  locked: " + "  ".join(f"{k}={v}" for k, v in r["locked"].items()))
            print(f"  after lock:     mean={r['after_lock']['mean']:.1f} "
                  f"(auto was {r['auto_reference']['mean']:.1f})  "
                  f"sharp={r['after_lock']['sharp']:.0f} "
                  f"(auto was {r['auto_reference']['sharp']:.0f})")
            if r["readback_mismatch"]:
                print(f"  ⚠ did NOT take: {r['readback_mismatch']}")
        rig = write_rig_json(cams, result)
    print(f"\nwrote {RIG_JSON}")
    if args.install_service:
        install_service(result)
    return 1 if any(r["readback_mismatch"] for r in result.values()) else 0


def write_rig_json(cams: CameraOwner, locks: dict | None = None) -> dict:
    """Provenance: what makes two datasets comparable, and a calibration valid."""
    try:
        import lerobot
        lerobot_version = lerobot.__version__
    except Exception:
        lerobot_version = "unknown"
    existing = {}
    if os.path.exists(RIG_JSON):
        try:
            existing = json.loads(Path(RIG_JSON).read_text())
        except Exception:
            pass
    doc = {
        **existing,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": os.uname().nodename,
        "lerobot": lerobot_version,
        "resolution": [cams.width, cams.height],
        "fps": cams.fps,
        "fourcc": {n: s.fourcc for n, s in cams.stats.items()},
        "cameras": {n: {"path": d, "real": os.path.realpath(d)}
                    for n, d in cams.cameras.items()},
        "mean_brightness": {n: brightness(n, cams) for n in cams.names()},
        "mains_hz": MAINS_HZ,
    }
    if locks:
        doc["locked_controls"] = {n: r["locked"] for n, r in locks.items()}
    Path(RIG_JSON).parent.mkdir(parents=True, exist_ok=True)
    Path(RIG_JSON).write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def cmd_rig_json(args) -> int:
    with CameraOwner(mode="rig-json") as cams:
        time.sleep(1.5)
        doc = write_rig_json(cams)
    print(json.dumps(doc, indent=2))
    return 0


def install_service(locks: dict) -> None:
    """Make the lock survive reboot and replug.

    A shell snippet in a notes file is a lock you forget to apply; a service is
    one you cannot.
    """
    lines = ["#!/bin/sh", "# generated by `python -m lab_cameras.lock apply --install-service`",
             "# re-run that command to change these values -- do not hand-edit.", "set -e", ""]
    for name, r in locks.items():
        lines.append(f"# {name}")
        lines.append(f'if [ -e {r["device"]} ]; then')
        for ctrl, value in r["locked"].items():
            lines.append(f'  v4l2-ctl -d {r["device"]} --set-ctrl {ctrl}={value} || true')
        lines.append("fi")
    script = "\n".join(lines) + "\n"
    unit = f"""[Unit]
Description=Freeze SO-101 lab camera optics (exposure/WB/focus/mains)
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={LOCK_SCRIPT}

[Install]
WantedBy=multi-user.target
"""
    tmp_s, tmp_u = "/tmp/labcam-lock.sh", "/tmp/labcam-lock.service"
    Path(tmp_s).write_text(script)
    Path(tmp_u).write_text(unit)
    if shutil.which("sudo") is None:
        print(f"no sudo; wrote {tmp_s} and {tmp_u} — install them by hand")
        return
    subprocess.run(["sudo", "install", "-m", "755", tmp_s, LOCK_SCRIPT], check=True)
    subprocess.run(["sudo", "install", "-m", "644", tmp_u, SERVICE], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now", "labcam-lock.service"], check=True)
    print(f"installed {LOCK_SCRIPT} + {SERVICE} (enabled)")


def main() -> int:
    ap = argparse.ArgumentParser(prog="lab_cameras.lock")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    p = sub.add_parser("apply")
    p.add_argument("--settle", type=float, default=6.0,
                   help="seconds of streaming before reading what auto chose")
    p.add_argument("--install-service", action="store_true")
    p.set_defaults(fn=cmd_apply)
    sub.add_parser("rig-json").set_defaults(fn=cmd_rig_json)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
