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

## Known issues / open problems

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
