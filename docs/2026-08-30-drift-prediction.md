# Pre-registered prediction: does common-mode heading drift reach the results?

Written 2026-08-30, **before** the relevant data finished processing. Recorded in advance so it
is a test rather than something reconciled after the fact.

## The claim under test

Heading drift shared by every segment should **cancel out of joint angles**, because joint angles
are relative. Only a segment drifting *differently from its parent* should reach a score.

That claim is currently supported by three participants, but two of them are the cases the claim
was built from, so they cannot test it.

## What the raw check says, before processing

From `raw_drift.py`, `.mvnx` only, no pipeline involved:

| participant | absolute pelvis heading | relative drift | processed yet? |
|---|---|---|---|
| AN | +27.3 deg (r +0.896) | **yes** — right foot -9.9 deg vs pelvis | yes |
| CK | +4.7 deg | **yes** — right hip flexion -6.2 deg | yes |
| HH | -1.5 deg | no | yes |
| KM | **-20.3 deg** (r -0.985) | no | **not yet** |
| MS | **-36.1 deg** (r -0.950) | no | **not yet** |
| SB | **-10.6 deg** (r -0.993) | no | **not yet** |

## The prediction

**KM, MS and SB will show no meaningful GDI trend across their sessions**, despite carrying 10 to
36 degrees of monotonic pelvis heading drift at correlations of 0.95 to 0.99 — larger, in MS's
case, than the participant whose score fell 18 points.

Operationally: `session_drift.py` should raise no alert for any of the three, i.e. |r| < 0.8 or a
GDI change under 5 points on both legs.

## What each outcome means

- **All three clean.** The claim holds on data it was not derived from. Absolute heading drift is
  then a recording-quality note rather than a data-validity problem, and the cheap `.mvnx` check
  is a sufficient pre-flight: relative drift is the only thing worth blocking on.
- **Any of them shows a trend.** The claim is wrong or incomplete, the pre-flight check has a
  false negative, and MS in particular (-36 deg) would suggest absolute drift reaches the results
  above some magnitude the current thresholds do not capture.

A partial result — say MS alerting while KM and SB stay clean — would point at a magnitude
threshold rather than a clean yes/no, and would be more informative than either extreme.

## Why this is worth pinning down

The pre-flight check costs seconds and the full pipeline costs about an hour per participant. If
absolute drift can be dismissed, sessions can be triaged before processing rather than after. If
it cannot, every session with heading drift needs full processing before it can be trusted, and
four of the six here have it.

---

# Outcome, recorded 2026-08-30 after processing finished

**The prediction was wrong.** All three test participants alerted, on both legs.

| participant | pelvis drift | GDI right | GDI left | predicted |
|---|---|---|---|---|
| KM | -20.3 deg | **-12.8** (r -0.991) | **-15.1** (r -0.993) | clean |
| MS | -36.1 deg | **-29.6** (r -0.967) | **-32.2** (r -0.979) | clean |
| SB | -10.6 deg | **-12.8** (r -0.995) | **-9.2** (r -0.969) | clean |

## Why the claim failed

Common-mode heading drift *does* cancel out of parent-child joint angles -- hip, knee and ankle
are quiet in every participant. It does **not** cancel out of foot progression angle, because FPA
is referenced to the direction of progression rather than to a parent segment, so pelvis heading
drift enters it directly. And FPA is one of the six variables in `reduced6`, the scored default.

Across all six participants:

| | pelvis drift | fpa right | fpa left | GDI right |
|---|---|---|---|---|
| AN | +27.3 | +20.7 | -27.9 | -18.4 |
| CK | +4.7 | +3.4 | -3.8 | -7.5 |
| HH | -1.5 | -1.4 | +2.7 | +0.7 |
| KM | -20.3 | -15.3 | +15.4 | -12.8 |
| MS | -36.1 | -26.6 | +31.8 | -29.6 |
| SB | -10.6 | +9.7 | -9.0 | -12.8 |

**|pelvis drift| against GDI change: r = -0.947, about -0.72 points per degree.** SB was predicted
at -9.0 points from its -10.6 degrees and came in at -12.8.

The two feet move in opposite directions, which is the fingerprint of the pelvis rotating between
them rather than the feet moving. That holds in five of six; **SB is an exception** -- its right
FPA takes the same sign as the pelvis drift where the other five take the opposite. The magnitude
relationship is robust; the signed one is not universal, and SB is unexplained.

## Consequences

- **The GDI scores for AN, KM, MS and SB are substantially measuring heading drift, not gait.** A
  per-participant mean is an average over a ramp.
- `raw_drift.py`'s "absolute heading drift only -- mostly cancels" verdict is a **false negative**
  whenever FPA is scored. It should predict damage at ~0.72 points per degree instead.
- Only HH (-1.5 deg) is clean enough for its scores to be read as gait.
- The open question is not a threshold: it is whether FPA belongs in the scored set given this
  pipeline's heading behaviour. That changes what every number in the study means.
