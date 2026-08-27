# Plan: historical re-run, visualizer event picker, 6-variable joint output

Date: 2026-08-27
Source: `to_do/8_27_to_do.pdf`, `context/model modified python opensim Actual (5).pdf`,
`context/replay-os-small/`, `context/gait_analysis/`, `context/control_kinematics (2)/`
Status: proposed, not started

Three tasks, ordered by what unblocks what. Task 1 and Task 3 are independent and can run in
parallel; Task 2 is a dependency of Task 1's fallback chain but not of its main path.

---

## 0. What already exists — do not rebuild

Checked before planning, because three of the to-do items are already done:

| note | status |
|---|---|
| "combine all csvs for each trial ... loop through mvnx and combine" | **done.** `combine_curves.py` (`combine_session`, natural trial ordering, `_index.csv` provenance sidecar) plus `clinician_gui.run_batch` (`clinician_gui.py:706`), which walks a folder of `.mvnx`, skips failures, and pools once at the end. |
| "gait cycle trimming code ... turned right and left" | **root cause found and fixed** 2026-08-24, edit #13, `gait_analysis_UCM_fixed.py:1115`. What remains is re-running the data produced *before* the fix — that is Task 1. |
| "if it cannot find gait cycles then try auto trimming" | **done.** `segment_walking` already escalates prominence `0.3 -> 0.25 -> 0.2`, then enters the auto-trim retry loop (`gait_analysis_UCM_fixed.py:1337`). The missing third rung is the manual selection GUI — that is Task 2. |

Also relevant: the non-gait guardrail (minimum heel strikes, cadence window) was **removed**
2026-08-27. There is no longer any hard cutoff that blocks a trial from being analysed. Any trial
that segments will produce a report, including one that is not walking. This matters for Task 1:
the re-run will not self-police, so the survey in Phase 1.1 is the only thing standing between a
bad trial and a plausible-looking wrong number.

---

## Task 1 — Re-run the historically corrupted trials

### The defect, precisely scoped

`trimend()` returned `rHS, rTO, lHS, lTO`. Its only call site unpacks
`rHS, lHS, rTO, lTO = trimend(self, trimarray[j])`. Every auto-trim retry therefore handed back
**left heel-strikes sitting in the right toe-off slot**, and vice versa.

Two consequences that shape the whole task:

1. **The swap did not affect convergence.** The ordering check that drives the retry loop runs
   *inside* `trimend` on correctly-ordered locals and signals success through `self.promflag`.
   The loop terminated correctly. What was corrupted is every downstream consumer of the returned
   events — cycle segmentation, and therefore every metric and every exported curve.
2. **The swap only fired on trials that reached the auto-trim path.** A trial whose events came
   back correctly ordered at prominence 0.3, 0.25 or 0.2 never called `trimend` and is clean.

That second point is the whole reason to survey before re-running. The corrupted subset may be a
small minority of the archive, and re-running it is cheap compared to re-running everything.

### Phase 1.1 — Survey: which archived trials are actually corrupt

New module `rerun_survey.py`. For each archived trial, run **segmentation only** — no metrics, no
FPA analysis pass, no curve export, no PDF — and record whether the auto-trim path was entered.

- Add an instrumentation attribute set inside `segment_walking`: `self.usedAutoTrim` (bool) and
  `self.nAutoTrims` (int), assigned where `trimflag` is set and incremented in the
  `while checkflag==0` loop. This is additive and changes no behaviour.
- The survey instantiates `gait_analysis(..., allow_manual_entry=False)` per trial per leg and
  writes one row: participant, trial, leg, `usedAutoTrim`, `nAutoTrims`, cycles found, exception
  if any.
- Output: `rerun_manifest.csv`. Rows with `usedAutoTrim == True` are the re-run set. Rows that
  raise are a third bucket — trials that fail outright now and need Task 2's manual picker.

Cost check before committing to this: segmentation loads markers and coordinate values and runs
peak detection, which is a fraction of a full pipeline run but not free. Time one trial first. If
segmentation alone turns out to be most of the per-trial cost, the survey stops being a saving and
we should fall back to re-running everything.

**Risk, stated plainly:** this assumes the archived results were produced by a code version whose
`trimend` had the swap. If any participant was processed with a *different* script — one of the
`context/` variants, or the MATLAB path — the survey's premise does not hold for them. Establish
the provenance of the archive before trusting the manifest. `combine_curves.py`'s `_index.csv`
sidecars help where they exist.

### Phase 1.2 — The re-run loop

`run_batch` already does per-folder batching. What it does not do is drive *many participants* from
a manifest, which is the actual ask ("a lot of manual imports for ms participants").

New CLI `rerun_batch.py`:

- Reads `rerun_manifest.csv`, filters to the corrupted set.
- Resolves each row to its source `.mvnx` and session directory. **This is the real work** — the
  archive has `.zip`s alongside extracted folders (`Data for Alex.zip`, `S01_04162026.zip`,
  `XsensOpensim.zip`), and the mapping from participant to raw file is currently manual.
  Write the resolver as a separate, testable function with an explicit mapping file rather than
  burying path heuristics in the loop.
- Calls the existing `run_pipeline` per trial, one process per trial.
- Appends to a resumable ledger so a crash mid-run does not restart from zero.
- Writes new outputs to a **new directory**, never over the old ones. The old results are the only
  evidence of what was previously reported.

**One process per trial, not one process for the batch.** A 15-trial batch is known to die around
trial 11 with exit 127 and no traceback; individual trials are fine. Drive the loop from a shell
or a supervising Python process that spawns and reaps.

### Phase 1.3 — Verification

The re-run is only trustworthy if we can show the fix changed what we think it changed:

- Pick 2–3 trials the survey flags as corrupt. Re-run each **twice**: once on current `main`, once
  with `trimend`'s return order reverted to the buggy order. The two must differ, and differ in the
  way a left/right swap predicts (right-leg curves in the re-run should resemble the *left*-leg
  curves of the old archive).
- Pick 2–3 trials the survey flags as clean. Old and new results must be numerically identical.
  If they are not, the survey's classification is wrong and Phase 1.1 needs rework.
- Regression test in `tests/`: a synthetic `trimend` fixture asserting the unpacking order matches
  `detect_gait_peaks`. Edit #13 must not be able to silently regress.

---

## Task 2 — Visualizer as the manual gait-event picker

### Why the current approach is a dead end

`context/replay-os-small/replay-os-small.py` ends with
`osim.VisualizerUtilities.showMotion(arm, motion)`. That is a static C++ helper that runs its own
playback loop to completion. It exposes no frame callback, no pause, no current-time getter. This
is the concrete reason behind the note "can load motion in but no access to change the gui" — the
GUI is not inaccessible, it is simply not yours to drive while `showMotion` owns the loop.

### The mechanism that does work

`context/model modified python opensim Actual (5).pdf` demonstrates it (Tables 3–4). Drive the
state yourself and report each frame:

    coord.setValue(state, value)      # per coordinate
    model.realizePosition(state)
    visualizer.report(state)          # from getVisualizer().getSimbodyVisualizer()

driven from a Tk `ttk.Scale` via `slider.configure(command=callback)`. The PDF's examples set
coordinates from slider values directly; ours sets them from a row of the motion table instead.

This also answers the note's "vectors are v3 proprietary array": you never construct a `Vec3` by
hand on this path. Coordinate values are plain floats via `Coordinate.setValue`. `Vec3` only
appears for camera transforms (`viz.setCameraTransform(osim.Transform(osim.Vec3(...)))`).

### The scrub-to-time mapping

The note asks: *"what is the time column in the motion file at that point."* Make this explicit
rather than inferred, because it is where an off-by-one becomes a mislabelled gait event:

- The slider's domain is **row index** `0 .. table.getNumRows()-1`, an integer, not seconds.
- Time is read back with `table.getIndependentColumn()[row]`. Never reconstruct it as
  `start + row*dt` — `.mot` files are not guaranteed uniformly sampled after trimming.
- The event a user picks is stored as a **row index**, converted to a time only at write-out.
  `segment_walking` works in indices into `markerDict['time']`, so store indices and convert once,
  at the boundary.
- Display the resolved time next to the slider so the operator can see what they are picking.

### Phases

**2.1 — Scrubbing viewer.** New module `motion_scrubber.py`. Load a `.osim` + `.mot`, build the
coordinate-name-to-`Coordinate` map once, wire a slider to the setValue/realize/report loop. Show
current row, current time, and the values of the six joints from Task 3. Muscle dynamics off
(`set_ignore_activation_dynamics(True)`, `set_ignore_tendon_compliance(True)`) as
`replay-os-small.py` already does — otherwise OpenSim tries to solve the muscles and fails.

**2.2 — Event picking.** Four buttons — mark rHS, rTO, lHS, lTO — each appending the current row
index to a per-event list. A table shows picked events in time order and allows deletion. Run
`detect_correct_order` on the picked set live and show pass/fail, so the operator gets the same
verdict the pipeline will apply.

**2.3 — Write-back into the pipeline.** Replace `manual_steps()` — currently a stdin prompt at
`gait_analysis_UCM_fixed.py:1119` — with a call into the picker when `allow_manual_entry=True`.
Keep the return contract identical: `return rHS, lHS, rTO, lTO`, same order as
`detect_gait_peaks`. This is exactly the contract edit #13 was about; do not invent a new one.

### Risks

- **Tk mainloop vs Simbody visualizer window.** The Simbody visualizer is a separate native window
  with its own event handling. Two GUI loops in one process is the most likely source of hangs or
  a frozen window. Prototype this specific interaction in 2.1 before building anything on top of
  it. If it fights, the fallback is a matplotlib-based picker over the joint-angle curves with no
  3D view at all — less pleasant, far less risky, and sufficient for picking heel strikes.
- **The GUI must not become a required step.** Every trial that needs a human is a trial that
  cannot be batch re-run in Task 1. Keep `allow_manual_entry=False` the default for batch paths.
- **`DESIGN.md` governs the visual layer.** Read it before styling anything; the existing GUI has
  an established token set.

---

## Task 3 — Six joint outputs, and regenerating GDI

### The six variables — recovered, not guessed

The archived matrices encode the answer in their row counts, and the slicing code confirms it.
The full feature vector is 9 variables x 51 points = 459 rows, in this fixed order
(`context/replay-os-small/gaitAnalysis.py:329`):

| rows | variable |
|---|---|
| 0–50 | `pelvis_tilt` |
| 51–101 | `pelvis_list` |
| 102–152 | `pelvis_rotation` |
| 153–203 | `hip_flexion` |
| 204–254 | `hip_adduction` |
| 255–305 | `hip_rotation` |
| 306–356 | `knee_angle` |
| 357–407 | `ankle_angle` |
| 408–458 | `fpa` |

The three reduction slices in that file map exactly onto the archived matrix row counts:

| slice | rows | matches |
|---|---|---|
| `indiv_data[153:255]` + `[306:408]` (commented) | 204 = 4 x 51 | `matrix.csv`, `matrix_sci_reduced.csv` |
| `indiv_data[153:255]` + `[306:459]` (**live**) | 255 = 5 x 51 | `matrix_ms_reduced.csv`, `..._old5.csv` |
| `indiv_data[153::]` (commented) | 306 = 6 x 51 | `matrix_ms_reduced_old{,2,3,4}.csv` |

So the **six** are the canonical nine minus the three pelvis terms:

    hip_flexion, hip_adduction, hip_rotation, knee_angle, ankle_angle, fpa

Convenient side effect: the two special-case corrections in `build_gdi_feature_vector` — the
`+20` on `pelvis_tilt` and the `-180` wrap on `pelvis_rotation` — apply only to variables that are
being dropped. The 6-variable path needs neither.

### Two live defects in `gdi.py` this work has to fix anyway

1. **Wrong ninth feature.** `_GDI_FEATURES_TEMPLATE` (`gdi.py:65`) ends with
   `subtalar_angle_{side}`. Both the source `joint_names`/`joint_names2` lists and the to-do note
   ("last 2 are fpa values") say it is `fpa_{side}`. Every feature vector built today is wrong in
   its last 51 values.
2. **Reference/feature mismatch.** `MATRIX_FILENAME = "matrix_ms_reduced.csv"` (`gdi.py:92`) is a
   255-row (5-variable) matrix, while the module hardcodes 459. `compute_gdi` raises its
   shape-mismatch `ValueError` on every call. GDI cannot currently produce a number at all.

Fix both as part of parameterisation rather than as separate patches — the feature list and the
reference file must be chosen together or they drift apart again.

### Phase 3.1 — Parameterise the feature set

Replace the module-level constants with an explicit feature-set object: name, ordered variable
tuple, matrix filename, control filename, `ln_control_mean`, `ln_control_sd`. Ship the known sets
(`gdi9`, `reduced6`, `reduced5`, `reduced4`) as named definitions. `GDI_VECTOR_LENGTH` becomes
`len(features) * 51` rather than a constant.

The `ln` constants must live **inside** the feature-set definition. They are properties of a
specific control group projected through a specific matrix, not of GDI in general. Keeping them
module-global is what makes a wrong pairing possible.

### Phase 3.2 — Where the reduction happens

**Recommendation: do not shrink the curve export.** The note says "change gait cycles and joint
outputs to be 6 joints instead of 26 — all in gait analysis", but
`get_coordinates_normalized_time` (`gait_analysis_UCM_fixed.py:966`) currently exports all 38
coordinates x 101 points (the 3838-row curve CSVs), and UCM needs kinematics and COM that GDI does
not. Shrinking the shared export to 6 variables destroys the UCM inputs to save disk.

Instead: keep the full export, and add a `select_features(curves, feature_set)` projection applied
at feature-vector build time. If a 6-variable export is genuinely wanted as a separate artefact,
write it as an additional file, not a replacement.

This is a recommendation, not a decision I can make from the notes — see Open Questions.

### Phase 3.3 — Regenerate the reference by SVD

Port the MATLAB. Inputs are the two pooled matrices from the `combine_curves` path: all control
gait cycles, and all MS gait cycles, as `(306 x n_cycles)` once projected to the 6 variables.

- Build the control matrix, take its SVD, keep the eigenvector set. The archived files kept 14–15
  columns; the number retained is a real choice, not a constant — record the variance explained
  at whatever cut is used.
- Project the control group through it to get `controlCalc` (the control mean in that space).
- Recompute `ln_control_mean` and `ln_control_sd` as the mean and SD of `ln(||subject - mean||)`
  across the control group. **These change.** The 4.443685139 / 0.223457646 pair in `gdi.py`
  belongs to the old dataset and becomes meaningless the moment the feature set changes.
- Sanity check: controls scored against their own reference must centre on 100 with SD near 10.
  If they do not, the projection or the ln constants are wrong. This is a cheap, decisive test —
  run it before scoring a single patient.

### Phase 3.4 — Rescore

Score every participant from the pooled per-cycle CSVs. Per the note, this needs no second pass
through gait analysis: once the cycles are extracted and pooled, GDI is a matrix multiply and a
distance. Capture spatiotemporal metrics during cycle extraction in Task 1's re-run so they are
already on disk.

### Risk

**New GDI scores are not comparable to any previously reported number.** Different feature set,
different eigenvectors, different normative constants. Anything already written down or shown to a
collaborator was computed against a different reference. Say so explicitly wherever the new scores
appear, and keep the old outputs rather than overwriting them.

---

## Open questions

1. **Should the 6-variable reduction also change the exported curve CSVs?** Recommendation above
   is no — keep the 38-coordinate export, project at feature-build time — but the note says "all
   in gait analysis", which reads like the export itself. Confirm before Phase 3.2.
2. **How many eigenvectors to retain in the new SVD?** The archived matrices used 14, 15, 26, 27,
   28, 30, 31 and 34 across variants, which suggests this was tuned rather than fixed. Pick a
   criterion (variance explained) rather than inheriting a number.
3. **Is the archive's provenance known?** Task 1's survey assumes every past result came from a
   `trimend` that had the swap. If some participants went through a different script, they need
   separate treatment.
4. **`gait_analysis — examples?`** — unresolved note. `example.py` and `example_kinetics.py` exist
   in the repo; unclear whether the note means "find the examples" or "write one".

---

## Sequencing

    Task 1.1 survey ─────┬──> 1.2 re-run loop ──> 1.3 verification
                         │
    Task 2.1 viewer ──> 2.2 picker ──> 2.3 write-back ─┘

    Task 3.1 parameterise ──> 3.3 SVD ──> 3.4 rescore
             └─ 3.2 projection ─┘

Task 2 unblocks the trials that fail outright and feeds Task 1's third bucket. Task 3.3 wants
Task 1's re-run output to be trustworthy before the control pool is rebuilt from it.

Task 3.1 is worth doing immediately regardless — GDI is currently broken in two ways and cannot
return a number, and that is independent of everything else here.
