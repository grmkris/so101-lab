# lab-pi touchscreen dashboard

The robot Pi screen works after physically reseating its connection; this version adds overview system stats, and Kris needs to do nothing unless touch stops working again.

This is the 320×480 RGB565 touchscreen dashboard running on `lab-pi` (`kris@100.77.154.45`). It only reads system status and existing `/data/session.json` heartbeat reports. It does not open camera, serial, motor, or robot-control devices. The Cameras tab is unchanged from the deployed September 29 script.

## Installed files

- `/home/kris/labstatus.py`
- `/etc/systemd/system/labstatus.service` (unchanged unit copied into this directory)
- `/home/kris/labstatus-touch.json` (panel-specific calibration; not committed)

Python needs `numpy` and Pillow, already installed on the Pi. The service runs as root for framebuffer/input access, with `Nice=10`, idle I/O priority, and automatic restart. The script reads the ADS7846 by its **device name**, never by the `input_device` number stored in calibration: event numbers can change after a reboot. It never grabs the touch device.

## Overview

Temperature in °C (red above 70), CPU usage from successive `/proc/stat` samples, one-minute load, RAM used/total from `MemTotal` minus `MemAvailable`, root SD filesystem used/free space in GiB, uptime, and `vcgencmd get_throttled` (`OK` or a warning). System stats sample at most once every five seconds; the first CPU reading is unavailable until the second sample. Existing camera-session and motor-service status still explicitly do not imply motion readiness. With `--debug-touch`, one nonsecret stats sample prints after CPU sampling warms up, and each actual tab change prints `Tab switched: old -> new`.

The sampler, power-warning labels and two-column renderer are reused from `phone-caller-sim/pi/rootfs/opt/phone-lab/pistats.py`. The local snapshot and embedded copy add one defensive `ValueError`/`IndexError` guard around transient `/proc/stat` parsing; an AST-equivalence regression test keeps the copies aligned. Both dashboards use the exact same stats layout, dark palette and four-tab navigation. Only the single bundled `labstatus.py` is installed on the robot Pi.

## Existing boot configuration (reference only)

```ini
dtparam=spi=on
dtoverlay=fbtft,spi0-0,ili9486,regwidth=16,reset_pin=25,dc_pin=24,speed=16000000,rotate=0,fps=30,txbuflen=32768
dtoverlay=ads7846,cs=1,penirq=17,penirq_pull=2,speed=2000000,xohms=60,pmax=255
```

Do not alter overlays or reboot a Pi hosting the arm without coordination and explicit authorization. Installing this dashboard requires only backing up/replacing the script and restarting **`labstatus.service`**. The unit and calibration are unchanged in this rollout.

## Recalibrate only if mapped taps are wrong

No recalibration was needed on September 30: existing measured taps mapped to Cameras, System and Overview after reseating. To recalibrate later, coordinate with the bench operator, ask them to tap the four targets in order, and stop only the screen service to prevent two framebuffer writers:

```sh
sudo sh -c '
set -eu
test -e /home/kris/labstatus-touch.json.bak-20260930 || cp -p /home/kris/labstatus-touch.json /home/kris/labstatus-touch.json.bak-20260930
trap "systemctl start labstatus.service" EXIT
systemctl stop labstatus.service
/usr/bin/python3 /home/kris/labstatus.py --calibrate --touch-calibration /home/kris/labstatus-touch.json
'
```

Calibration waits up to 45 seconds per target, rejects degenerate/inconsistent measurements, and leaves the existing JSON unchanged if a target times out or validation fails. A successful set is atomically replaced and followed by a completion screen. `--calibrate` is an attended maintenance mode; never add it to the permanent service command. If no events arrive, recalibration cannot repair a disconnected touch path.

## Photo-free checks

```sh
systemctl is-active labstatus
journalctl -u labstatus -n 40 --no-pager
grep -i ads7846 /proc/interrupts
pinctrl get 17
ls -l /dev/input/by-path/platform-fe204000.spi-cs-1-event
sha256sum /dev/fb0
```

A registered input device alone does not prove touch. Require real operator taps, rising IRQ counts, a mapped-tab log line, and a framebuffer change correlated with that tab change. During the fault, ADS7846 existed but an independent reader received zero events for 180 seconds; the interrupt count was stuck at 1 and idle GPIO17 was high. The overlay matched the working phone Pi. Kris reseated/replugged the screen and removed the protector, then rebooted it himself. Which physical contact or protector detail caused the fault is not isolated; the agent did not reboot or rebind the driver.

## Offline tests

From this directory, with numpy and Pillow installed:

```sh
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 labstatus.py --render overview.png
```

Tests mock device access and cover dynamic name-based discovery, calibration metadata not pinning an event number, released-tap and dropped-event handling, navigation geometry, RAM/root-disk/CPU calculations, one-shot stats logging, all tab rendering, temperature/throttle warnings, and calibration timeout cleanup. Run expensive checks on the dev box through `heavy`.
