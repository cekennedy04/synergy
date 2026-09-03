# Is the GDI path wrong? Auditing the supervisor's suspicion

Written 2026-08-31 in response to the note in `to_do/8_31_to_do.pdf`:

> "gait analysis code for gdi is different from ucm also separated out by foot and does gdi but
> they are likely wrong since it takes csvs of everyones gait cycles and does matrix math to find
> the difference between the mean of each gait cycle"

Written as an audit. The two defects it found in **live repo code** were fixed on the same day —
see section 9, added after the fact. The other five live in vendored `context/` files and are
recorded in `VENDORING.md` rather than patched, because the repo's convention is to fix in the fork
and because the live pipeline has no equivalent of the broken code. Three defects found
earlier are already fixed and are not re-derived — see
`docs/plans/2026-08-27-001-feat-rerun-visualizer-joint-reduction-plan.md` Task 3 and its
2026-08-30 addendum.

## Verdict

The suspicion is **right about the architecture and right that scores are wrong, but the stated
mechanism is not the reason.** Taking the sentence apart:

| claim | verdict |
|---|---|
| "gait analysis code for gdi is different from ucm" | **Correct, and it matters.** Two forks of one class, 12 of 30 shared methods changed. The GDI fork is the copy as supplied, so it is missing all fifteen recorded repairs. |
| "separated out by foot" | **Correct, and correct by design.** GDI is defined per limb. Not a defect. |
| "does matrix math to find the difference between the mean" | **This is the definition of GDI**, not an error. Schwartz & Rozumalski score the distance from the control mean in an eigenvector basis. Subtracting a mean is the method. |
| "takes csvs of everyone's gait cycles" | **Correct, and this is the real defect** — but not because pooling is wrong. Because *what gets pooled* and *what gets scored* are not the same kind of object, and because the pooled units are not independent. |
| "they are likely wrong" | **Yes.** Quantified below: healthy controls score **94.5 ± 7.0** through the path as actually run, where they must score 100.0 ± 10.0. |

The headline number: **the archived MS path miscalibrates healthy controls by −5.5 points and
compresses the whole scale to 70% of nominal.** Every deviation it has ever reported is understated
by about a third. That is a much larger error than anything the "mean of gait cycles" concern
produces, and it comes from a different cause entirely.

## 1. The two paths, precisely

`context/replay-os-small/gaitAnalysis.py` (GDI) imports `gait_analysis` — the copy supplied as
`context/gait_analysis/gait_analysis.py`. The live pipeline runs `gait_analysis_UCM_fixed.py`, this
repo's fork of that same file. Method-level comparison:

    30 methods in both        18 byte-identical        12 changed
    only in the UCM fork: compute_foot_progression_angle, build_manual_picker,
                          collect_manual_events, prompt_for_event_rows, n_rows, time_at

The good news first: **`get_coordinates_normalized_time` is byte-identical** across the two, as are
`detect_gait_peaks`, `get_gait_events` and `compute_scalars`. Time normalisation — the step that
turns strides into the 101-point curves GDI consumes — is not a source of divergence.

The divergence is upstream of it, in **which strides exist at all**. `segment_walking` and `trimend`
both differ, and the GDI copy is missing:

- **edit #4** — the auto-trim retry loop's only termination check is `if j==len(trimarray)-2:
  checkflag=self.promflag`, a variable reassigned to itself. It is a no-op, so the loop can index
  `trimarray[j]` past the end. Still present at `context/gait_analysis/gait_analysis.py:1086`.
- **edit #12** — `trimend()` is cumulative and nothing bounds how much of a recording it may consume.
  No `MIN_REMAINING_SECONDS_FOR_GAIT_DETECTION` floor in the GDI copy.
- **edit #14** — with an explicit `leg=`, an empty `hsIps` yields `n_gait_cycles = -1` and dies in
  `np.zeros((-1,3))` with "negative dimensions are not allowed". Observed on real data (Trial3_1,
  session ca505b02).
- **edits #3, #5** — `IndexError` on short trials and on empty heel-strike arrays.

**Correction to one thing the plan assumed.** The addendum's Task 1 premise was that past results
came from a `trimend` carrying the left/right return-order swap (edit #13). The supplied copy does
**not** have that swap — all three of its returns are `rHS, lHS, rTO, lTO`
(`context/gait_analysis/gait_analysis.py:772, 871, 906`). Whatever copy edit #13 was found in, it
was not this one. Results processed through the supplied file are not affected by that swap.

### The ninth GDI feature is computed by different code in the two paths

`fpa` is a GDI feature in `gdi9`, `reduced6` and `reduced5`. The GDI path computes it in the
driver's own `getpelvis()`; the live path uses `compute_foot_progression_angles` in
`Examples/gaitAnalysis-UCM.py`. **`getpelvis` still carries edit #15** — it measures the walking
heading as `arctan2(y2-y1, x2-x1)`, where OpenSim's Y is vertical, so it compares forward travel
against vertical body sway and returns approximately zero always. Fully documented in
`VENDORING.md` edit #15 (fixed in the live path in commit 16c78e8); measured at 5.26° mean error
over ten OpenCap trials, and exactly zero heading on any pinned-root IMU trial. Not re-derived here.

## 2. The pooled-cycle reference: what it actually does

`control_kinematics.csv` is **459 × 166** — the canonical 9 variables × 51 points, one column per
gait cycle. Verified against the archived artefacts:

    controlcalc_control.csv  ==  matrix_control.csv.T @ mean(control_kinematics, axis=1)
                                 max elementwise difference 0.0036

So `controlCalc` is the pooled mean over the 166 **cycles**, projected — confirming the supervisor's
description of the mechanism exactly. The normative constants are the mean and SD of the
**per-cycle** log distances:

    per-cycle ln-distance, gdi9:   mean 4.6942   sd 0.2967
    the original's fallback:       (ln_result - 4.69)/0.30

Those match to three decimals, which pins the provenance of the recovered `4.69/0.30` constants:
they are this cohort's per-cycle constants. The `reduced6` pair shipped in `gdi.py`
(4.642758 / 0.300381) reproduces to six decimals from the same 166 columns.

### The 166 columns are not 166 independent observations

Correlation between control columns, by separation in file order (mean-centred):

    lag 1: +0.267    lag 2: -0.001    lag 3: +0.052    lag 4: +0.082
    random pair: -0.006

Correlation is confined to lag 1 and vanishes at lag 2. Assuming pairs gives within-pair
correlation +0.519 against +0.13–0.15 for any other block size. Per variable, within-pair versus
across-boundary:

    pelvis_list  +0.669 / +0.037     hip_flexion   +0.498 / +0.238
    pelvis_rot   +0.728 / +0.089     hip_adduction +0.447 / +0.040
    ankle_angle  +0.585 / -0.032     knee_angle    +0.447 / +0.054
    fpa          +0.456 / +0.033     hip_rotation  +0.365 / +0.052

**The cohort is 83 pairs, not 166 independent units.** (The pairing is not two limbs of one cycle —
the three pelvis variables differ within a pair by a median of 7.4°, and they would be identical.
Two cycles of one limb, or two limbs of one subject, both fit; the data cannot separate those.)

What that costs. Rebuilding `reduced6` with each pair collapsed to one column and scoring the 83
pair-means against **today's** shipped constants:

    83 pair-means vs today's reference:   103.9 ± 9.3      (must be 100.0 ± 10.0)
    83 pair-means vs a pair-built one:    100.0 ± 10.0
    166 cycles     vs today's reference:  100.0 ± 10.0

So the pooling is worth **+3.9 GDI points and a 7% scale compression** if the intended unit is the
pair. Real, directional, and modest. It also means every contributing unit is weighted twice in the
basis and in the control mean.

## 3. The mean-of-cycles concern, measured

Two live consumers of `gdi.py` disagree about what a GDI is computed from, and only one agrees with
how the reference was calibrated:

- `session_drift.py:121` → `curve_features.score_curves(...).mean()` — scores **each stride**, then
  averages the scores. Matches the per-cycle calibration. ✅
- `methodology_comparison.py:230` → `gdi.gdi_for_trial(...)` → `build_gdi_feature_vector(curves['mean'])`
  — scores the subject's **mean curve** against a per-cycle norm. Mismatched. ❌

The vendored GDI path scores per-cycle and averages the scores (`GDI_r.mean()`), so it sits on the
consistent side. The mismatch was introduced by the rewrite's own top-level API.

**How much does it matter? Much less than it first appears — and I want to record the wrong
estimate too, because it is an easy trap.** Constructing pseudo-subjects from random control cycles
suggests the mean-curve convention inflates GDI by +12 to +46 points at 2 to 15 cycles. That
construction is misleading: a bundle of random control cycles sits near the control mean, so its
distance is nearly all stride noise and averaging destroys nearly all of it.

Measured instead on all **90 real exported trial-legs** in `context/gait_curves/` (`reduced6`, the
2026-08-27 reference, 3–6 strides per trial):

    per-stride GDI range      54.5 – 90.7
    mean-curve minus per-stride mean:   mean +0.53    max +3.30    min +0.04
    correlation with within-trial stride SD    r = 0.62
    correlation with per-stride GDI level      r = 0.39
    correlation with number of strides         r = -0.16

**Always positive — the mean-curve convention always inflates — but bounded at +3.3 points on this
cohort.** It is driven by stride-to-stride variability, not stride count, and it grows as a subject
approaches normal, because a subject far from the control mean is dominated by systematic deviation
that averaging cannot remove. So it is worst exactly where discrimination matters most, and still
small. This is a defect to fix for consistency, not the explanation for wrong scores.

## 4. What is actually producing wrong numbers

Scoring the 166 control cycles through the archived references **as the script actually runs them**
— archived matrix paired with the archived hardcoded constants:

| path as run | healthy controls should be | they score |
|---|---|---|
| `msflag` — `matrix_ms_reduced.csv` + 3.64317 / 0.54211 | 100.0 ± 10.0 | **94.5 ± 7.0** (range 73.6–106.5) |
| `sciflag` — `matrix_sci_reduced.csv` + 4.518094 / 0.415455 | 100.0 ± 10.0 | **103.5 ± 7.2** |

Two distinct causes, cleanly separated:

- **The MS basis is not a basis.** `matrix_ms_reduced.csv` has column norms from 0.031 to 1.000 and
  `MMᵀ` departs from the identity by 0.999. Projections onto its scaled-down columns shrink 5–30×
  and the distance collapses. `load_gdi_reference` now refuses it (already recorded in the plan
  addendum). The SCI matrix is fine — `|MMᵀ−I| = 1.07e-3` — so its error is purely in the constants,
  which belong to some other cohort.
- **Both scales are compressed to ~70%.** The divisor is an SD from a different distribution than
  the numerator. A subject reported at 80 through the MS path is roughly 71 on a correct scale.

The vendored driver hardcodes `selected_index=2`, so **`msflag` is the only path it ever runs.**

## 5. Two further defects in the vendored driver

**The per-cycle selection is index-confused and silently keeps the outliers.** At
`context/replay-os-small/gaitAnalysis.py:400-413` (and again at 646-659 for the left leg):

```python
c = np.argsort(overalldepth)          # c[k] = index of the k-th most central cycle
data3 = reduceddat[:, (abs(rsco) < 3).flatten()]      # MAD outlier rejection
c2    = c[(abs(rsco) < 3).flatten()]
if len(c2) > 5:
    data2 = reduceddat[:, (c < 6).flatten()]          # <- both bugs are on this line
else:
    data2 = data3
```

`(c < 6)` masks the *ranks*, not the cycles. Worked example with 8 cycles of depth
`[5,1,9,2,8,3,7,4]`: the intended six most central are columns `[1,3,5,7,0,6]`; the code selects
columns `[0,1,2,4,6,7]`, which includes the two **deepest** cycles (9.0 and 8.0). The correct
expression is `reduceddat[:, c[:6]]`.

And it indexes `reduceddat`, not `data3` — so whenever more than five cycles survive MAD rejection,
which is the normal case, **the outlier rejection is computed and then thrown away.**

**The depth measure misses a point per variable.** `reduceddat[starts[j]+1 : starts[j+1]-2]` plus
the two endpoints covers 50 of each variable's 51 indices — index 49 of each block is never
included — and the sum is divided by 50. Immaterial while the selection it feeds is broken, but it
should not survive the fix.

Two harmless-but-fragile aliases, worth noting only so nobody "cleans them up" into a real bug:
`diff = subject` and `rsco = ap` create references, not copies. Both happen to be safe because each
column is read before it is written.

`perGaitCycle.csv` is loaded in all three branches and never used. It is a 0-to-1 percent-of-cycle
axis repeated nine times, not data.

## 6. What is not wrong

Stated explicitly, because an audit that only lists faults invites over-correction:

- **Per-foot separation is correct.** GDI is a per-limb score by definition.
- **Subtracting the control mean is correct.** That is the method, not a bug.
- **SVD on the raw, uncentred matrix is faithful to the archived reference** and the evidence for it
  is recorded in `gdi_reference.py`'s docstring.
- **Time normalisation is shared.** `get_coordinates_normalized_time` is byte-identical across both
  forks.
- **The published AN drift finding stands.** It came through `session_drift.py`, the per-stride
  consumer, which is the convention the reference is calibrated for.

## 7. Ranked, with what each is worth

| # | defect | magnitude | where |
|---|---|---|---|
| 1 | FPA heading measured against vertical, zero under a pinned root | up to 36° heading drift → −29.6 GDI within one session | `getpelvis`, GDI path only; fixed in the live path (edit #15) |
| 2 | Archived MS path miscalibrated and non-orthonormal | controls 94.5 ± 7.0; scale at 70% | `gaitAnalysis.py` as run |
| 3 | GDI fork missing edits #3, #4, #5, #12, #14 | crashes and unbounded trimming; changes which strides exist | `context/gait_analysis/gait_analysis.py` |
| 4 | Cycle selection keeps the deepest outliers; MAD filter discarded | selects 6 arbitrary cycles instead of the 6 most central | `gaitAnalysis.py:413`, `:659` |
| 5 | Reference pooled over 166 correlated cycles (83 pairs) | +3.9 points, 7% scale compression | `gdi_reference.py` / `control_kinematics.csv` |
| 6 | `gdi_for_trial` scores a mean curve against a per-cycle norm | +0.53 mean, +3.30 max, always positive | `gdi.py:509` vs `session_drift.py:121` |
| 7 | Depth measure omits index 49 of each variable, divides by 50 | negligible while #4 stands | `gaitAnalysis.py:395`, `:641` |

## 8. Recommendations

1. ~~**Retire the vendored GDI path rather than repair it.**~~ **Decided 2026-08-31: keep it, as
   reference.** Defects 1–4 all live in code the live pipeline already replaced — the live route
   (one `gait_analysis_UCM_fixed` run, wide curve export, `curve_features.py` projecting at
   feature-build time) has none of them, so nothing depends on the vendored driver and it is not
   repaired. It stays on disk as the provenance record for what the original did: the recovered
   feature-set slices, the `msflag`/`sciflag` constants and the per-cycle scoring convention were
   all read out of it, and deleting it would strand every claim in this document that cites a line
   number. `VENDORING.md` carries the warning against porting its cycle-selection stage.
2. **Pick one scoring unit and make `gdi.py` enforce it.** Today `gdi_for_trial` and `score_curves`
   answer differently for the same trial. Whichever is chosen, the reference must be built from the
   same kind of object. Recording the unit in the reference sidecar would make a mismatch a load
   error, the way the feature-set/matrix pairing already is.
3. **Ask the collaborator what a column of `control_kinematics.csv` is.** The pairing is empirically
   unambiguous; what a pair *is* — two cycles of one limb, or two limbs of one subject — is not,
   and it determines whether the constants should be rebuilt at 83 units. This is the last open
   provenance question flagged at plan line 349. **Now carried in the code** as the `OPEN QUESTION`
   comment in `gdi_reference.build_reference`, where the per-column assumption is actually made,
   with a pointer from `gdi.py` beside the constants it would change — so it is found by whoever
   next touches either end, not only by whoever reads this document.
4. **Do not report GDI against the archived references at all.** Both as-run pairings are
   miscalibrated in opposite directions. `load_gdi_reference`'s orthonormality refusal already
   blocks the MS one; the SCI one passes the check and is still wrong.
5. **Any number produced before the 2026-08-27 regeneration should be treated as unusable**, not
   adjusted. The scale compression is not a constant offset that can be corrected after the fact.

## 9. What was fixed (added 2026-08-31, after the audit)

Two changes, both in live repo code, both covered by new tests. Full suite: 493 passed.

**Defect #6 — the scoring unit.** `GdiFeatureSet` now carries `scoring_unit`, and `gdi_for_side`
scores on it: every shipped set declares `cycle`, so each gait cycle is scored and the *scores* are
averaged — which is both what the reference is calibrated for and what the supervisor's original
script did (`GDI_r.mean()`). A cycle-calibrated set handed only a mean curve now **raises**. The
fallback was the defect: it returns a number, the number is always too high, and nothing downstream
can tell it apart from a correct one.

**Recommendation 4, made enforceable.** `GdiFeatureSet.reference_digest` is the sha256 of the exact
(matrix, control_mean) pair the constants were derived from; `load_gdi_reference` refuses a mismatch
with `GdiReferenceMismatchError`, waivable via `check_digest=False`. `gdi_reference.py` writes the
digest and the scoring unit into the sidecar. This closes the gap the orthonormality check could
never see — a *valid* basis from the *wrong* cohort:

    archived gdi9      -> now refused (previously loaded; controls read 100.8)
    archived reduced4  -> now refused (previously loaded; controls read  96.6)
    archived reduced5  -> already refused, non-orthonormal
    archived reduced6  -> already refused, non-orthonormal
    regenerated x4     -> load, digest verified

`gdi_comparison` reports a mismatch rather than raising, matching its existing "state the reason,
never fabricate a score" contract. The `curve_features.py` and `session_drift.py` CLIs print the
error and exit 1 instead of dumping a stack trace -- each of these messages is already a full
sentence naming the fix, and a traceback buries it. That is the same complaint edit #14 records
against numpy's "negative dimensions are not allowed".

Verified on the real runtime object type, which nothing else covered: `gdi_for_side` on the pandas
DataFrames `get_coordinates_normalized_time` actually returns agrees to 1e-9 with the array path,
and on `CK-CK-003_right` it removes a **+1.26** point bias (88.41 against the old 89.68).

**Verification worth recording.** Rebuilding `reduced6` from the archived cohort reproduces
`ln 4.642758 / 0.300381` exactly and its sidecar digest equals the shipped constant — so the
2026-08-27 regeneration is bit-reproducible from `control_kinematics.csv`.

**No previously reported number changes.** Every published figure came through `session_drift.py`'s
per-stride path, which was already the calibrated convention. What changed is that the other path
can no longer silently disagree with it.

**Not fixed, deliberately.** Defects #1, #3, #4 and #7 are in `context/` vendored files. #1 and #3
already have repo-side fixes (edits #15 and #3/#4/#5/#12/#14); #4 and #7 have no repo-side
equivalent because the cycle-selection stage was never ported, and `VENDORING.md` now records why
it should not be. #5 needs the collaborator to say what a `control_kinematics.csv` column is before
the constants could be rebuilt at 83 units.

---

## 10. The open question, answered (2026-09-01)

Section 8's recommendation 3 asked what one column of `control_kinematics.csv` is, because it
decided whether the normative constants should be rebuilt at 83 units. **It is one stride** — a
single gait cycle of a single limb. The per-column treatment in `gdi_reference.build_reference` is
therefore correct, the constants stand, and **the +3.9-point rebuild proposed in section 2 must not
be done.**

Three independent lines of evidence agree.

**1. The published method.** Herrera-Valenzuela et al. 2022, *Derivation of the Gait Deviation
Index for Spinal Cord Injury* (`10.3389/fbioe.2022.874074`) — the closest published analogue of this
project's own `sciflag` path:

> "a matrix with kinematic data from several walking strides where **each column vector is a
> stride** represented by nine joint angles of a whole gait cycle extracted at 2% increments: three
> planes for the pelvis and hip, knee flex/extension, ankle dorsi/plantarflexion, and foot
> progression angle"

Its control group is counted the same way — "446 **strides** from adults without gait pathologies".
Sinovas-Alonso et al. 2022 (`10.3389/fnhum.2022.826333`) states the distance is taken to "the
average of a set of healthy control **strides**", and traces the basis to >6,000 CP strides in
Schwartz & Rozumalski 2008.

Three incidental confirmations of things this repo had recovered by inference: 459 = 9 × 51 at 2%
increments, 15 retained features, and **the ninth variable is the foot progression angle** — the
`fpa`-not-`subtalar_angle` recovery is now externally corroborated rather than argued from
commented-out code.

**2. The supervisor's code.** `context/replay-os-small/gaitAnalysis.py:763-810` builds `indiv_data`
as `459 × (n_right_cycles + n_left_cycles)`, one column per gait cycle per limb, right block then
left block. That is exactly this file's shape.

**3. The file.** The 83-pair structure is adjacent strides sharing a subject, which is what pooling
per-trial exports produces. It does mean the effective sample is nearer 83 than 166 for a confidence
interval on the constants — that bears on precision, not on the unit.

**This also settles the section 3 fix.** The calibration unit is the stride, so scoring per stride
and averaging the scores is right, and `gdi_for_side`'s behaviour is correct as shipped.

### A new defect found on the way: `+20` on `pelvis_tilt` disagrees with the cohort

The test that ruled out one reading of the pairing was to look for the driver's left-limb sign
flips. They are not there — and neither is its `+20`:

    control_kinematics.csv column-mean pelvis_tilt = 11.99   (raw; a stored +20 would give ~32)

So `_CURVE_ADJUSTMENTS`' `+20` offsets a `gdi9` subject vector from the reference in 51 of its 459
rows. Scoring the control cycles through gdi9 both ways:

    as stored (raw tilt)              100.0 ± 10.0     <- correct by construction
    with the +20 adjustment applied    89.5 ±  9.1     <- a 10.5-point loss on normal subjects

**Not currently reachable**, because `DEFAULT_FEATURE_SET` is `reduced6` and reduced6/5/4 carry no
pelvis terms — the same immunity the 2026-08-30 addendum noted in reduced6's favour, now with a
measured cost for the set that lacks it. But `gdi9` is shipped and would return a plausible wrong
number.

**Not fixed, deliberately.** Deleting the `+20` is not obviously right: it is a convention offset,
and this pipeline makes the mismatch worse rather than better — its own raw `pelvis_tilt` runs ~21.5°
against the cohort's ~12°, so `+20` takes it to ~41°. Which of the three conventions is the odd one
out is a provenance question of exactly the kind just settled above, and it deserves the same
treatment rather than a guess. Recorded at the adjustment table in `gdi.py`.

**Still open, and narrower than before.** `control_kinematics.csv` was **not** written by the driver
— the raw tilt proves it — so it is an earlier artefact of the collaborator's, and which cohort and
pipeline produced it remains unestablished. The *unit* question is closed; the *provenance* question
is not.

---

## 11. gdi9 disabled (2026-09-02), after an outside review

Section 10 recorded the `pelvis_tilt` mismatch and left it unfixed, on the reasoning that it was
"not currently reachable in practice" because `DEFAULT_FEATURE_SET` is `reduced6`. **That reasoning
was wrong**, and an independent Codex review caught it.

`--feature-set gdi9` is a documented flag on both `curve_features.py` and `session_drift.py`. It ran
clean:

    --feature-set gdi9      GDI mean 82.6      exit 0, no warning
    default reduced6        GDI mean 88.4

Being off the default path is not the same as being unreachable. A user following the CLI's own
`--help` could produce a number ~10.5 points low against controls that are normal by construction,
with nothing in the output to suggest anything was wrong. That is precisely the "plausible wrong
number" failure the rest of this work exists to prevent, shipped while being documented.

**gdi9 is now disabled outright.** `GdiFeatureSet.disabled_reason` carries the explanation, and two
hard stops raise `GdiFeatureSetDisabledError` (a `RuntimeError` — nothing about the caller's
arguments is malformed; the pipeline is not in a state where this set can be honestly scored):

- `get_feature_set()` refuses it **by name** — the CLI path.
- `compute_gdi()` refuses it **as an object** — `get_feature_set` duck-types feature-set objects
  straight through, so the name guard alone would leave `compute_gdi(v, ref, gdi.GDI9)` open.
  Scoring is the last point where refusing still stops a wrong number existing.

Both CLIs print the reason and exit 1 rather than dumping a traceback, matching how reference
failures are already handled.

**Deliberately not waivable.** Every other check here has an escape hatch (`check_digest=False`,
`check_orthonormality=False`) because an expert may legitimately want to reproduce a historic
result. This one does not: those hatches permit a reference that is merely *unattributed*, whereas a
disabled set produces output known to be wrong in a known direction, and there is no honest reason
to want that number.

**Disabled, not deleted.** The recovered feature order, the regenerated constants and the digest all
remain — they are needed to read this document and to rebuild gdi9 once the convention is settled.
`GDI9.can_score` is still true: gdi9 is out of service for a *convention mismatch*, not for missing
calibration, and collapsing that into `GdiConstantsMissingError` would lose a distinction this
module draws deliberately.

**Why not just delete the `+20`.** Trimming and calibration are orthogonal: auto-trimming recovers
steady-state cycles from noisy trial bounds, it does not recalibrate a coordinate offset, so cleanly
trimmed data still scores wrong through gdi9. And deleting the offset would be a guess — this
pipeline's own raw `pelvis_tilt` runs ~21.5° against the cohort's ~12°, so `+20` takes it to ~41°;
which of the three conventions is authoritative is the collaborator's call. Guessing wrong
reintroduces the same class of error at a different offset.

**Status: the ship blocker is closed.** No route now reaches a gdi9 score. 598 tests pass. The
remaining open item is unchanged and is a question, not a defect: what the authoritative pelvis
convention is.

### What the review got right, and where it was over-severe

Codex raised two further `[P1]`s about the digest: that it hashes only `(matrix, control_mean)` and
so binds neither the constants nor the scoring unit, and that enforcement is skipped for any feature
set with `reference_digest=None`. Both are **factually correct** and verified against the code.

They are recorded here as **P2**, not fixed. The digest was built to catch the failure that actually
occurred — loading an archived reference directory whose matrix belongs to a different cohort — and
it does that provably: all four archived pairings are refused, all four regenerated ones verify. The
residual risk Codex describes is someone hand-editing `ln_control_mean` in source without updating
the digest literal beside it. That is a different and much smaller threat, and no digest computed
over on-disk files can detect it. Worth revisiting if feature sets ever become user-supplied rather
than defined in this module.

One documentation finding is accepted: the flat assertion "Always high, never low" above
`SCORING_UNIT_CYCLE` overclaims. The ordering is measured over 90 trial-legs, not proved; the
comparison is against the mean of *log* distances and no universal ordering follows.

---

## 12. The frame mismatch is general, not a pelvis bug (2026-09-02)

Section 11 disabled `gdi9` for a `pelvis_tilt` convention mismatch and named the authoritative
convention as the open question. Investigating a proposed fix produced a larger finding: **the
mismatch is not confined to the pelvis, and a pelvis correction cannot resolve it.**

### The three conventions, reconciled

The diagnosis that prompted this was sound, and the literature supports it:

| Convention | Mean | Assessment |
|---|---|---|
| A — stored control cohort | **11.99°** | Clinical baseline. Matches optical-mocap norms (12° ± 4°, Schwartz 2008 / Davis 1991). The constants are moments of *this* distribution. |
| B — our raw exports | **21.23°** | Uncalibrated markerless baseline, consistent with OpenCap-derived anatomical frames sitting ~20-22°. |
| C — B plus the legacy `+20` | **41.23°** | Double-counted. The `+20` was written for a pipeline outputting near 0°; applied here it over-corrects. |

**Acted on: the `+20` is removed.** 41.23° is non-physiological against any published norm, so the
offset was wrong here regardless of which frame proves authoritative — removing it required no
answer to the open question. What replaces it does.

### Why no fitted offset replaced it

Aligning our mean tilt to the cohort's (a −9.24° shift) was measured and rejected on three grounds.

**The estimator is thin.** The "90 trial-legs" are three subjects, and their means span 6.5° —
70% of the offset being estimated:

    CK-CK   24.28    OC   21.63    XT-XT   17.78     (spread 6.50, offset 9.24)

**It would calibrate away the signal.** Mean-matching a *subject* group onto a *control* reference
removes exactly the between-group difference GDI exists to measure. If those subjects are impaired,
subtracting their mean offset subtracts their impairment. None of the three has a verified health
status in this repo.

**It targets the wrong variable.** Measured per variable against the cohort:

    hip_flexion    -13.47      <- largest, and reduced6 uses it
    fpa            +10.90
    pelvis_tilt     +9.24      <- the one the fix addressed
    ankle_angle     -4.70
    pelvis_rotation +2.36
    knee_angle      -2.41
    hip_adduction   +0.85
    hip_rotation    +0.75
    pelvis_list     -0.54

    sum |offset| over the six NON-pelvis variables: 33.1 deg

### The decisive measurement

`reduced6` contains **no pelvis terms at all**, so it is immune to this entire question. Our
subjects score:

    CK-CK    n=145 strides    84.62 +/- 4.19
    OC       n=106            77.04 +/- 8.77
    XT-XT    n=145            78.08 +/- 8.59
    ALL      n=396            80.20 +/- 8.09

    control cohort, same reference     100.00 +/- 10.00
    deficit, zero pelvis involvement    19.80 points

A pelvis-only correction cannot close a 19.8-point gap in a feature set containing no pelvis terms.
Confirmed directly — `gdi9` under each convention:

    +20 (legacy)              79.04
    no adjustment (raw)       85.58
    -9.24 (proposed)          84.38      <- target was 100
    reduced6 (pelvis-free)    80.20

Note that the legacy `+20` produced the *closest* agreement with `reduced6` (79.04 vs 80.20). That
is coincidence, and it is worth stating plainly: **agreement between gdi9 and reduced6 is not a
validity criterion.** They are different feature sets with different constants and need not agree.
The criterion is whether a known-healthy subject scores ~100, and no combination tested achieves it.

### What this means

Either our three subjects are genuinely impaired, or this pipeline's kinematics are systematically
offset from the optical-mocap cohort the reference is built on — the same anatomical-frame problem
identified for the pelvis, but across all nine variables. **The repo cannot distinguish these**, and
the distinction decides whether every GDI number this project reports is ~20 points low.

Scores remain internally consistent and therefore valid for **within-pipeline comparison** — trial
to trial, leg to leg, session to session, which is what `session_drift.py` and the clinician report
actually do. They are **not** on the published normative scale, and should not be reported as though
100 means what it means in the literature.

### The question that resolves it

Not the pelvis convention. It is: **is there a known-healthy subject measured through this
pipeline?** One such subject scoring ~100 on `reduced6` shows the frame is sound and our cohort is
impaired. One scoring ~80 shows the frame is offset and every reported score needs rescaling. That
is a single measurement, and it is worth more than any further analysis of the existing files.

Failing that, the clean alternative is to build the normative reference from healthy subjects
measured through **this** pipeline, which sidesteps cross-pipeline comparability entirely. A frame
correction derived from a concurrent-capture validation study (same subjects, both systems) would
also work; one fitted to our own participants would not.

---

## 13. Section 12 is retracted: there is no uniform pipeline offset (2026-09-03)

Section 12 concluded that either our subjects are impaired or this pipeline is systematically offset
from the optical-mocap cohort, and that the repo could not distinguish them. **The second
explanation is now refuted, and section 12's framing of the open question is withdrawn.**

The error was sampling. Section 12 measured three subjects and read 80.20 +/- 8.09 as the pipeline's
centre. It was the low tail.

### All six sessions

Scored on `reduced6` against `context/gdi_reference_2026-08-27`, verified by running each through
`validate_control_baseline.py` rather than reading the cohort JSON:

    session   left     right    pooled   verdict
    SB         98.96   106.13   102.35   sound
    HH         98.89    97.82    98.32   sound
    MS        104.79    91.35    98.31   inconclusive -- legs disagree by 13.44
    KM         93.34    88.41    90.96   sound
    AN         87.60    85.56    86.64   inconclusive
    CK         85.22    83.36    84.30   low

    cohort mean 93.45 +/- 7.44, range 83.36-106.13

### Why this settles it without a control capture

A uniform -20 point offset is arithmetically incompatible with the observed maximum. SB's right leg
scores 106.13; under that hypothesis its true value would be 126.13. HH reaches 98.32 and MS 98.31.
Same pipeline, same reference, same feature set as CK's 84.30.

**The argument does not depend on anyone's clinical status**, which is what makes it decisive from
existing data: whatever these subjects' conditions, a constant subtracted from everyone cannot
produce a 22-point spread that straddles the normative mean.

The pipeline is stable across routes, so this is a sampling difference and not a moving target: CK
measures 84.62 through `context/gait_curves` and 84.30 through the session route.

### What section 12's other numbers become

**The 33.1 deg figure is superseded.** It was computed on the same three subjects. Recomputed over
all six sessions (180 curve files):

    variable          cohort     ours     offset      (3-subject figure)
    pelvis_tilt        11.99    22.27    +10.27           +9.24
    hip_flexion        19.50     8.93    -10.57          -13.47
    fpa                -7.64    -2.85     +4.78          +10.90
    ankle_angle         0.26    -2.18     -2.44           -4.70
    knee_angle         22.99    21.47     -1.51           -2.41
    hip_adduction      -0.35     0.16     +0.51           +0.85
    hip_rotation       -2.25    -2.39     -0.14           +0.75

    sum |offset|, six non-pelvis variables: 20.0 deg  (was 33.1)

`pelvis_rotation` is omitted: the raw exports carry unwrapped values near 360 that
`_CURVE_ADJUSTMENTS` folds back at feature-build time, so a raw mean over it is not comparable to
the cohort's and the apparent +20 deg is an artefact of the measurement rather than a finding.

Residual coordinate differences therefore persist, and they still do not explain the scores. GDI is
a Euclidean distance in a 15-dimensional projected space, not a sum of per-coordinate mean offsets,
so mean-level differences do not simply add into a deficit -- and empirically they do not, since the
cohort centres near 100 with 20 deg of them present.

### What stays true from section 12

- The `+20` on `pelvis_tilt` was still wrong and is still removed: 41 deg mean tilt is
  non-physiological, and our raw tilt now measures 22.27 deg against the cohort's 11.99.
- A fitted global offset is still rejected, now for a second reason -- there is no uniform offset to
  fit, and mean-matching subjects onto a control reference removes exactly the between-subject
  variation the score exists to detect.
- `gdi9` stays disabled: its pelvis terms carry a real convention mismatch against the reference
  cohort with no offsetting benefit.
- Within-pipeline comparison was never in question.

### What is actually open now

Narrower, and per-subject rather than global:

1. **CK at 84.30 and AN at 86.64.** Impairment, or that subject's tracking quality? A per-session
   question, answerable by looking at those two sessions.
2. **MS's 13.44-point inter-leg gap** (104.79 vs 91.35), which the asymmetry guard flags while the
   pooled 98.31 looks unremarkable. This is the case that guard was written for.
3. **Clinical status of the six.** Not needed to refute the uniform offset, but needed before any
   individual score is interpreted as impairment.

The control capture is no longer the blocking measurement. It would be confirmatory, and its value
now lies in anchoring individual interpretation rather than in validating the scale.
