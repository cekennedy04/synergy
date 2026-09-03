# Subject-level triage of the six-session cohort

Written 2026-09-03, after audit section 13 refuted the uniform pipeline offset and moved the open
questions from the scale to individual sessions. Three sessions were flagged by
`validate_control_baseline.py`: CK (84.30), AN (86.64) and MS (98.31 pooled, on a 13.44-point
inter-leg gap). Verdicts quoted here predate the 2026-09-03 move to interval-based bands; CK and KM
are now INCONCLUSIVE rather than placed, which does not change the per-trial findings below.

The question for each was the same: **impairment, or a tracking artefact?** Per-trial scores answer
it better than session means do, because an artefact usually has a shape in trial order and
impairment does not.

## Finding 1: three sessions are still drifting within the session

`session_drift.py`, run against `context/gdi_reference_2026-08-27`:

    session  side    trials   GDI trend        first -> last
    MS       right      15    r = -0.840       99.4 -> 83.8    ALERT
    CK       right      15    r = -0.866       86.4 -> 81.8
    KM       left       15    r = -0.788       95.8 -> 91.0
    CK       left       15    r = -0.413       89.7 -> 83.8
    KM       right      15    r = -0.406       88.7 -> 86.3
    AN       right      15    r = +0.269       85.6 -> 87.6
    AN       left       15    r = +0.149       87.9 -> 89.8
    HH       both       15    r = +0.07/+0.13  flat
    SB       both       15    r = +0.04/+0.16  flat

`docs/2026-08-31-an-gdi-decline.md` established what a monotonic fall across trials means: *"Gait
does not do that. Every trial is converted, calibrated and segmented independently, so nothing
carries between them inside the pipeline; a quantity that moves monotonically with trial number is
moving in the recording."*

**AN is now clean** (+0.269 / +0.149). The decline that document was written about is fixed. Its
current 86.64 is a *stable* low reading, which is the one profile here most consistent with a
genuine subject characteristic rather than an artefact.

## Finding 2: MS's asymmetry is drift on one leg, not asymmetric pathology

This is the answer to the triage question about MS's 13.44-point gap.

    MS left    103.4 -> 105.6    r = +0.329    stable
    MS right    99.4 ->  83.8    r = -0.840    ALERT, -15.6 points

The two legs do not differ by a constant. The right leg **starts at 99.4**, within a point of the
left, and falls 15.6 points across the session. A unilateral calibration offset would be present in
trial 1; this is not.

`session_drift.py` names the cause: *"largest variable movement is fpa (+9.36 deg)"* — the FPA
heading defect already documented in the README, which it puts at up to 30 GDI points within one
session. So MS's asymmetry is a known defect expressing itself on one side, not an asymmetric gait
pattern, and it should not be read clinically.

## Finding 3: CK is a mixture, and KM was not flagged but should be watched

**CK** shows the same signature (right r = -0.866, 86.4 -> 81.8) below the magnitude gate that
alerts on MS. But CK's left leg *starts* at 89.7, so drift alone does not explain the session: some
of the deficit is present from trial 1. CK is the one session where "impairment or artefact" is
genuinely both, and the drift has to be dealt with before the residual can be read.

**KM** pooled 90.96 and scored SOUND, yet its left leg falls 95.8 -> 91.0 (r = -0.788) — a stronger
trend than either of CK's. It was not flagged because the pooled mean is comfortable. Worth
recording that a clean verdict from `validate_control_baseline.py` does not imply a clean session:
that tool answers "does this session read normal", and `session_drift.py` answers "is it stable".
They are different questions and both are worth asking.

## Finding 4: trial index 8 is low in more sessions than the CK-008 record suggests

`VENDORING.md` records the anomaly as `Trial8` / `CK-008`, participant-specific, with the
magnetic-drift hypothesis marked untestable from the available exports. Across the cohort it is
broader than that. Deviation of trial 8 from each session/side's own median:

    CK    left   -18.69      MS    right  -12.60
    MS    left   -10.32      AN    left    -8.68
    HH    left    -4.85      HH    right   -3.10
    AN    right   -2.07      CK    right   +0.00
    KM    left    +2.80      KM    right   +2.69
    SB    left    +1.75      SB    right   +0.78

Low in **7 of 12 session-sides, spanning 4 of 6 participants**. KM and SB are unaffected, so this is
not universal and it is not a fixed processing bug that would hit every run.

**Deliberately not asserting a cause.** With six participants, four showing a dip at the same index
is suggestive and no more; it could be an artefact of trial ordering in the capture protocol, or
coincidence. What it does establish is that the `CK-008` framing in `VENDORING.md` is too narrow —
whatever this is, it is not specific to CK. Worth one look at what happens around trial 8 in the
session protocol before anything is concluded.

## What this changes

| session | before | after |
| --- | --- | --- |
| MS | 13.44-point asymmetry, cause unknown | FPA heading drift on the right leg; not clinical |
| CK | low, cause unknown | part drift (r = -0.866), part present from trial 1 |
| AN | inconclusive | stable, no drift; the best candidate for a genuine reading |
| KM | sound | left-leg drift r = -0.788, previously unflagged |
| HH, SB | sound | confirmed flat, no drift |

None of these are clinical conclusions. Establishing that a low score is *not* an artefact is a
different and easier claim than establishing that it *is* impairment — the second needs the subject
demographic and diagnostic metadata this repo does not hold.

## Method

Per-trial GDI from `context/cohort/cohort_scores.json` (regenerated 2026-09-03, `reduced6`, all six
sessions, 15 trials each), cross-checked by running `session_drift.py` per session rather than
relying on the correlation computed here. Trend is Pearson r of trial mean against trial index;
trial-8 deviation is against each session/side's own median, so it is insensitive to that session's
overall level.
