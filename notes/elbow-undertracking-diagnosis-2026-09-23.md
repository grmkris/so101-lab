# Elbow under-tracking diagnosis — 2026-09-23

This is a diagnosis from saved commissioning ledgers, deployed-source snapshots and offline tests. No motion, contact trial, gain/limit/calibration write, completion-guard change or provider call was made during this diagnosis. The arm remains stationary while physical camera repositioning is awaiting Kris's confirmation.

## Evidence

- The isolated elbow-only request changed the target by 1.6 degrees over 1.142857 seconds. It moved 0.7912088 degrees and failed at a residual of 0.8087912 degrees (`ea3781a9-7a13-4d0e-9387-088a2aa02a76`). The target was 54.356044 degrees and the measured elbow was 55.164835 degrees.
- A fresh read-only snapshot 49.3 minutes later had the same measured elbow, commanded target and operation ID. There was no fault or operator, cameras were fresh, and the maximum servo temperature was 42 C. Waiting longer therefore has no evidence as a fix; the motor owner holds the failed command and does not retry or rebase it.
- The deployed 4095-count/revolution conversion truncates this target to 54.285714 degrees. That accounts for about 0.07033 degrees, while the measured position remains ten raw counts from the encoded goal. Quantization is only a small part of the miss.
- Historical loaded traces are pose and direction dependent: on 2026-09-17 P32 moved 0.000 degrees, P48 left 0.833 degrees and P64 left 0.393 degrees; on 2026-09-18, a different working pose had P96 residuals of 0.042 degrees outward and 0.264 degrees returning. The deployed elbow profile remains P96, max step 2 degrees and max speed 2 degrees/second.
- The checkout and deployed engine are AST-equivalent. The offline saved-evidence test file passes 6 tests; selected engine safety tests pass 5 tests. These cover the measured terminal snapshot, held-joint judging, stale-camera cancellation, timeout cleanup, conversion rounding and a persistent plateau. The saved ordinary observations do not include raw current/load/voltage, so they cannot distinguish load/friction from trajectory timing.

## Decision and next diagnostic

Do not change P96, limits, calibration or the 0.8 degree completion guard. Do not repeat the failed motion or run the historical `servo_step_trace.py` unchanged: it is a sole-owner trace that writes P and restores a goal in `finally`, so it is not a passive readback.

After Kris confirms the physical camera move and releases the hardware hold:

1. Take a **zero-motion raw register/readback snapshot through the sole motor-owner path**: goal, present position, P/I/D, current, load, voltage, temperature, boot ID and clock. Do not create a second bus owner or write a gain.
2. If that snapshot is healthy, run one attended isolated elbow step at the existing P96 in the raised pose, with raw position/current/load/voltage/temperature sampled and a strict 60 C stop. Stop at the first failed settle; do not automatically replay or return after failure, and keep the exact start hold.
3. Interpret high current/load or voltage sag as a reviewed hardware/gain investigation. Interpret low-load settled servo data with a coordinator miss as duration/trajectory/driver analysis. No table contact is part of this diagnostic.

## Commissioning prerequisites

The final camera framing must be confirmed and frozen. Elbow behavior must be explained by the bounded raw-telemetry diagnostic, and a reachable raised home must return repeatably using measured joint outcomes. Only then measure the TCP with guarded first-contact stopping, touch distributed mat points, fit a nine-point workspace homography with held-out error under about 1 cm, and record/review the safe polygon and home. Keep Cartesian/live admission disabled until those values are reviewed. Run three watched reset smokes and one watched trial per available model before enabling scored trials or the provider-agnostic visual operator.

Private evidence: `robo-harness/var/elbow-diagnosis-2026-09-23/`.
