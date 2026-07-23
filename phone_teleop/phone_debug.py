"""Diagnostic: what is the HEBI Mobile I/O phone actually streaming?
Run, then move the phone and press B1. Prints AR-pose availability + button states."""
import time
import hebi

lookup = hebi.Lookup()
time.sleep(2)  # let discovery run
group = lookup.get_group_from_names(["HEBI"], ["mobileIO"])
if group is None:
    print("NO GROUP FOUND — app not discovered. Check family=HEBI name=mobileIO, same network, firewall.")
    raise SystemExit

print(f"Connected: {group.size} module(s). Move the phone and press B1...\n", flush=True)
fbk = hebi.GroupFeedback(group.size)
i = 0
while True:  # run until Ctrl+C
    i += 1
    f = group.get_next_feedback(reuse_fbk=fbk)
    if f is None:
        print("feedback: None (no packet)")
        time.sleep(0.1); continue
    p = f[0]
    ar_pos = getattr(p, "ar_position", None)
    ar_quat = getattr(p, "ar_orientation", None)
    io = getattr(p, "io", None)
    b1 = None
    a3 = None
    if io is not None:
        try: b1 = io.b.get_int(1) if io.b.has_int(1) else (io.b.get_bool(1) if hasattr(io.b,'has_bool') and io.b.has_bool(1) else None)
        except Exception: b1 = "err"
        try: a3 = io.a.get_float(3) if io.a.has_float(3) else None
        except Exception: a3 = "err"
    has_ar = ar_pos is not None and ar_quat is not None
    if i % 10 == 0 or b1:
        print(f"AR_pose={'YES '+str([round(x,2) for x in ar_pos]) if has_ar else 'NO'}  | B1={b1}  A3={a3}")
    time.sleep(0.03)
print("\ndone.")
