# AN's right-leg GDI decline: observed, misattributed, resolved

Written 2026-08-31, after the fix that explains it. Recorded because the wrong explanation was
carried for a day and drove real work, and because the observation itself was the thread that led
to the largest defect found in this pipeline so far.

## What was observed

AN was the first participant processed end to end (15 trials, `ik` route, 2026-08-30). Scored
against the `reduced6` control reference, the **right leg fell monotonically across the session**:

    right   GDI r = -0.917    90.3 (first three trials) -> 71.9 (last three)    -18.4 points
    left    GDI r = +0.486    82.5 -> 86.9

Gait does not do that. Every trial is converted, calibrated and segmented independently, so
nothing carries between them inside the pipeline; a quantity that moves monotonically with trial
number is moving in the recording. And the asymmetry made it look diagnostic — fatigue, a
loosening pelvis strap or a global heading drift would move both legs together, so one side moving
alone pointed at that side's sensors.

## What it was attributed to, and why that was wrong

The reading was **hardware drift in AN's right-side sensors**. `session_drift.py` and
`raw_drift.py` were both built on the back of it, and `raw_drift.py` did find something real:
AN's right foot moved -9.9 degrees relative to the pelvis across the session, alongside +27.3
degrees of absolute pelvis heading drift (r = +0.896).

That explanation survived one day. It failed on 2026-08-30 when KM, MS and SB — carrying 10 to 36
degrees of *absolute* heading drift and no relative drift at all — alerted on **both** legs
(see `2026-08-30-drift-prediction.md`). A per-participant sensor fault cannot produce a
six-participant relationship, and |pelvis drift| against GDI change came out at r = -0.947,
about -0.72 points per degree.

The actual cause was in this repository, not in AN's sensors:
`compute_foot_progression_angles` derived its reference heading as
`arctan2(y_end - y_start, x_end - x_start)`. OpenSim's ground frame has Y vertical and walking
happens in X-Z, and this project's IMU route pins `pelvis_tx/ty/tz`, so the expression evaluated
`arctan2(0, 0) = 0` on every trial. FPA was therefore **absolute foot yaw in the lab frame**, not
a progression angle, and it inherited the session's heading wander directly. FPA is one of the six
variables in `reduced6`. Recorded as edit #15 in `VENDORING.md`; fixed in commit 16c78e8.

## The measurement that closes it

AN re-processed after the fix, and both versions scored with the same tool, the same reference
(`context/gdi_reference_2026-08-27`, `reduced6`) and the same 15 trials. The pre-fix curves are
preserved at `Data/xsens_sessions/XsensSession_AN/GaitCurves_pre-fpa-fix/`.

| | pre-fix | post-fix |
|---|---|---|
| right GDI trend | **r = -0.917**, 90.3 -> 71.9 (**-18.4**) | r = +0.270, 85.5 -> 87.4 (+1.9) |
| left GDI trend | r = +0.486, 82.5 -> 86.9 | r = +0.152, 87.7 -> 89.6 |
| right fpa drift | **+20.73 deg** (r = +0.873) | -6.51 deg (r = -0.715) |
| left fpa drift | **-27.94 deg** (r = -0.905) | **-0.70 deg** (r = -0.140) |

The decline is gone. Two details are worth more than the headline:

**Every non-FPA variable is numerically identical across the two runs** — hip_flexion -2.48,
hip_rotation -2.09, hip_adduction +1.25, knee_angle -0.36, ankle_angle -0.44 on the right, and the
same on the left. That is the internal check: the fix touched the reference heading and nothing
else, and the scores agree.

**The left foot's drift falls 97.5% while the right's only falls 69%.** That residual is the
relative drift `raw_drift.py` found independently in the raw `.mvnx` (-9.9 deg, right foot against
pelvis), and it should not have vanished — it is in the recording, not in the arithmetic. The fix
removed the common-mode artefact and left the genuine per-segment drift standing, which is the
behaviour the FPA reference was supposed to have all along.

Absolute level moved too, not just the trend: right first-three goes 90.3 -> 85.5. Pre-fix GDI
values are not merely mis-trended, they are wrong pointwise.

## What this invalidates

- **AN has no right-side sensor fault.** Any note, figure or message saying otherwise is wrong.
  The -18.4 point decline was this repository's own defect.
- **The same applies to KM, MS and SB.** Their alerts were the same artefact; they need the same
  before/after check once their re-runs finish. HH (-1.5 deg heading drift) was never affected
  either way.
- **`session_drift.py` is not invalidated — it worked.** It surfaced a real problem that nothing
  else in the pipeline would have caught, and its own warning ("a trend indicates a problem, not
  its cause") is exactly the caution that turned out to be needed. What changes is the prior: a
  GDI trend is now a software-defect suspect first and a hardware suspect second.
- Every FPA and GDI value produced before 2026-08-31 is invalid on both routes. That is stated in
  full in `VENDORING.md`, edit #15.

## The lesson worth keeping

The asymmetry was real and it was the reason the observation looked trustworthy — but it was
produced by `fpa_l = heading - euler_l` against `fpa_r = euler_r - heading`, a construction
artefact that makes the two feet move in opposite directions whenever the shared heading moves.
It was read as physical. A signed difference between two quantities computed from the same shared
term is not independent evidence about either of them.
