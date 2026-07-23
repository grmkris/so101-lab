"""Check exactly how B1 is exposed. Hold B1 while this runs."""
import time, hebi
lk = hebi.Lookup(); time.sleep(2)
g = lk.get_group_from_names(["HEBI"], ["mobileIO"])
fbk = hebi.GroupFeedback(g.size)
print("hold B1 now...", flush=True)
for _ in range(150):
    f = g.get_next_feedback(reuse_fbk=fbk)
    if f is None: time.sleep(0.05); continue
    b = f[0].io.b
    hi = b.has_int(1); hb = getattr(b,'has_bool',lambda x:False)(1)
    gi = b.get_int(1) if hi else None
    gb = b.get_bool(1) if hb else None
    if gi or gb:
        print(f"has_int(1)={hi} get_int(1)={gi} | has_bool(1)={hb} get_bool(1)={gb}", flush=True)
    time.sleep(0.05)
print("done", flush=True)
