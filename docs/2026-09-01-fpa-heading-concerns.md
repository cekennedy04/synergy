# Open concerns: the FPA reference heading, and what it touches

Raised 2026-09-01, after edit #15 (see `VENDORING.md` for the full provenance record and the
measurements behind it). This is the list to walk through with whoever maintains the upstream
`getpelvis` / `gaitAnalysis` code — several of these are questions only they can answer, and two
are defects that exist independently of this repository.

## The defect

`getpelvis` establishes the direction the subject walked, then expresses each foot's angle relative
to it:

```python
x2, x1 = mean(direction[-4:, 0]), mean(direction[0:4, 0])   # X - forward
y2, y1 = mean(direction[-4:, 1]), mean(direction[0:4, 1])   # Y - VERTICAL
heading = degrees(arctan2([y2 - y1], [x2 - x1]))[0]
```

OpenSim's ground frame is X forward, **Y vertical**, Z lateral; walking happens in X-Z. As written
this measures forward travel against vertical bounce, so foot progression angle has never been
referenced to the direction of travel.

It survived review because the result is always close to zero, and close to zero is
*approximately* correct whenever a subject walks straight along +X.

---

## 1. The heading uses the vertical axis (defect, upstream)

Fix is `arctan2(dz, dx)`. Measured on ten OpenCap trials where the pelvis genuinely travels ~6 m:
mean error **5.26 degrees**, maximum **6.55**. The vertical term is ~8 cm of body sway against 6 m
of travel.

## 2. It affects the upstream OpenCap results too (defect, upstream)

Not confined to this project's IMU route. Every FPA value produced by that code carries roughly the
subject's own walking angle as a bias. Worth raising as *their* correction, not ours.

## 3. Under a pinned root it degenerates completely (defect, here)

Orientation-only IK leaves `pelvis_tx/ty/tz` exactly constant (measured range `0.00e+00`), so the
expression evaluates `arctan2(0, 0) = 0` on every trial. FPA then is not a progression angle at
all: it is absolute foot yaw in the lab frame, which tracks the orientation estimate's heading
drift directly.

## 4. The measured consequence

Across six participants, `|pelvis heading drift|` predicts the within-session change in GDI at
**r = -0.947, about -0.72 points per degree**. Four of six sessions carry 10-36 degrees of drift.
For those participants most of the within-session score movement was the sensors rather than the
subject.

## 5. The repair is deliberately narrow

Only the heading changed: ground-plane `arctan2(dz, dx)`, with a fallback to the circular mean of
pelvis yaw when displacement is under 10 cm. Preserved unchanged, because they are conventions
rather than errors: the `+/-5` degree foot offsets, the mirrored left/right sign
(`fpa_l = heading - euler_l`), one scalar heading per trial, the Euler `xyz` component, and FPA's
membership of the GDI feature set.

## 6. It does not flatten the data — the strongest evidence it is correct

| participant | GDI drift before (R / L) | after (R / L) |
|---|---|---|
| AN | -18.4 / +4.4 | +1.9 / +1.9 |
| CK | -7.5 / -3.7 | -4.5 / -5.8 |
| HH | +0.7 / -2.3 | +1.5 / +0.0 |
| KM | -12.8 / -15.1 | -2.4 / -4.2 |
| MS | -29.6 / -32.2 | **-15.5** / +2.2 |
| SB | -12.8 / -9.2 | -0.2 / +0.7 |

CK's drift is driven by hip flexion, visible in Xsens's own `jointAngle` output at r = -0.951, and
the fix leaves it untouched to two decimal places. MS's right leg retains -15.5 points, and its
right foot genuinely diverges from the pelvis by ~6 degrees in the raw recording. A change that had
cleaned those up as well would have meant real signal was being flattened.

Lead with this one if the defect is disputed: a fix that improved every number would be the
suspicious outcome.

## 7. Scores rose after the fix

Previous per-participant means were averages taken over a drift ramp, so several participants were
scored several points low. Any GDI value produced before 2026-08-31 should be regarded as
superseded; pre-fix curve exports are retained per session as `GaitCurves_pre-fpa-fix/`.

---

## Questions only the upstream author can answer

## 8. What do the `+/-5` degree foot offsets encode?

`euler_r - 5` and `euler_l + 5`, applied to the whole Euler triple before the component is taken.
No derivation found anywhere in the supplied code or notes. Preserved without understanding them.
If they encode marker or segment placement, it belongs in writing somewhere.

## 9. Does anything downstream assume the old near-zero heading?

If any later step was tuned against FPA values produced under the broken heading, correcting it
here will shift those results too.

---

## Unrelated observations worth passing on

## 10. `AnalyzeTool` is run but its output is never read

`getpelvis` constructs an `osim.AnalyzeTool`, sets a coordinates file, calls `run()` — and then
recomputes everything itself from the `.mot`. Measured at ~17 s per trial, roughly a quarter of the
per-trial pipeline cost, with no observable use. Left in place in case it has a side effect not
apparent from reading it.

## 11. An intermittent native crash with no Python traceback

Trials occasionally die with exit `3221226505` (`STATUS_STACK_BUFFER_OVERRUN`). It is **not**
tied to particular trials: a trial that crashed in one run completed in the next. Trials now run in
their own process so a crash costs one trial rather than the batch, but the cause is unknown. Worth
asking whether it has been seen upstream.
