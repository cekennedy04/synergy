# Synergy

Joint-kinematics research project comparing two simultaneous gait-recording methods captured
while a subject walks, to compute a synergy index between them:

- **OpenCap** — video-based pose estimation feeding an OpenSim musculoskeletal simulation.
  OpenCap and OpenSim come from the same group; OpenCap handles video → human pose estimation,
  OpenSim does the biomechanical simulation (muscle activations, joint torques, moment arms,
  back-computed joint angles).
- **Xsens body suit** ("exsense" in early notes) — worn simultaneously with the OpenCap
  recording, gives joint angles directly and more precisely than OpenCap.

The current analysis pipeline is manual and takes ~15 steps per trial. The goal of this project
is to automate it: loop through a batch of recordings and run the full pipeline on each one
without hand-driving every step.

The gait-cycle-segmentation portion of the pipeline is built on top of the
[OpenCap GitHub repo](https://github.com/opencap-org/opencap-processing) (a large portion of
this codebase is inherited from there — vendored directly into this repo; see `VENDORING.md`,
and `PROVENANCE.md` for which files are upstream, supervisor-supplied, or written here),
which already contains the logic for detecting when steps happen — splitting a walking trial
into strides from heel-strike to heel-strike (heel strike → single support → swing → next
heel strike).

## Running the GUI

```
python launch_gui.py
```

Any python works -- there is no need to `conda activate` first. The launcher
finds the `opencap-processing` environment (the only place `opensim` is
installed) and re-executes the GUI under it. On Windows, `launch_gui.bat` does
the same and can be double-clicked.

Note that the **tests** run under a different interpreter than the app: `pytest`
lives in base, not in `opencap-processing`.

```
~/miniconda3/python.exe -m pytest tests -q
```

See `.claude/skills/run-gui/SKILL.md` for the failure modes and the
`SYNERGY_PYTHON` override.

## Pipeline

1. **Xsens → OpenSim format.** Convert Xsens kinematics (`.mvnx`) into the `.mot` format
   OpenSim expects, so Xsens data can run through the same downstream code as OpenCap data.
   Requires mapping each Xsens joint to its corresponding OpenCap/OpenSim joint (currently done
   in MATLAB).
2. **Gait-cycle segmentation.** Feed the `.mot` file into the existing OpenCap-derived code that
   finds heel-strike events and splits the trial into 0–100% gait cycle, per joint, producing a
   table of motion files.
3. **Apply to scaled model.** Use a subject-scaled OpenSim model (scaled by height/weight) with
   both the OpenCap-derived and Xsens-derived motion data, so the two sources are comparable on
   the same model.
4. **Repackage into an OpenCap session.** OpenCap sessions download as a zip with a 32-char
   session-ID descriptor. Extract it, replace the motion files inside the kinematics folder
   (one subfolder for OpenCap results, one for Xsens-derived results), then re-zip for upload
   back into the gait analysis backend.

## Open concerns — read this first

**The foot progression angle was never referenced to the walking direction.** Found 2026-09-01.
Full write-up with every measurement in
[`docs/2026-09-01-fpa-heading-concerns.md`](docs/2026-09-01-fpa-heading-concerns.md); provenance in
`VENDORING.md` under edit #15.

`getpelvis` derives the direction the subject walked as
`arctan2(y_end - y_start, x_end - x_start)`. OpenSim's ground frame is X forward, **Y vertical**,
Z lateral — walking is in X-Z. As written it measures forward travel against vertical bounce, so
FPA has never been expressed relative to the direction of travel. It looks plausible because the
answer is always near zero, which is approximately right whenever a subject walks straight along
+X.

Two consequences, one of which is not confined to this repository:

| where | effect | size |
|---|---|---|
| **Upstream OpenCap results** (root translates) | constant bias per trial | **5.26 deg mean, 6.55 max** over 10 trials |
| **This project's IMU route** (root pinned) | `arctan2(0, 0) = 0`, so FPA becomes absolute foot yaw and tracks heading drift | **up to 30 GDI points** within one session |

Across six participants, `|pelvis heading drift|` predicts the within-session change in GDI at
**r = -0.947, about -0.72 points per degree**; four of six sessions carry 10-36 degrees of drift.

Repaired by measuring the heading in the ground plane, falling back to pelvis yaw where the root
does not translate. Everything else was deliberately left alone — the `+/-5` degree foot offsets,
the mirrored left/right sign, one heading per trial, and FPA's place in the GDI feature set.

**The correction does not improve every number, which is the main reason to trust it.** One
participant's drift is driven by hip flexion rather than FPA and is untouched to two decimal
places; another retains a genuine right-foot divergence that is visible in the raw recording. A fix
that cleaned those up as well would have meant real signal was being flattened.

**Any GDI or FPA value produced before 2026-08-31 is superseded.** Pre-fix curve exports are kept
per session as `GaitCurves_pre-fpa-fix/` rather than deleted.

Two questions for whoever maintains the upstream code, both in the write-up: what the `+/-5` degree
foot offsets encode (no derivation found anywhere), and whether anything downstream was tuned
against the old near-zero heading.

**GDI reads roughly normal across the cohort; two subjects sit low.** Corrected 2026-09-03 --
an earlier version of this section claimed the pipeline carried a systematic ~20-point offset
against the published scale. **That claim was wrong**, and it was wrong because it generalised from
three subjects who turned out to be the low tail. Over all six processed sessions, scored on
`reduced6` against `context/gdi_reference_2026-08-27`:

| session | left | right | pooled | verdict |
| --- | --- | --- | --- | --- |
| SB | 98.96 | 106.13 | **102.35** | sound |
| HH | 98.89 | 97.82 | **98.32** | sound |
| MS | 104.79 | 91.35 | **98.31** | inconclusive -- legs disagree by 13.4 |
| KM | 93.34 | 88.41 | **90.96** | sound |
| AN | 87.60 | 85.56 | **86.64** | inconclusive |
| CK | 85.22 | 83.36 | **84.30** | low |

Cohort mean **93.45 +/- 7.44**, range 83.36-106.13 -- within one SD of the normative 100 +/- 10.

**A uniform offset is refuted, and does not need a control capture to refute it.** If the pipeline
subtracted ~20 points from everyone, no subject could reach 98, let alone 106: SB's right leg would
need a true score of 126. Same pipeline, same reference, same feature set. This argument does not
depend on knowing anyone's clinical status.

**So low scores are subject-specific.** CK at 84.30 and AN at 86.64 are low for reasons particular
to those subjects -- real impairment, or that subject's tracking quality -- not because the scale is
shifted. The pipeline is stable across routes: CK measures 84.62 through `context/gait_curves` and
84.30 through the session route.

**Residual coordinate differences exist and do not explain the scores.** Measured over all six
sessions (180 curve files) against the cohort, `hip_flexion` runs -10.57 deg and `fpa` +4.78,
summing to 20.0 deg across the six non-pelvis variables. (An earlier 33.1 deg figure came from the
same three-subject sample and is superseded.) Those are mean-level differences in individual
coordinates; GDI is a distance in a 15-dimensional projected space, so they do not simply add up
into a score deficit -- and empirically they do not, since the cohort still centres near 100.

**What this means in practice.** Relative comparison -- trial to trial, leg to leg, session to
session -- was never in question. Absolute GDI can now be read against the published scale with
ordinary care, treating a single low session as a finding about that subject rather than about the
pipeline. What is *not* established is any individual subject's clinical status.

**Do not fit a global offset to our participants.** Still true, and now for a second reason: there
is no uniform offset to fit, and mean-matching a subject group onto a control reference removes
exactly the between-subject differences the score exists to detect.

**Checking one session — `validate_control_baseline.py`.** Originally written to settle the
pipeline-offset question; that question is answered, so it now serves as a per-session diagnostic
for outliers and asymmetry.

```bash
python validate_control_baseline.py     --session PATH/TO/SESSION     --reference context/gdi_reference_2026-08-27
```

| code | verdict | meaning |
| --- | --- | --- |
| 0 | SOUND | pooled >= 90 |
| 1 | ACTION REQUIRED | pooled <= 85; investigate that subject's data quality |
| 2 | INCONCLUSIVE | the 85-90 band, **legs disagreeing by more than one normative SD**, or fewer than 8 strides |
| 3 | UNABLE TO RUN | missing reference, invalid session, or a pelvis-bearing feature set |

The asymmetry guard is the most useful of these in practice: it is what flags MS, whose legs differ
by 13.4 points (104.79 vs 91.35) while the pooled mean of 98.31 looks unremarkable. A pooled mean
alone would have hidden that.

**`gdi9` is disabled** and raises `GdiFeatureSetDisabledError` from both `get_feature_set` (by name,
the CLI path) and `compute_gdi` (as an object). Its pelvis terms carry a convention mismatch against
the reference cohort -- `pelvis_tilt` runs +10.27 deg -- with no offsetting benefit. `reduced6` is
the default and the only set the project reports through. This is not waivable, unlike
`check_digest`: a disabled set's output is wrong in a known direction, and there is no honest reason
to want that number.

## Known issues / open problems

- **An intermittent native crash with no Python traceback.** Trials occasionally exit with
  `3221226505` (`STATUS_STACK_BUFFER_OVERRUN`). It is *not* tied to particular trials — one that
  crashed in a batch completed on the next run. Each trial now runs in its own process so a crash
  costs one trial rather than the whole batch; the cause is still unknown.
- **`AnalyzeTool` is run but its result is never read.** `getpelvis` constructs one, runs it, then
  recomputes everything itself from the `.mot`. Roughly 17 s per trial — about a quarter of the
  per-trial cost — with no observable use. Left in place in case of a side effect.

- **Zip handling is fragile.** File-finding by name (motion files, session metadata) breaks if
  filenames get mangled on re-zip, or if files end up nested deeper than the code expects.
- **Session ID parsing is inconsistent.** The session ID must be retained in the filename, but
  the format varies — ID alone, ID + `.zip`, or an extra underscore — and index-based parsing
  is the main source of bugs here.
- **Login requirement.** The gait-analysis backend requires being logged in as the account that
  originally recorded the session, so the pipeline currently has to log in as that user each run.
- **No direct motion-file import.** Raw motion files can't be imported straight into OpenCap —
  inverse kinematics has to be re-run manually to regenerate marker positions, and the
  resulting timescale/resolution don't line up cleanly with the original recording.
- **Manual file selection.** Selecting which Xsens/OpenCap folder to convert still requires
  typing exact folder names; there's no directory picker or cycling through a folder of trials
  yet.
- **Tight coupling to local/manual execution.** Large parts of the current workflow are
  intertwined with running code interactively in a local console, which makes batch automation
  difficult without a rework.

## Recent progress

- Added the ability to download session data directly (instead of only working from a
  pre-downloaded zip) and to re-evaluate past sessions.
- Moved the main trial-selection while-loop so it no longer re-lists/re-prompts on every pass
  when running multiple trials back to back.
- Vendored the OpenCap `opencap-processing` codebase into this repo and overlaid the
  Synergy-specific edits (`utils.py`, `utilsKinematics.py`, `Examples/gaitAnalysis-UCM.py`).
- Replaced pipeline step 1 (the manual MATLAB joint-mapping + `getMarkers.py`'s
  forward-kinematics marker-reconstruction workaround) with `xsens_to_opensim.py`, built on
  OpenSim's own OpenSense framework. Also writes `.trc` marker files directly (no MATLAB, no
  marker round-trip) and can write output straight into an existing OpenCap session's own
  folder layout. `getMarkers.py`, `utils_UCM.py`, and `utilsKinematics_UCM.py` were removed as
  dead weight once superseded — see `VENDORING.md` for the full history and reasoning.
- `gait_analysis_UCM.py` (the gait-cycle scoring class) has been supplied. A bug-fixed copy,
  `gait_analysis_UCM_fixed.py`, addresses issues found in review — see `VENDORING.md`.

## Status

The OpenCap base is vendored in and the known Synergy-specific edits are layered on top. See
`VENDORING.md` for what's still missing before this runs end to end.

## Credentials

Do **not** commit credentials to this repo. Use environment variables or a local, gitignored
secrets file instead.
