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

**The model was never posed to match the IMU calibration frame.** Found and fixed 2026-09-02.
Mechanism, evidence and the numbers are in `VENDORING.md` under "The calibration pose was never
set, and the arms paid for it".

`IMUPlacer` computes each body-to-IMU offset against the OpenSim model's **default** pose — it
never solves for the subject's. The calibration row we hand it is the .mvnx's **T-pose** (all 90
trials in this study carry one; none carry an N-pose), and `LaiUhlrich2022`'s default pose is
arms-down. The 90 degrees of shoulder abduction between the two went into the arm IMU offsets, so
IK had to report a walking arm as ~90 degrees abducted. That is gimbal lock for the shoulder's
Euler triplet, and `arm_flex`/`arm_rot` then wound up against the model's own **+/-572.96 degree
(+/-10 rad)** coordinate bounds — roughly three full shoulder revolutions of slack, which is why
the symptom read as "the arm angles are 180 degrees too high" rather than as an obvious failure.

Fixed by posing the model in the calibration frame's own pose before `IMUPlacer` runs
(`xsens_to_opensim.CALIBRATION_POSES`). Checked against Xsens's own `<jointAngle>` solver, which
shares none of this machinery: AN's right forearm pronation is 112.2 deg by Xsens, was 6.6 deg on
the IK route, and is now 115.1 deg; right elbow flexion is 8.5 deg by Xsens, was pinned at 0.02
deg, and is now 6.4 deg. Across-stride arm SDs fall from 2-157 deg to 1-3 deg, the same range as
the marker-based OpenCap route.

**Scope: arms only.** Pelvis and both legs hold the same pose in a T-pose as in the model default,
so their offsets were already right — measured shift on the regenerated exports is under 0.25 deg
(p99). Nothing in the gait metrics, GDI or the synergy index changes. The lumbar coordinates do
move a little, and that is the fix working: `torso_imu`'s tracking residual drops from 1.00 to 0.07
deg RMS once the arm frames stop pulling on the torso in the global IK solve.

**Audited across all six sessions on 2026-09-03.** Upper-body IMU residual 12.23 deg -> 8.10 deg
over 90 trials; lower body identical at 3.60 deg, which is the regression evidence. One trial
regressed: **MS-005's left arm is lost from t = 4.35 s** (humerus residual 16 -> 59 deg RMS) and its
arm/elbow/forearm kinematics must not be used -- its legs are unaffected, so it stays usable for
GDI and the synergy index. KM's right hand tracks poorly in nine trials, before and after, which is
a separate pre-existing defect. Full audit in `VENDORING.md`.

**Any arm, elbow or forearm value produced before 2026-09-02 is superseded.** Pre-fix outputs are
kept per session as `pre-calibration-fix/` rather than deleted. `verify_calibration_fix.py` is the
cohort-wide gate. The `xtoo` route was never affected — it does not run `IMUPlacer`.

**One thing the fix does not solve:** `pro_sup` now reaches the model's 119.75 deg limit for AN.
Xsens puts that subject's forearm pronation at up to 142 deg, so the model's range is genuinely
narrower than the movement rather than the calibration being wrong. It is reported, not widened —
a +/-10 rad shoulder range is exactly what let the original defect hide for two weeks.
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

**Absolute GDI is not on the published normative scale — only relative comparison is safe.**
Our three processed subjects score **80.20 +/- 8.09** on `reduced6` against the control cohort's
**100.0 +/- 10.0**. `reduced6` carries no pelvis terms, so this has nothing to do with the pelvis
convention below. Two explanations fit the same numbers, and nothing in this repo separates them:

- the subjects are genuinely impaired, and the pipeline is sound, or
- this pipeline's kinematics are systematically offset from the optical-mocap cohort the reference
  was built on, and every score we report is ~20 points low.

The offset is not confined to the pelvis: measured against the cohort, `hip_flexion` is off by
-13.47 deg and `fpa` by +10.90, summing to 33.1 deg across the six non-pelvis variables. Full
analysis in `docs/2026-08-31-gdi-vs-ucm-audit.md` section 12.

**What this means in practice.** Trial-to-trial, leg-to-leg and session-to-session comparison was
never in question and stays valid — a common offset cancels. Do **not** report an absolute GDI as
though 100 means what it means in the literature.

**Do not "fix" it by fitting an offset to our own participants.** That was measured and rejected: it
subtracts precisely the impairment GDI exists to measure. The estimator is also three subjects whose
between-subject spread (6.5 deg) is 70% of the offset itself.

**How to settle it — one control subject, one command.** The question is a capture, not a
computation: a subject *known* to be uninjured scores ~100 under the first explanation and ~80 under
the second.

```bash
python validate_control_baseline.py     --session PATH/TO/CONTROL_SESSION     --reference context/gdi_reference_2026-08-27
```

Exit status is the verdict, so it drops into a post-capture script:

| code | verdict | meaning |
| --- | --- | --- |
| 0 | SOUND | scores >= 90; the frame is fine, the cohort is impaired |
| 1 | ACTION REQUIRED | scores <= 85; the pipeline is offset, rescaling needed |
| 2 | INCONCLUSIVE | the 85-90 band, legs disagreeing by more than one normative SD, or too few strides |
| 3 | UNABLE TO RUN | missing reference, invalid session, or a pelvis-bearing feature set |

**`gdi9` is disabled** and raises `GdiFeatureSetDisabledError` from both `get_feature_set` (by name,
the CLI path) and `compute_gdi` (as an object). It adds three frame-mismatched pelvis terms on top
of six already-mismatched ones with no offsetting benefit. `reduced6` is the default and the only
set the project reports through. This is not waivable, unlike `check_digest` — a disabled set's
output is wrong in a known direction, and there is no honest reason to want that number.

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
