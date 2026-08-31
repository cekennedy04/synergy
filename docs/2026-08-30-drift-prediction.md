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
