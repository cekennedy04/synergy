# Vendoring notes

> **Status note (2026-08-26).** See **[PROVENANCE.md](PROVENANCE.md)** for the current,
> authoritative map of which files are upstream, supervisor-supplied, or ours. This document is
> kept for its detailed history of the 2026-08-14 to 2026-08-17 overlay work; sections below that
> have since been overtaken by events are marked **RESOLVED** or **SUPERSEDED** inline.

This repo vendors the [opencap-org/opencap-processing](https://github.com/opencap-org/opencap-processing)
codebase directly (not a git submodule), unmodified. Synergy-specific edits are added as separate
files rather than overwriting upstream files in place — see "Import-name mismatch" below for what
that means in practice.

- **Upstream commit vendored:** `72b5416bf6172fe3d9b42b01e1a02252362b20fc` (2026-04-24), fetched
  2026-08-14.
- **Upstream's own README** is kept as `README.opencap-processing.md` for reference (install
  steps, conda/OpenSim setup, etc. — still accurate for this repo, just not Synergy-specific).
- To pull a newer upstream snapshot later: clone opencap-processing fresh elsewhere, diff it
  against this repo's untouched files (see "Files NOT modified" below), and re-apply the overlay
  list.

## ⚠ No git commits yet — **RESOLVED**

~~This repo has never been committed to.~~ The repo was committed on 2026-08-17 in exactly the
order recommended below: `cfcf7ad` vendors the untouched upstream baseline referencing the commit
hash above, then `3a568fb` adds the Synergy-specific overlay on top. Diffs against upstream are
now actually checkable rather than resting on this file's word for it, and the
"stays byte-identical to upstream" rule is verified in PROVENANCE.md tier A.

## Files added from `utilsKinematics.zip` (sent 2026-08-14)

Nothing upstream is overwritten in place. Your versions live alongside the stock files as
separate `_UCM`-suffixed copies:

| File | Location | Status |
|---|---|---|
| `utils.py` (yours) | `utils_UCM.py` *(since deleted, `67a4b2f`)* | Byte-identical to upstream HEAD content (only line-ending differed: your copy is LF, upstream ships CRLF). No functional edits detected. |
| `utilsKinematics.py` (yours) | `utilsKinematics_UCM.py` *(since deleted, `67a4b2f`)* | Real edits. See "utilsKinematics_UCM.py diff" below. **Not currently imported by anything** — see "Import-name mismatch" below. |
| `gaitAnalysis-UCM.py` | `Examples/gaitAnalysis-UCM.py` | Added alongside the untouched `Examples/example_gait_analysis.py` it was based on (you said you *added* this one, not replaced). |
| `getMarkers.py` | repo root *(since deleted, `67a4b2f`)* | Added; no upstream equivalent, so nothing to diff against. **Never reviewed in depth until 2026-08-17 — see below.** |

`utils.py` and `utilsKinematics.py` at the repo root are untouched stock upstream files.

### What `getMarkers.py` actually does (reviewed 2026-08-17)

> **HISTORICAL.** `getMarkers.py` was deleted in `67a4b2f`, superseded by `xsens_to_opensim.py`'s
> marker export. The hardcoded-path problems flagged below were never fixed — the file was
> removed instead.

Read in full for the first time on 2026-08-17 — earlier passes only skimmed the top of the file.
It does **not** read Xsens files directly (no `.mvnx`, no Xsens SDK calls). It picks up *after*
Xsens joint angles have already been converted to a `.mot` file (README's pipeline step 1, still
done in MATLAB per the README) and does the "no direct motion-file import" workaround the README's
own "Known issues" section describes: for each of 10 hardcoded trials, it (1) loads a scaled
OpenSim model, (2) drives the model through the `.mot` file's joint angles via forward kinematics,
(3) reads back the resulting global marker positions at every frame and writes them out as a
`.trc` file, then (4) re-runs OpenSim's `InverseKinematicsTool` on that reconstructed `.trc` to
regenerate an `_ik.mot`. That round-trip (FK → synthetic markers → IK again) is what makes a
motion file — whether it originated from OpenCap or from Xsens-via-MATLAB — importable back into
an OpenCap session, since OpenCap's session format expects marker-derived motion data.

**Same class of problem as the `gaitAnalysis-UCM.py` fix, not yet applied here:** lines 63 and 70
hardcode a mapped-drive path (`X:\Alex\UCM Analysis\data\...`) to a specific session folder and
model file, plus a hardcoded `range(10)` trial count. This script won't run against this local
checkout or this repo's `Data/` folder without editing those paths — same category of issue as the
`os.chdir()` fix made 2026-08-16, just not yet addressed here. Flagging, not fixing, per the same
"don't touch your live scripts without being asked" approach used elsewhere in this doc.

## Import-name mismatch — `utilsKinematics_UCM.py` is currently inert

> **SUPERSEDED.** `utilsKinematics_UCM.py` and `utils_UCM.py` were deleted in `67a4b2f` for
> exactly the reason this section diagnoses — nothing ever imported them. Neither replacing the
> root `utilsKinematics.py` nor renaming the import was chosen; the files were removed instead.
> The root `utils.py` / `utilsKinematics.py` remain stock upstream.

`ActivityAnalyses/gait_analysis.py` (and almost certainly its missing `gait_analysis_UCM.py`
counterpart, per its own `from gait_analysis_UCM import gait_analysis` pattern used elsewhere)
does `from utilsKinematics import kinematics` — the plain module name, not `utilsKinematics_UCM`.
So as things stand, anything that runs the gait pipeline will pick up the **stock**
`utilsKinematics.py` at the repo root, not your edited `utilsKinematics_UCM.py` — your
`get_body_angular_velocity` rewrite and the other changes described below won't actually run
until either:
- `gait_analysis_UCM.py` (once you send it) imports `utilsKinematics_UCM` by that name, or
- you decide `utilsKinematics_UCM.py` should replace the root `utilsKinematics.py` after all, at
  which point say so and it's a one-line copy.

Same reasoning applies to `utils_UCM.py`, though it's moot there since its content is identical
to the stock file anyway.

## Files NOT modified (still stock upstream)

Everything, including `utils.py` and `utilsKinematics.py` at the repo root —
`ActivityAnalyses/gait_analysis.py`, `ActivityAnalyses/sts_analysis.py`, `marker_name_mapping.py`,
`utilsAPI.py`, `utilsAuthentication.py`, `utilsPlotting.py`, `utilsProcessing.py`, `utilsTRC.py`,
`OpenSimPipeline/`, `Moco/`, `UtilsDynamicSimulations/`, `Resources/`, `batchDownload.py`,
`example.py`, `example_kinetics.py`, etc.

## Critical gap: `gait_analysis_UCM.py` is missing

> **RESOLVED.** The file was supplied and added in `67a4b2f`. It sits at the repo root as
> `gait_analysis_UCM.py` (not `ActivityAnalyses/`), untouched as supplied. The bug-fixed copy is
> `gait_analysis_UCM_fixed.py`, and `Examples/gaitAnalysis-UCM.py` imports that copy.

`Examples/gaitAnalysis-UCM.py` (line 44) does:

```python
from gait_analysis_UCM import gait_analysis
```

and adds `ActivityAnalyses` to `sys.path`, so it expects a module at
**`ActivityAnalyses/gait_analysis_UCM.py`** — the file you described as "replaced their
`gait_analysis.py` with my `gait_analysis_UCM.py`". **It was not in `utilsKinematics.zip`.**
Right now `ActivityAnalyses/` only has the stock upstream `gait_analysis.py`, so
`gaitAnalysis-UCM.py` will fail to import. This is the top blocker — send that file and it can be
dropped straight into `ActivityAnalyses/gait_analysis_UCM.py`.

## `utilsKinematics_UCM.py` diff (vs. upstream HEAD / the stock `utilsKinematics.py`)

> **HISTORICAL.** The file described below no longer exists (deleted in `67a4b2f`). Retained
> because it records what the supervisor's version differed on, should it ever be resupplied.

Your version is based on an **older upstream commit**, from before two features were added
later: `marker_name_mapping.REVERSE_MARKER_NAME_MAPPING` (marker-name conversion in
`get_marker_dict`) and a `get_body_orientation` method that `get_body_angular_velocity` was
rewritten to depend on (numerical differentiation of orientation instead of the direct
`getAngularVelocityInGround` call your version uses).

Practical effect, **if `utilsKinematics_UCM.py` is ever wired in** (it currently isn't — see
above):
- `get_body_angular_velocity` uses your direct-angular-velocity implementation, not the
  newer orientation-diff one. Functionally different, not obviously wrong — just flagging the
  fork point.
- No marker-name remapping happens in `get_marker_dict`. Only matters if your `.trc` files use
  marker names that need the `_study` suffix mapping — check if that's a live concern for the
  Xsens-derived motion files this pipeline produces.
- `ActivityAnalyses/sts_analysis.py` (sit-to-stand analysis, unrelated to the gait pipeline this
  project uses) calls `get_body_orientation`, which doesn't exist in `utilsKinematics_UCM.py`. It
  would break if it ever imported that file instead of the stock one — it currently doesn't, so
  this isn't live, just noting it so it doesn't surprise anyone later.
- A few stray debug `print()` statements are still in there (`print(trcFilePath)`,
  `print(i)` in the body loop) — harmless, just noisy stdout.
- ~~The `self.modelPath = modelPath` assignment in `__init__` was also dropped relative to
  upstream.~~ **Fixed 2026-08-16** — restored, right before `self.model = opensim.Model(modelPath)`.
- ~~The model-path-resolution block in `__init__` (roughly lines 52-90) got reformatted with
  non-standard indentation.~~ **Fixed 2026-08-16** — reformatted to consistent 4-space
  indentation, matching the rest of the file. Verified it still parses
  (`python -c "import ast; ast.parse(...)"` via `C:\Users\cladi\miniconda3\python.exe`, the only
  interpreter found on this machine — it's not on PATH, use the full path if you need it for
  anything else).

## Other things flagged

- **Hardcoded network path — fixed 2026-08-16.** `Examples/gaitAnalysis-UCM.py` line 37 used to
  `os.chdir()` to a work network share
  (`\\fs2.ric.org\smulab2\alex\projects\opencap\opencap_git\opencap-processing`). Replaced with
  `os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))` — resolves to this
  script's own repo root no matter where it's invoked from or which machine it's on, instead of a
  hardcoded machine-specific path. Preserves the original intent (force cwd to the repo root
  before the relative `sys.path.append` calls) without hardcoding a location.

  **New thing this surfaced, not yet fixed:** line 56, `baseDir = os.path.join(os.getcwd(), '..')`,
  was written assuming cwd ends up at the repo root — so `baseDir` becomes the repo's *parent*
  directory, and `dataFolder = os.path.join(baseDir, 'Data')` on this machine resolves to
  `C:\Users\cladi\Data`, **not** `C:\Users\cladi\synergy\Data` where the downloaded files actually
  are. This was already true under the old hardcoded path too (it pointed at the repo root, same
  off-by-one-directory issue existed there), so it's not something the path fix introduced — just
  something it makes visible now that the script can actually run locally. Worth deciding: move
  `Data/` up a level, or change line 56 to use the repo root directly instead of its parent.

  **Added 2026-08-16:** a one-line assertion right after the `chdir` that the resulting cwd
  actually contains `VENDORING.md`, so if this script is ever copied out of `Examples/` on its
  own (without the rest of the repo), it fails loudly instead of silently `chdir`-ing somewhere
  wrong and failing confusingly later. The old hardcoded UNC path used to fail loudly on its own
  if unreachable; this restores that property without hardcoding a location.
- **Credentials in chat.** You sent a username/password alongside the Google Drive link for the
  OpenCap data zip. Per this repo's own README rule, nothing here stores it — still worth rotating
  that password since it's sitting in conversation history now.

## Tests (`tests/`)

Two files, 5 tests total, verifying the two fixes above without needing OpenSim installed:

- `test_gaitAnalysis_UCM_chdir.py` (3 tests) — the chdir fix, run from several starting
  directories, checked against real subprocess behavior.
- `test_utilsKinematics_UCM_modelpath.py` (2 tests) — **since deleted** in `67a4b2f` as orphaned, along with its subject. Kept deliberately small. Originally written
  as 7 tests (5 parametrized branch cases + a negative case), trimmed after a second-pass review
  pointed out that `utilsKinematics_UCM.py` isn't imported by anything yet (see "Import-name
  mismatch" above), so building out a full branch-coverage suite for currently-dead code was
  disproportionate to the risk. What's left: one smoke test for the actual regression
  (`self.modelPath` missing) and one test looping over all 5 modelName/isMono combinations to
  confirm the indentation reformat didn't change behavior — real coverage of the edit that was
  actually made, without the extra infrastructure weight. Expand this if/when
  `utilsKinematics_UCM.py` gets wired into the pipeline for real.

  That same review also caught that the stub `opensim`/`utils`/`utilsProcessing`/`utilsTRC`
  modules were being written straight into `sys.modules` with no teardown — confirmed to actually
  leak into later tests in the same process (a later `import opensim` would silently get the fake
  module instead of failing normally). Fixed by using pytest's `monkeypatch.setitem` instead,
  which restores `sys.modules` automatically; verified the stubs are gone from `sys.modules` after
  the test file runs.

Run with: `C:\Users\cladi\miniconda3\python.exe -m pytest C:\Users\cladi\synergy\tests -v`

- `test_xsens_to_opensim_mvnx_parsing.py` (4 tests) — see `xsens_to_opensim.py` below. Covers only
  the pure-stdlib `.mvnx` XML parsing (segment/frame extraction, the 3-leading-frame skip,
  quaternion order, ms→s time conversion), against a synthetic fixture built to match the real
  MVNX schema. Does not and cannot test the OpenSim-dependent stages (`build_orientations_sto`,
  `calibrate_model`, `run_imu_ik`) — `opensim` isn't installed on this machine.

## `xsens_to_opensim.py` — new, not part of the vendored/overlaid files above (2026-08-17)

You said the existing `getMarkers.py` + MATLAB pipeline has too many errors and takes too long,
and asked for research into a lighter-weight Xsens → OpenSim conversion as a fresh Python file —
not a fix to the existing scripts. This is a separate, additive file; nothing above was touched
or replaced.

**Design, in short:** skip markers entirely. OpenSim ships its own IMU-orientation-based
pipeline ("OpenSense") built for exactly this — Xsens is one of its two officially supported
input formats. `xsens_to_opensim.py` parses a `.mvnx` file directly (stdlib `xml.etree`, no
extra dependencies), writes an OpenSim orientations `.sto`, then calls `opensim.IMUPlacer` and
`opensim.IMUInverseKinematicsTool` to go straight to a `.mot` — no MATLAB, no manual joint
mapping, no forward-kinematics/marker round-trip. Full reasoning and the source list (opensim-core
C++ headers read directly via `gh api`, the official Rajagopal OpenSense MATLAB example, a
real open-source `.mvnx` parser's actual schema traversal) are in the file's own module
docstring — not repeated here to avoid the two going out of sync.

**Status update 2026-08-17: tested against real data, `.mvnx`-parsing half confirmed working.**
You uploaded a real recording, `0_Bed_to_ShowerChair_M.mvnx` (21MB, 2609 frames). Inspecting it
directly (byte-offset greps + `ET.parse`, not assumed) turned up real structural differences from
what the script originally assumed, all now fixed in `parse_mvnx`:

- The file's root element IS `<frames segmentCount="23" jointCount="22">` directly — no
  `<mvnx>`/`<mvn>`/`<subject>` wrapper, and critically no `<segments>` label list at all. Segment
  *names* now fall back to a hardcoded `STANDARD_23_SEGMENT_ORDER` (cross-checked against three
  independent sources — Xsens's own MVN User Manual, the original Xsens MVN 6DOF paper, and an
  arXiv paper on bridging Xsens MVN to ROS) when no label list is present, only when the segment
  count is the standard 23.
- Only 2 non-motion leading frames (`npose`, `tpose`), not 3 — the original code's fixed
  `frames[3:]` slice would have silently dropped your first real motion frame. Frame selection now
  filters by each frame's own `type="normal"` attribute instead.
- The `time` attribute is confirmed to genuinely be elapsed milliseconds (0, 16, 33, 50...) — the
  original ms→s conversion was already right; the separate `ms` attribute is the one holding a
  large Unix-epoch timestamp, not `time`.
- **New fix, not just a correction:** your file's first `normal` frame is mid-task (this is a
  "bed to shower chair" transfer trial, so frame 0 is very likely not a clean static pose).
  `IMUPlacer` always calibrates off the first row of whatever orientations file it's given, so
  `build_orientations_sto` now writes the file's `tpose` frame (falling back to `npose`) as row 0,
  ahead of the motion data, instead of letting calibration silently use whatever pose the
  recording happened to start on.

Verified end-to-end for the parsing half: `python xsens_to_opensim.py --list-segments
0_Bed_to_ShowerChair_M.mvnx` correctly reports 23 real segment names, 2609 motion frames at 60 Hz,
and that a tpose calibration frame was found. `synergy/tests/test_xsens_to_opensim_mvnx_parsing.py`
still passes (4 tests) against the synthetic fixture.

**Still not verified — the OpenSim-dependent half** (writing the real `.sto` via
`STOFileAdapterQuaternion`, `IMUPlacer`, `IMUInverseKinematicsTool`) has never actually run.
`opensim` isn't installed on this machine yet (you said you'll install it).

**Before trusting this on real data, you still need to:**
1. Edit `SEGMENT_TO_IMU_FRAME` at the top of the file — the Xsens-side keys are now real
   (`STANDARD_23_SEGMENT_ORDER`, confirmed above), but the OpenSim-side values are still the
   7-sensor placeholder from OpenSim's Rajagopal example, not your actual model's IMU frame names.
   That depends on which `.osim` model you calibrate against, which isn't chosen yet.
2. Install OpenSim (`conda install -c opensim-org opensim`) and actually run it once, end to end,
   against this or other known-good data, before relying on it for real analysis.
3. Decide on segment vs. sensor orientation as input (see the main session reply for the
   reasoning) — segment orientation (current default) is ready to use now; sensor orientation
   would need the sensor→segment mapping confirmed from a non-stripped `.mvnx` export or your MVN
   Analyze hardware configuration, since this file's `<sensorOrientation>` data (17 sensors,
   confirmed present) has no label list either.

## Update 2026-08-17 (later same day): `context/` folder — real data, sensor mapping resolved

You added a `context/` folder to the repo with real clinical data (Shirley Ryan AbilityLab study
data — a full Excel per-trial export, `S01_04162026`'s 13 `.xlsx` files, plus the previously
undownloadable large OpenCap/Xsens zips, now grabbed manually). **First thing done: added
`context/`, `*.mvnx`, `*.xlsx`, and `*.crdownload` to `.gitignore`** — this is real subject data
and must never end up in git history. Verified `git status --ignored` shows it excluded before
touching anything else.

This data resolved two of the three "still needs a decision" items above:

- **`SEGMENT_TO_IMU_FRAME`'s OpenSim-side is no longer a placeholder.** Extracted
  `LaiUhlrich2022_scaled.osim` (your actual scaled model) from the OpenCap zip and grepped its
  real `<Body name="...">` elements. Separately, read `IMUPlacer.cpp` directly and confirmed the
  actual mechanism (not guessed): it strips a literal trailing `_imu` off each orientation column
  name and looks for an existing model Body with the remaining name — it creates the IMU frame
  itself, no pre-existing IMU setup needed on the model. So the dict now maps confirmed
  sensor-equipped Xsens segments straight to real body names + `_imu` (`pelvis_imu`, `torso_imu`,
  `humerus_r_imu`, `femur_r_imu`, etc. — 14 entries, up from the original 7-8 item Rajagopal
  placeholder). A few segments (Head, RightShoulder, LeftShoulder) were dropped from the mapping
  since this model has no matching separate body for them.
- **Segment order and sensor availability are both now independently confirmed**, not just
  literature-sourced. `context/S01-001.xlsx`'s "Segment Orientation - Quat" sheet has literal
  column headers ("Pelvis q0", "L5 q0", ...) matching `STANDARD_23_SEGMENT_ORDER` exactly. Its
  "Sensor Orientation - Quat" sheet uses the same 23-segment layout but with `(0,0,0,0)` for
  segments with no physical sensor — checked every column: exactly 17 are real, matching L5, L3,
  T12, Neck, RightToe, LeftToe as the 6 without. That 17-count also independently matches what
  `0_Bed_to_ShowerChair_M.mvnx`'s compact `<sensorOrientation>` element contains (68 = 17×4),
  cross-validating between two unrelated files. New constant `SENSOR_EQUIPPED_SEGMENTS` records
  this.

**New capability added: `source="sensor"` option** on `build_orientations_sto` (and `--source` on
the CLI), alongside the existing `source="segment"` default — lets you actually choose the
raw-sensor-orientation path discussed as the likely-more-accurate option, now that the
sensor→segment mapping is confirmed rather than guessed. **New finding that limits it, for this
specific file:** `0_Bed_to_ShowerChair_M.mvnx`'s tpose/npose calibration frames carry
`<orientation>` and `<position>` only — no `<sensorOrientation>` at all — even though the real
motion frames do. `source="sensor"` now fails loudly with a clear error in that case (raise, not a
silent fallback to calibrating off the first motion frame) rather than repeating the exact
bad-calibration-pose bug `source="segment"` was already fixed for. `source="segment"` still works
fine against this file since its calibration frames do have `<orientation>` data.

Also fixed: `parse_mvnx`'s `.mvnx`-parsing test suite (`tests/`) grew from 4 to 8 tests —
`test_xsens_to_opensim_source_selection.py` (4 tests, opensim stubbed the same way
`test_utilsKinematics_UCM_modelpath.py` does, same `monkeypatch.setitem` cleanup) covers the new
`source` parameter's branches, including the calibration-data-missing failure case above. All
still pass against the real file's actual structure (verified via `--list-segments`, not just the
synthetic fixtures) — 13/13 total.

**Still open:** the compact-slot-order assumption for `.mvnx`'s `<sensorOrientation>` (that its 17
values appear in the same relative body-order as the full 23-segment list, just with the 6
non-sensor segments removed) is inferred from the Excel export's parallel zero-padded structure,
not independently proven for the `.mvnx` binary-compact form specifically — worth a spot-check
once OpenSim is installed and this can actually run.

## Update 2026-08-17 (evening): OpenSim installed, ran end-to-end against real data for the first time

> **⚠ SUPERSEDED 2026-08-24 — the data behind this section was mismatched.**
> Every accuracy figure below was produced by driving IMU orientations from one
> recording through `LaiUhlrich2022_scaled.osim` scaled to a *different* person:
> the OpenCap session used was `subjectID: test1` (a generic OpenCap demo
> session, 1.68 m / 84.4 kg, trials `test1`..`test10`/`Cir12`/`walker11`), while
> the `.mvnx` was an unrelated bed-to-shower-chair transfer found online — a
> different subject performing a different, non-walking motion. Do not quote
> these numbers as this pipeline's accuracy. Real validation against a verified
> matched pair is in **"Update 2026-08-24: real validation"** at the end of this
> file. Kept here unedited as a record of how the error was made and found.

`conda create -n opencap-processing python=3.11` + `conda install -c opensim-org opensim=4.5=py311np123`
(exactly the version this repo's own README specifies) — confirmed installed and importable
(`OpenSim version: 4.5-2023-11-26-efcdfd3eb`).

First real run (`source="segment"`, real `0_Bed_to_ShowerChair_M.mvnx` + real
`LaiUhlrich2022_scaled.osim` extracted from the OpenCap zip) immediately surfaced two real Python
API bugs — exactly the kind source-reading alone can't catch, since the C++/MATLAB API and the
Python bindings don't always use identical method names:

1. **`RowVectorQuaternion` has no `__setitem__` or `.set(col, quat)`.** Fixed by using
   `row.updElt(0, col)` (confirmed to return a live reference, not a copy — mutating it does
   propagate back into the row) and calling `Quaternion.set(component_index, value)` four times
   per element (that method sets ONE of the 4 components — it's inherited from `Vec4`, not a
   set-all-4 call).
2. **`Model.print()` (the C++/MATLAB method name) doesn't exist in the Python bindings** — renamed
   to `Model.printToXML()` there, almost certainly because `print` collides with the Python
   builtin.

After both fixes: **ran successfully end to end**, first on a 2-second smoke-test window, then on
the full 43-second/2609-frame trial. Produced a real `.mot` joint-angle file plus an
`_orientationErrors.sto` tracking-error report. Spot-checked the smoke-test output: `pelvis_imu`
(the calibration-reference segment) tracks almost perfectly (~0.001 rad residual error across the
window); other segments range higher (`femur_r_imu` ~0.22 rad, `calcn_r_imu` ~0.28 rad,
~0.02-0.14 rad for the arms) — plausible for real IMU-IK on real movement, but not something to
call "accurate" without a domain expert's judgment on whether those magnitudes are acceptable for
this clinical use case. Not a code-correctness question at that point, a biomechanics one.

Full-trial run log and outputs are in scratchpad (not the repo — derived-but-still-subject-linked
outputs shouldn't live in git any more than the source data should).

**Timing was never recorded during this run** — the ~5-minute total (parse+write ~1s,
calibrate <1s, IMU IK ~4m58s, i.e. ~115ms/frame) was reconstructed after the fact from output-file
timestamps, not measured directly. Fixed 2026-08-18: `xsens_to_opensim.py`'s `main()` now times
each of the three stages with `time.perf_counter()`, prints them, and writes them to
`<results-dir>/timing.txt` alongside the IK output on every run, so this doesn't need forensic
reconstruction again. Verified with a smoke test (stage functions replaced with fast stand-ins) and
the existing 26-test suite; not re-verified against a real 5-minute run since the original run's
uncalibrated scaled model isn't available in this session to redo it cheaply.

## Update 2026-08-19: re-ran against the real trial with real timing, results reproducible

> **⚠ SUPERSEDED 2026-08-24 — the data behind this section was mismatched.**
> Every accuracy figure below was produced by driving IMU orientations from one
> recording through `LaiUhlrich2022_scaled.osim` scaled to a *different* person:
> the OpenCap session used was `subjectID: test1` (a generic OpenCap demo
> session, 1.68 m / 84.4 kg, trials `test1`..`test10`/`Cir12`/`walker11`), while
> the `.mvnx` was an unrelated bed-to-shower-chair transfer found online — a
> different subject performing a different, non-walking motion. Do not quote
> these numbers as this pipeline's accuracy. Real validation against a verified
> matched pair is in **"Update 2026-08-24: real validation"** at the end of this
> file. Kept here unedited as a record of how the error was made and found.

Re-extracted `LaiUhlrich2022_scaled.osim` (the same real scaled model from the OpenCap session zip,
`OpenSimData/Model/LaiUhlrich2022_scaled.osim`) and re-ran `xsens_to_opensim.py` against the same
real trial (`0_Bed_to_ShowerChair_M.mvnx`) to get a genuine, script-recorded timing instead of the
timestamp-reconstructed estimate above.

**Per-segment orientation error is identical to the 2026-08-17 table above, to the decimal place** —
the pipeline is deterministic and reproducible against the same inputs.

**Timing came out very different this time: 61.8s total** (parse+write 3.1s, calibrate 0.9s, IK
57.8s) versus the ~5 minute figure reconstructed on 2026-08-17 (IK alone was ~4m58s then). No
confirmed cause for the ~5x difference — possibly machine load or one-time overhead (antivirus
scan, disk cache, OpenSim library load) on that first-ever real run, not diagnosed further. Take the
~5-minute number as unreliable and this run's 61.8s, produced by the script's own `timing.txt`
logging rather than reconstructed after the fact, as the better data point — but note it's still
only two data points on one machine, not a benchmark.

**Full 43-second/2609-frame trial: also completed successfully, exit code 0** — mechanically, this
is a real, working, end-to-end pipeline now. But the full-trial orientation-error summary is a more
important result than the "it ran" headline, and it's not uniformly good:

| Segment | mean error | RMS | max |
|---|---|---|---|
| torso_imu | 0.1° | 0.1° | 0.4° |
| pelvis_imu | 5.0° | 7.8° | 26.5° |
| calcn_l_imu | 7.3° | 9.8° | 33.7° |
| radius_r_imu | 10.9° | 12.3° | 33.2° |
| humerus_r_imu | 13.4° | 17.2° | 42.7° |
| humerus_l_imu | 14.8° | 19.8° | 56.1° |
| hand_r_imu | 17.8° | 20.9° | 43.1° |
| radius_l_imu | 18.3° | 21.1° | 42.1° |
| calcn_r_imu | 15.2° | 15.5° | 22.4° |
| hand_l_imu | 20.5° | 23.3° | 48.8° |
| tibia_l_imu | 22.2° | 24.0° | 38.1° |
| tibia_r_imu | 26.4° | 28.2° | 46.5° |
| femur_l_imu | 28.4° | 31.3° | 58.8° |
| femur_r_imu | 29.6° | 31.7° | 51.7° |

Torso and pelvis (the calibration segments) track well throughout, as expected. **Leg segments
(femur/tibia especially) have large, sustained tracking error — 20-32° RMS, up to ~59° at worst —
across the whole trial, not just brief spikes.** This is a real, honest result, not a code bug:
the pipeline ran without errors and produced numerically valid output, but that output's
biomechanical accuracy for the legs during this "bed to shower chair" transfer is questionable.
Possible contributors (not diagnosed, just listed): a single static calibration pose may not
generalize well across a transfer task with large leg movement; soft-tissue artifact/sensor
slippage on the legs during vigorous movement; the unusually large 95.8° heading correction found
during calibration may indicate the calibration pose itself wasn't ideal. Not something to resolve
by writing more code — needs a domain expert's (PT/biomechanist) judgment on whether this is
normal for this task or a real problem, before treating the leg kinematics from this pipeline as
trustworthy for anything clinical.

## Update 2026-08-17 (later): git baseline committed, `gaitAnalysis-UCM.py` rewritten

**Git baseline.** Per this doc's own earlier recommendation, the repo now has real history:
1. `cfcf7ad` — the untouched vendored `opencap-processing` files (everything listed under "Files
   NOT modified" above), as a clean baseline referencing the upstream commit hash.
2. `3a568fb` — the Synergy-specific overlay on top: `xsens_to_opensim.py`, `utils_UCM.py`,
   `utilsKinematics_UCM.py`, `getMarkers.py`, `Examples/gaitAnalysis-UCM.py`, `tests/`, this file,
   README.md, `.gitignore`. `context/`, `Data/`, `*.mvnx`, `*.xlsx` remain gitignored and were
   confirmed via `git status --ignored` to never have been staged.

**`Examples/gaitAnalysis-UCM.py` rewritten (commercial-viability / quality-review pass).** Full
rationale is in the file's own module docstring now (kept there, not duplicated here, to avoid the
two drifting apart) — summary:
- Removed ~810 lines of fully inactive, commented-out GDI (Gait Deviation Index) scoring code.
  Never reachable, depended on `matrix.csv`/`perGaitCycle.csv`/`controlCalc.csv` files that don't
  exist in this repo, and was internally inconsistent (checked for `matrix.csv`, opened
  `matrix_ms_reduced.csv`). Recoverable from git history (the commit before this rewrite) if ever
  needed.
- Fixed: left-leg individual gait curves were computed and their scalars printed, but never
  written to CSV — only the right leg was saved. Both are now saved. **Unexercised, unverified**
  — this needs a real run against real data to confirm the left-leg CSV is numerically sane.
- Fixed: the 'E' (evaluate downloaded data) menu path never set `subjid`/`savpath` at all (only
  'Z' did) — first-action 'E' would NameError; 'E' after a prior 'Z' would silently reuse the
  wrong save location. Also fixed 'E''s `baseFolder` reconstruction, which re-derived the already-
  known selected folder via the same `rfind("_")` slicing 'Z' uses — broken for UUID session IDs,
  which contain no underscores.
- Session-ID / subject-ID / zip-root parsing rewritten from chained `str.find`/`rfind` slicing to
  explicit regex against OpenCap's own `OpenCapData_<uuid>` naming, addressing README's
  "Session ID parsing is inconsistent" known issue directly.
- `dataFolder` fixed to resolve inside the repo root (`<repo>/Data`) instead of the repo's parent
  — matches `.gitignore`'s `Data/*` entry, which only makes sense if `Data/` lives in the repo.
- The whole file used to run its interactive prompt loop immediately at import time (module-level
  code, no `if __name__ == '__main__':` guard) — nothing in it was importable or unit-testable, and
  importing it for any reason would hang a process waiting on `input()`. Now split into functions
  behind a real entry point, with the `gait_analysis_UCM`/`opensim`/`utils` imports deferred into
  the functions that actually need them (same pattern `xsens_to_opensim.py` already uses) — so
  path parsing, trial discovery, and the CSV export shape are all testable without OpenSim
  installed and without `gait_analysis_UCM.py` existing. See
  `tests/test_gaitAnalysis_UCM_rewrite.py` (13 new tests, all passing).
- Added a non-interactive batch mode (`--zip`/`--data-dir` plus `--trial`/`--all-trials`) — this
  is the automation this project's own README asks for ("loop through a batch of recordings ...
  without hand-driving every step"), which the interactive-only version never provided.
- The foot-progression-angle math itself (`compute_foot_progression_angles`, formerly `getpelvis`)
  is **UNCHANGED** — same operations, same order, same +/-5° per-foot offset (still undocumented,
  still not re-derived, just preserved and named as `FOOT_ROTATION_OFFSET_DEG`). This could not be
  re-verified against the pre-rewrite version's numeric output this session — do that (real
  OpenSim run, real session data, diff the `.mot`/CSV output against a pre-rewrite run) before
  trusting this over the original for anything clinical.
- **Still blocked**: `gait_analysis_UCM.py` is still missing (see "Critical gap" above) — this
  rewrite makes everything *around* that dependency correct and testable, but the file itself
  still needs to be supplied before the pipeline can run end to end.

Full test suite after the rewrite: `26 passed` (13 pre-existing + 13 new), run via
`C:\Users\cladi\miniconda3\python.exe -m pytest C:\Users\cladi\synergy\tests -v`.

## Update 2026-08-19: response to your supervisor's critique of `xsens_to_opensim.py`

Your supervisor's notes on the original pipeline description ("New: Xsens .mvnx -> [this script]
-> orientations file (.sto) -> [opensim.IMUPlacer, **one static calibration frame**] -> calibrated
model -> [opensim.IMUInverseKinematicsTool] -> .mot directly, **no markers at all**") raised two
concrete gaps and flagged the calibration approach itself. This update addresses the first two
directly and turns the calibration concern into a quantified, evidence-backed finding rather than
an open question.

### 1. Marker/`.trc` output -- "can we save marker positions in a sto file then take markers and
put into trc"

`xsens_to_opensim.py` gained a 4th, optional pipeline stage: `get_marker_trajectory()` +
`write_trc()` (wired together as `write_markers_trc()`, enabled via `--trc-path`). It drives the
calibrated model through the IK `.mot` output frame by frame (forward kinematics only, no muscle
dynamics) and reads back every `Marker` in the model's `MarkerSet`, writing a standard `.trc` file
-- the format OpenCap's own gait-event-detection code actually consumes (per README's "No direct
motion-file import" issue and `getMarkers.py`'s existing manual version of this).

**Deliberately not a port of `getMarkers.py`.** That script has a real unit bug: it calls
`np.radians()` on every coordinate column indiscriminately, including the translational
`pelvis_tx/ty/tz` columns (meters, not degrees), then papers over it with an ad hoc `+=
pelvis_tx`/`+= pelvis_ty` correction on the resulting marker position that only covers two of the
three translational coordinates (`pelvis_tz` is never corrected). The new version instead reads
each `Coordinate`'s real `MotionType` (`osim.Coordinate.Rotational` vs `.Translational` -- verified
against the actual Python bindings, not assumed) and only converts degrees to radians where that's
actually correct, and matches `.mot` columns to model coordinates by name rather than positional
index, so it doesn't need `getMarkers.py`'s manual "skip a slot for constrained coordinates"
bookkeeping (`coordinate.isDependent(state)` is checked directly instead).

Verified against real data: ran the full 4-stage pipeline against `0_Bed_to_ShowerChair_M.mvnx`,
produced a real `.trc` with all 43 markers in OpenCap's own `_study` naming convention, 300 frames,
no NaNs, coordinate values in a plausible +/-0.7 to 1.5 m range. 3 new unit tests cover the
pure-Python `.trc` writer (header format, row values, frame-rate derivation); the OpenSim-dependent
half (`get_marker_trajectory`) is only verified by that real run, same pattern as
`build_orientations_sto`/`calibrate_model`/`run_imu_ik` above.

### 2. Xsens's own joint kinematics -- "Joint kinematics are given by xsens already - dont need
more pipeline to do this"

True, and now used: the real `.mvnx` already carries Xsens's own `<jointAngle>` (66 = 22 joints x 3
DOF per frame) and `<centerOfMass>` (3 values/frame) -- computed by Xsens's own engine, independent
of this script's IMUPlacer/IK conversion entirely. `parse_mvnx` now extracts both.

The 22-joint order and the per-joint 3-DOF axis order were **not guessed**: structurally, 23
segments in a tree rooted at Pelvis implies exactly 22 parent-child joints (matching the file's own
`jointCount="22"`), giving `STANDARD_23_SEGMENT_ORDER` minus the root as a well-justified default --
then confirmed directly against `context/S01-001.xlsx`'s real "Joint Angles ZXY" sheet for this
exact subject/suit: its literal column headers ("L5S1 Lateral Bending", ..., "hip_add_r,
hip_rot_r, hip_flex_r", ..., "ballfoot_flex_l") match this order exactly, all 22 joints, 3 columns
each. Also confirmed the per-DOF order is **[abduction/adduction, internal/external rotation,
flexion/extension]** -- flexion is the *third* value per joint, not the first, which would have been
an easy wrong guess. New constants: `STANDARD_22_JOINT_ORDER`, `JOINT_ANGLE_DOF_NAMES`. 4 new tests
cover extraction, DOF-order, the missing-element-yields-None case, and the wrong-length error case.

### 3. The calibration concern, quantified: leg-tracking error scales with distance from the
calibration pose

> **⚠ SUPERSEDED 2026-08-24 — the data behind this section was mismatched.**
> Every accuracy figure below was produced by driving IMU orientations from one
> recording through `LaiUhlrich2022_scaled.osim` scaled to a *different* person:
> the OpenCap session used was `subjectID: test1` (a generic OpenCap demo
> session, 1.68 m / 84.4 kg, trials `test1`..`test10`/`Cir12`/`walker11`), while
> the `.mvnx` was an unrelated bed-to-shower-chair transfer found online — a
> different subject performing a different, non-walking motion. Do not quote
> these numbers as this pipeline's accuracy. Real validation against a verified
> matched pair is in **"Update 2026-08-24: real validation"** at the end of this
> file. Kept here unedited as a record of how the error was made and found.

Your supervisor's own framing ("one static calibration frame") turns out to name the actual
mechanism behind the femur/tibia tracking-error finding from 2026-08-17 (20-32 deg RMS, worst of
any segment), not just a design choice worth flagging. Used the newly-added Xsens joint-angle data
to test it directly, against the real full 43-second trial:

- Correlation between Xsens's own `jRightKnee` flexion angle and this pipeline's `tibia_r_imu`
  orientation tracking error, over time: **0.97**. For `femur_r_imu`: **0.94**.
- When Xsens's own data says the knee is nearly straight (bottom quartile, <32 deg flexion): mean
  tibia tracking error is 12 deg.
- When Xsens's own data says the knee is well bent (top quartile, >70 deg flexion): mean tibia
  tracking error is 36 deg -- three times worse.

Ruled out simpler explanations first: the raw Xsens segment-orientation data fed into the `.sto`
file (the same data Xsens's own `jointAngle` is computed from) shows 12-97 deg of real relative
femur/tibia rotation over the trial, so the signal isn't missing upstream. `femur_r_imu` and
`tibia_r_imu` are correctly separate, correctly attached frames in the calibrated model (checked
directly in the XML), with nearly-identical calibration offsets from each other -- exactly what
you'd expect from calibrating on a standing, straight-leg T-pose, not a mixup. `knee_angle_r`'s
coordinate range is 0-140 deg, not locked or clamped in a way that would explain it sitting at
0.03-8.8 deg throughout.

**What's left standing:** a single static calibration frame anchors the model well when the real
pose is near that reference (straight leg) -- consistent with torso/pelvis (the calibration
reference itself) tracking almost perfectly throughout. The further the real knee moves from that
reference, the less a fixed calibration offset plus a flexion-only knee DOF can explain the true 3D
relative rotation between the two IMUs, and the correlation above shows that degradation is not
subtle. For a bed-to-shower-chair transfer specifically -- large intentional knee excursion -- this
is close to a worst case for a single static-pose calibration.

This reframes the earlier "leg accuracy is questionable, ask a biomechanist" finding into a
specific, testable one: **error should track deviation from the calibration pose, not just anatomical
location.** That's something a domain expert can act on (e.g. deciding whether a functional/dynamic
calibration, or a mid-range calibration pose, is worth pursuing) rather than an unexplained number.
No code fix attempted here -- picking a different calibration strategy is a methodological decision,
not a bug fix, and shouldn't be made unilaterally in code.

### Still open from your supervisor's notes: internal joint torques ("look into internal joint
torque inside of knee and hip")

Not started. `opensim.InverseDynamicsTool` is the right tool for this, but it typically needs
ground-reaction-force data to produce physically meaningful torques for a weight-bearing task like
this transfer, and no force-plate/GRF data exists anywhere in this project's data as of this
writing. Needs a decision: is GRF data available or planned, or is this meant to run without it
(e.g. for the non-weight-bearing portions of a transfer, or as a rough estimate accepting that
limitation)?

## Update 2026-08-19 (later): output paths made session-compatible, proven against the real
`kinematics` class -- plus a real login-coupling discovery

Two things prompted this: the `.trc` stage needed to be automatic (was opt-in via `--trc-path`,
now always runs unless `--no-trc`), and the output paths needed to actually match what the
older, unmodified OpenCap-derived code expects, not just live wherever this script felt like
writing them.

**New: `resolve_session_output_paths(session_dir, trial_name, model_file=None)`.** Read directly
out of `utilsKinematics.py`'s `kinematics.__init__` (model + motion path construction) and
`get_marker_dict` (marker path construction) -- not guessed -- to get the exact layout:

- model: `<session_dir>/OpenSimData/Model/<name>.osim` (auto-discovered if exactly one `.osim`
  is there; pass `model_file` explicitly for a "mono" session with per-trial model subfolders,
  which this doesn't replicate)
- motion: `<session_dir>/OpenSimData/Kinematics/<trial_name>.mot`
- markers: `<session_dir>/MarkerData/<trial_name>.trc`

Wired into `main()` as `--session-dir`/`--trial-name` (used together; explicit `--results-dir`/
`--sto-path`/`--trc-path`/`model_file` still override individual paths if given). 5 new tests
cover the pure-path-construction logic (correct layout, explicit-model-file bypass, zero/multiple
`.osim` files raising).

**Real bug this surfaced and fixed:** `build_orientations_sto` never created its own output
directory before writing the `.sto` file. Never mattered before because every prior run's
`--sto-path` pointed at a directory that already existed by coincidence (cwd, or a scratch folder
created for something else). Running in session mode against a fresh mock session
(`OpenSimData/Kinematics/` not yet created) failed immediately with `IMUPlacer`'s C++ layer
throwing "File ... does not exist" -- a real, reproducible bug, not a hypothetical. Fixed with one
`Path(sto_path).parent.mkdir(parents=True, exist_ok=True)` line before the write.

**Proven, not just path-matched:** built a mock OpenCap session folder (using the real
`LaiUhlrich2022_scaled.osim` extracted earlier from the actual session zip), ran this pipeline
against it in session mode, then loaded the result with the actual, unmodified
`utilsKinematics.kinematics` class -- the same class `gait_analysis_UCM.py` subclasses. It worked:
35 coordinates x 301 frames from the `.mot`, 43 correctly-named markers from the `.trc`. This is
the first time any output from this pipeline has been consumed by the older OpenCap-derived code,
not just produced and inspected standalone.

**Real discovery made along the way: importing `utilsKinematics` forces an OpenCap login, even for
purely local analysis.** `utils.py` (unmodified, stock) runs `API_TOKEN = get_token()` at *module
import time* (not lazily, not only when an API call is actually needed). `get_token()` falls back
to `getpass.getpass()` -- an interactive terminal prompt -- when no `API_TOKEN` is set via
environment variable or `.env` file. Since `utilsKinematics.py` unconditionally does `import
utils`, and `gait_analysis_UCM.py` inherits from `kinematics`, **merely importing
`gait_analysis_UCM` blocks on a credential prompt**, even though nothing in `kinematics.__init__`,
`get_coordinate_values`, or `get_marker_dict` ever makes a network call. This is very likely the
concrete mechanism behind the "have to log in every time" complaint in the original project notes
-- not a vague inconvenience, a specific line of code (`utils.py:41`). Worked around here for
testing by setting a dummy `API_TOKEN` env var (bypasses the prompt without needing a real token,
since nothing exercised here actually calls the API) -- not a fix, since these are the coworker's
files ("only make copies" still applies); flagging for a real decision on whether this coupling
should be loosened for the Xsens-only, no-download use case.

**Also noted:** `gait_analysis_UCM.py`'s `__init__` doesn't forward a `modelName` override to
`kinematics.__init__` -- it only passes `lowpass_cutoff_frequency_for_coordinate_values`. So
without a real OpenCap session's own metadata file (which supplies the model name automatically),
`gait_analysis_UCM` can't be instantiated directly against a synthetic/mock session the way the
lower-level `kinematics` class can. Not a blocker for real usage (a genuine downloaded OpenCap
session already has this metadata; Xsens-derived output written into an existing real session,
per README's original plan, would too) -- just not exercised by the mock session used for this
test.

### What's kept vs. what this pipeline makes unnecessary

**Kept, still doing real work:**
- `utilsKinematics.py`'s `kinematics` class -- proven compatible above, unmodified.
- `gait_analysis_UCM.py`'s actual gait-cycle/scalar-computation logic -- once instantiated, this
  is the real analysis; nothing here replaces it.
- The OpenCap session directory convention itself (`OpenSimData/Model|Kinematics`, `MarkerData`)
  -- this pipeline now writes into it rather than working around it.

**Superseded, for the Xsens path specifically:**
- `getMarkers.py`'s forward-kinematics marker-synthesis loop -- `get_marker_trajectory`/
  `write_markers_trc` (2026-08-19, earlier this session) does the same job without the
  `np.radians()`-on-translational-coordinates bug.
- The MATLAB joint-mapping step -- `build_orientations_sto` + `IMUPlacer` +
  `IMUInverseKinematicsTool` (2026-08-17) replace it entirely.

**Still real gaps, not yet resolved:**
- The import-time login coupling above.
- `gait_analysis_UCM.py` still needs `pandas`/`scipy`/`matplotlib`/`requests`/`pyyaml`/
  `python-decouple`/`maskpass` installed in whatever environment runs it -- installed in the
  `opencap-processing` conda env during this session's testing (pinned to `numpy==1.23.5`,
  `scipy==1.10.0`, `pandas==2.0.3`, `matplotlib==3.7.3` -- an unpinned `pip install pandas scipy`
  silently upgraded numpy to 2.x mid-session and broke the OpenSim bindings entirely; fixed by
  reinstalling everything pinned together in one transaction. Worth remembering if installing
  anything else into this env later: always pin numpy explicitly alongside it).

## Update 2026-08-19 (evening): found and fixed the actual root cause of the leg-accuracy problem
-- `base_heading_axis` default was wrong

> **⚠ SUPERSEDED 2026-08-24 — the data behind this section was mismatched.**
> Every accuracy figure below was produced by driving IMU orientations from one
> recording through `LaiUhlrich2022_scaled.osim` scaled to a *different* person:
> the OpenCap session used was `subjectID: test1` (a generic OpenCap demo
> session, 1.68 m / 84.4 kg, trials `test1`..`test10`/`Cir12`/`walker11`), while
> the `.mvnx` was an unrelated bed-to-shower-chair transfer found online — a
> different subject performing a different, non-walking motion. Do not quote
> these numbers as this pipeline's accuracy. Real validation against a verified
> matched pair is in **"Update 2026-08-24: real validation"** at the end of this
> file. Kept here unedited as a record of how the error was made and found.

Your supervisor's benchmark (a working Xsens-to-OpenSim translation should show only a few degrees
of error) was the right pushback -- the earlier framing of the 2026-08-17 leg-tracking-error
finding as "a real limitation of single-frame IMU calibration, needs a domain expert's judgment"
undersold it. Most of it was a wrong default value, not an inherent limitation.

`calibrate_model`'s `base_heading_axis` defaulted to `'z'` -- the axis used in OpenSim's own
official Rajagopal OpenSense reference example, which is where this script's calibration call was
modeled from. It's specific to that example's sensor mounting convention, not a universal default.
For this file/model, `'z'` produces a **95.8 degree heading correction** during calibration -- a
number flagged as suspicious back on 2026-08-17 but never actually chased down. Tested all 6 axis
options directly against the real trial:

| axis | heading correction |
|---|---|
| `x` | **5.8 deg** |
| `-x` | -174.2 deg |
| `y` | -90.0 deg |
| `-y` | 90.0 deg |
| `z` (old default) | 95.8 deg |
| `-z` | -84.2 deg |

`x` is the obvious outlier -- every other option is 84-174 degrees, a huge, physically implausible
correction for a calibration pose that's just "stand roughly facing some direction." Changed the
default to `x` and re-ran the full 43-second trial:

- **`knee_angle_r` now ranges 0.1-100.7 degrees** (was 0.03-8.8 degrees) -- matching Xsens's own
  jointAngle range (2.6-97.5 degrees) closely for the first time. This is the actual fix for the
  "knee stays flat" finding from earlier today, not just a related observation.
- Overall RMS tracking error across all 14 IMUs: **20.7 -> 16.4 degrees**. Pelvis (the calibration
  reference) improved from 7.8 to 0.1 degrees. Tibia improved the most (tibia_r: 28.2 -> 9.3 deg;
  tibia_l: 24.0 -> 5.3 deg).
- **Not fully resolved**: femur_r (20.4 deg) and calcn_r/calcn_l (24.8/7.1 deg -- calcn_r actually
  got worse, 15.5 -> 24.8) are still elevated, and arm segments (humerus/radius/hand) barely moved
  (17-29 deg range both before and after) -- heading-axis was one real bug, evidently not the only
  contributor. The T-pose-vs-model-default-pose mismatch flagged earlier (calibration pose has arms
  out; this model's default pose has arms down) is a plausible separate contributor specifically
  for the arms, not yet tested.

Changed `--base-heading-axis`'s default from `'z'` to `'x'` in `xsens_to_opensim.py`. Also fixed a
real CLI bug surfaced while testing every axis option: `--base-heading-axis -x` (space-separated)
is parsed by argparse as an unrecognized `-x` option, not a value -- negative axes need
`--base-heading-axis=-x` (`=` syntax). Documented in the flag's own help text rather than fixed in
argparse itself, to avoid a bigger parsing rework for a one-line workaround.

**Still open:** femur_r/calcn_r/calcn_l/arms remain elevated. Worth testing next: whether the
T-pose calibration frame (vs. npose) explains the arm error specifically, and whether `base_imu`
other than `pelvis_imu` changes the leg picture. Both are cheap to test (same pattern as the axis
sweep above) but not done yet this session.

## Update 2026-08-19 (later still): independent second opinion from Codex on file-by-file usability

Ran `/codex` (OpenAI Codex, an independent model with no memory of this session's earlier work)
against the whole repo, asked specifically what's usable, what needs changes, and what's dead
weight. Full findings below; three real bugs in `xsens_to_opensim.py` fixed immediately since they
were cheap and unambiguous. Findings about `gait_analysis_UCM.py` and `Examples/gaitAnalysis-UCM.py`
are reported, not fixed -- `gait_analysis_UCM.py` is the coworker's file (same "only make copies"
rule as `getMarkers.py`/`utils_UCM.py`), and none of this was requested as a fix yet.

**Fixed immediately (our own code, cheap, unambiguous):**
- `write_trc()` didn't validate `times` and `positions` were the same length -- `zip()` would
  silently truncate to the shorter one, leaving the `.trc` header's `NumFrames` disagreeing with
  the actual row count. Now raises. New test:
  `test_write_trc_rejects_mismatched_lengths`.
- `parse_mvnx`'s `<centerOfMass>` extraction accepted any nonempty length instead of validating
  exactly 3 values (x, y, z). Now raises on anything else. New test:
  `test_wrong_center_of_mass_length_raises`.
- The module docstring's "WHAT THIS SCRIPT DOES NOT DO YET" section was stale -- still said the
  OpenSim-dependent half "has still never been run," written before the extensive real runs
  documented above. Rewritten to a current STATUS section pointing at this file for the full
  history, plus a shorter, accurate "still open" list (remaining tracking error, `source="sensor"`
  still experimental).

Full test suite: 40 passed (was 38).

**Reported, not fixed -- `gait_analysis_UCM.py` (coworker's file, not yet reviewed by anyone
before this):**
- **Not actually safe for unattended batch runs**, which matters directly for
  `Examples/gaitAnalysis-UCM.py --all-trials`: a failed event-order check calls `input()`
  (line 968), and manual event entry prompts 4 more times (lines 783-786). Either will hang a
  batch run waiting on stdin that nothing is providing.
- **The foot-progression-angle inputs are computed but functionally unused.** `fpa_r`/`fpa_l` are
  inserted into the coordinate dataframe (lines 68-69) but nothing downstream reads either column
  -- the driver's own scalar/export list excludes them (driver lines 128-141). The FPA computation
  step runs for no effect on any reported metric.
- Auto-trim recovery can `IndexError` on short recordings (lines 940-944) and its retry loop has
  no real termination condition on persistent failure (lines 998-1005).
- If no gait-event peaks are found, auto-leg-selection indexes `rHS[-1]`/`lHS[-1]` (lines
  1030-1035) before checking whether either list is actually empty.
- `compute_correlations()` is broken at its own default: `cols_to_compare=None` becomes
  `df1.columns` while `df1` is still empty at that point, so it collects nothing and divides by
  zero (lines 567-568, 607). Separately, it claims to interpolate to 101 rows but only fills
  missing values -- it doesn't resample (lines 580-581).
- Center of mass is computed twice with different filters: the columns inserted into
  `coordinateValues` use a 10 Hz low-pass (lines 99-103), while `comValues()` uses whatever
  filter was passed in, no forced default (lines 107-115) -- the exported COM and any metric
  computed from `comValues()` can silently disagree with each other.
- `sys.path` is modified relative to the caller's current working directory (lines 21-22) --
  works today only because the rewritten driver happens to set cwd correctly first; fragile if
  the class is ever imported directly.
- Confirmed positive: it imports the stock, working `utilsKinematics` (line 30), not the inert
  `_UCM` fork -- consistent with the import-mismatch finding from 2026-08-14.

**Reported, not fixed -- `Examples/gaitAnalysis-UCM.py`:**
- `--data-dir` batch mode still isn't actually offline: it forces an OpenCap API lookup/download
  for every trial, even ones already downloaded locally (lines 494-504) -- meaning it still hits
  the import-time login coupling documented above, defeating the point of a local batch mode.
- `discover_trials()` recursively picks up any `.mot` anywhere under the selected folder (lines
  208-216) instead of scoping to `OpenSimData/Kinematics` -- risk of picking up an unrelated or
  stale `.mot` from elsewhere in a session folder.
- Its own docstring/comments are stale -- still say `gait_analysis_UCM.py` is missing (lines
  80-86, 320-323), true when written, not true since it was supplied this session.

**Dead weight, confirmed independently (matches this session's own earlier analysis):**
- `getMarkers.py` -- fully superseded by `get_marker_trajectory()`/`write_markers_trc()`, and
  independently confirmed unsafe: wrong documented array shape vs. actual usage (lines 18-24,
  54-56), a hardcoded 10-trial batch with machine-specific `X:` paths that runs at import time
  (lines 61-70), and the `np.radians()`-on-translational-coordinates bug with its incomplete
  `pelvis_tx`/`pelvis_ty`-only correction (not `pelvis_tz`) called out earlier (lines 132, 136).
- `utils_UCM.py` -- confirmed a byte-for-byte duplicate of stock `utils.py` (matches the
  2026-08-14 finding), and nothing imports it.
- `utilsKinematics_UCM.py` -- confirmed inert: `gait_analysis_UCM.py` imports stock
  `utilsKinematics` (line 30), not this fork, so its edits (the direct-angular-velocity
  `get_body_angular_velocity` implementation, no marker-name remapping) never actually run.
  Behind current upstream and missing `get_body_orientation`. Recommendation: delete, or keep
  purely as reference with a comment explaining it's unused -- retaining it live invites someone
  wiring it in later and accidentally regressing behavior nobody's tested.

**Not acted on yet:** whether to actually delete the three dead-weight files, and whether/when to
fix the `gait_analysis_UCM.py` bugs above (blocking real batch-mode use, but it's the coworker's
file) are both open decisions, not made unilaterally here.

## Update 2026-08-20: dead weight deleted; bug-fixed copy of `gait_analysis_UCM.py` created

Both open decisions from the entry above were resolved by direct instruction.

**Deleted:** `getMarkers.py`, `utils_UCM.py`, `utilsKinematics_UCM.py`, and
`tests/test_utilsKinematics_UCM_modelpath.py` (its own test, now orphaned). Confirmed before
deleting that nothing else imports any of them (`grep` across `.py` files) — `README.md` had one
descriptive mention, updated rather than left stale. Full test suite: 38 passed (was 40; the two
lost were `test_utilsKinematics_UCM_modelpath.py`'s own).

**`gait_analysis_UCM_fixed.py`** — a copy, not an in-place edit (`gait_analysis_UCM.py` stays
untouched, same rule as `utils.py`/`utilsKinematics.py`). Every edit is documented in the new
file's own module docstring (so it travels with the code, not just this doc) — summarized here:

1. `sys.path.append('../')`/`'./'` were relative to the caller's cwd. Now derived from `__file__`.
2. Two blocking `input()` call sites would hang `--all-trials` batch mode: the "enter gait events
   manually?" prompt and `manual_steps()`'s 4 further prompts. New `allow_manual_entry=True`
   constructor arg (default preserves today's interactive behavior; `False` raises a clear
   exception instead of blocking).
3. `ntrims=round(seshlen/.2)-2` could be ≤0 for a short trial, making `trimarray[0]=-1` raise an
   opaque `IndexError`. Now raises a clear, descriptive exception.
4. The auto-trim retry loop's only "termination check" reassigned a variable to its own value —
   a no-op. The loop could run past the end of `trimarray` and crash uncaught. Now raises clearly
   once attempts are exhausted.
5. Auto leg-selection indexed `rHS[-1]`/`lHS[-1]` before checking either was non-empty — a real
   `IndexError` if peak detection found zero heel-strikes. Now checks first, raises clearly.
6. `compute_correlations()`'s `cols_to_compare=None` default resolved against a still-empty
   `df1`, so the default always matched nothing and `len(correlations)` was 0 —
   `ZeroDivisionError` on literally the first no-argument call. Fixed so `None` means "compare
   everything." Also fixed a latent bug where `corresponding_col` from a previous iteration could
   be reused when a column matched neither `_r` nor `_l`, and corrected a docstring/comment that
   claimed 101-row resampling when `.interpolate()` only fills internal gaps (row counts already
   matched by construction here, so this was a wrong comment, not a separate numeric bug).
7. Center of mass was computed twice with two different, undeclared filter settings (hardcoded
   10 Hz for the exported CSV columns, unfiltered-or-whatever-was-passed for internal use by
   `compute_gait_speed` etc.) — the exported COM and the COM actually used for gait-speed disagreed
   with each other. Both now consistently use `self.lowpass_cutoff_frequency_for_coordinate_values`.
8. `find_nearest(array, value)` was missing `self`/`@staticmethod` — dead code (never called
   anywhere in this file), fixed for correctness, still unused.
9. Found by testing, not by the Codex review: `modelName` wasn't forwarded to
   `kinematics.__init__`. Without it, loading any session lacking a full OpenCap-downloaded
   metadata file (e.g. one written by `xsens_to_opensim.py --session-dir`) was impossible. Added
   as a constructor parameter, passed through.

**Deliberately not changed:** the `fpa_r`/`fpa_l` unused-value issue Codex flagged. This file
correctly stores them as columns; the actual gap is that `Examples/gaitAnalysis-UCM.py`'s own
scalar/export list never reads them back out. Fixing that means deciding what should consume
them — a product decision, not something to guess at in a bug-fix pass.

**Verified against real data, not just syntax-checked:**
- Imports cleanly against the real `opencap-processing` conda env (`opensim`, `pandas`, `scipy`,
  etc. all present).
- Instantiated directly against this session's own real pipeline output (the mock OpenCap session
  with `xsens_to_opensim.py`'s real `.mot`/`.trc`, `modelName="LaiUhlrich2022_scaled"`,
  `allow_manual_entry=False`) — ran cleanly through kinematics/marker loading, coordinate values,
  and center-of-mass computation, then hit the new edit-#5 guard with a clear message ("No
  heel-strike events detected for one or both legs") instead of the original's opaque
  `IndexError`, because the 5-second bed-transfer clip isn't a walking trial. That's the *expected*
  outcome for this data — the point was confirming `allow_manual_entry=False` doesn't hang and the
  failure is legible, both of which it did.
- `find_nearest` and `compute_correlations()` (called with no arguments, the exact call that used
  to `ZeroDivisionError`) verified directly: `compute_correlations()` now returns a real computed
  correlation instead of crashing.
- **Not covered by the base-env `pytest tests` suite** — same as the original `gait_analysis_UCM.py`
  and `utilsKinematics.py` before it, this file's import chain needs `opensim`/`requests`/`yaml`/
  `python-decouple`/`maskpass`, none of which are in the base env the main suite runs under.
  Verification above was done directly in the `opencap-processing` conda env instead of forcing
  artificial stubbing into the base suite for marginal benefit.

**Not done:** re-running this against a real walking trial with clean heel-strikes (none exists in
this project's data yet — only the bed-transfer clip) would be the actual happy-path test. Worth
doing once real gait data is available.

## Update 2026-08-20 (later): FPA made a real, reported metric — and the driver now actually uses
the fixed copy

Your instruction: your supervisor did his own calculations for foot progression angle, so it needs
to stay in the code as a meaningful, reported metric — not silently computed and discarded, which
is what the FPA finding above described. The underlying math in
`compute_foot_progression_angles()` (`Examples/gaitAnalysis-UCM.py:230-313`) is **completely
unchanged** — only what happens to its output after computation changed.

**`gait_analysis_UCM_fixed.py`:** new `compute_foot_progression_angle()` method (10th edit to this
file, added after the copy was already created for the Codex-review fixes) — mean FPA for the
ipsilateral leg per gait cycle, in degrees, following the exact same pattern as
`compute_gait_speed`/`compute_cadence` (whole-cycle mean, then averaged across strides). Reads the
`fpa_r`/`fpa_l` columns that were already being stored in `coordinateValues` but never read back
out.

**`Examples/gaitAnalysis-UCM.py`:**
- `SCALAR_NAMES` gained `'foot_progression_angle'`, so it's now computed and included in
  `results['scalars_r']`/`results['scalars_l']` by default, same as `gait_speed`/`stride_length`/etc.
- `JOINT_NAMES` gained `'fpa_r'`, `'fpa_l'`, so the full per-gait-cycle FPA waveform (not just the
  mean) also lands in the exported per-gait-cycle curves CSV alongside every joint angle.

**Critical fix this surfaced: the driver was still importing the wrong file.**
`run_gait_analysis()` did `from gait_analysis_UCM import gait_analysis` — the *original*,
un-fixed file — not `gait_analysis_UCM_fixed`. Every fix from the previous entry (batch-mode
safety, the `ZeroDivisionError`/`IndexError` fixes, `modelName` passthrough) and this session's new
FPA scalar would have been silently inert, exactly the same "import-name mismatch" trap that made
`utilsKinematics_UCM.py` dead weight in the first place (see the 2026-08-14 entry near the top of
this file). Changed the import to `gait_analysis_UCM_fixed`. **This is the one line that makes
everything else in these two update entries actually run.**

**Also threaded `allow_manual_entry` all the way through**, since fixing the batch-mode-hang bug
in `gait_analysis_UCM_fixed.py` is meaningless if nothing in the driver ever passes `False`:
`run_gait_analysis()` and `process_trial()` both gained an `allow_manual_entry` parameter (default
`True`, preserving today's interactive behavior). `run_batch()`'s call site now explicitly passes
`allow_manual_entry=False` — the actual `--all-trials` entry point — and wraps each trial in a
`try/except` so one trial failing gait-event detection gets logged and skipped rather than
crashing (or, before this fix, hanging) the whole batch. The interactive call site
(`run_interactive()`) is unchanged and keeps the default `True`.

**Verified against real data:**
- `compute_foot_progression_angle()` called directly against a lightweight fake instance with real
  fpa-shaped data: returns the correct mean value in degrees.
- `compute_scalars(['foot_progression_angle'])` — the exact call
  `Examples/gaitAnalysis-UCM.py`'s `SCALAR_NAMES` dispatch makes — correctly resolves to the new
  method and returns `{'foot_progression_angle': {'value': ..., 'units': 'deg'}}`.
- Full test suite still 38 passed after all of the above.

**Not done:** an actual end-to-end `run_batch()` call against a real multi-trial session (would
need real walking data with clean gait cycles, which this project doesn't have yet — see the
previous entry's "Not done" note).

## Update 2026-08-24: real validation — verified matched pair, knee/hip agreement at 4.48° RMS

Everything before this section that quotes an accuracy number was measured on mismatched inputs
(see the four ⚠ SUPERSEDED banners above). This section replaces those numbers. It is the first
time this pipeline has been measured against an independent recording of **the same motion on the
same body**.

### The matched pair, and how the pairing was proven

- **Xsens:** `context/Data for Alex/CK/HD Reprocessed/CK-001.mvnx` … `CK-015.mvnx` — 15
  HD-reprocessed MVNX v4 files, MVN 2022.0.0, 23 segments, 60 Hz, each with exactly
  `1 identity + 1 tpose + N normal` frames (so every trial carries its own calibration pose).
- **OpenCap:** `context/OpenCapData_<session-id>` — subject CK, `Trial1` … `Trial15`, with
  `LaiUhlrich2022_scaled.osim` scaled to that subject.
- **Pairing: `CK-00N` ↔ `TrialN`.**

The pairing is not assumed. It was established two independent ways that agree:

1. **Wall clock.** Xsens `recDate` (local) vs. the OpenCap `.mov` QuickTime `mvhd` creation
   timestamps (UTC) sit exactly 5 hours apart — CDT, consistent with a Chicago lab — and match
   within **0–4 seconds on all 15 trials**. The whole session runs 2026-08-20 11:34–11:41 local.
   The Xsens operator consistently starts recording a beat before the phones, which is exactly the
   sign of the offset observed.
2. **Signal alignment.** Per trial, the time lag between the two systems is recovered by
   cross-correlating knee flexion — computed **independently for the left and right knee**. The two
   answers never disagree by more than **1 frame** (mean 0.5), across lags spanning 0.90–4.82 s,
   with peak correlations 0.956–0.988.

Method 1 uses only file metadata; method 2 uses only signal content. They agree on every trial.

### Result: agreement with OpenCap, 14 trials

`Trial8` is excluded from the aggregate and discussed separately below.

| coordinate | mean RMS | sd | mean r |
|---|---|---|---|
| `knee_angle_l` | **3.28°** | 0.55 | **0.986** |
| `hip_adduction_r` | 3.72° | 0.28 | 0.902 |
| `knee_angle_r` | **3.76°** | 0.55 | **0.980** |
| `hip_adduction_l` | 3.92° | 0.31 | 0.857 |
| `hip_flexion_r` | 4.75° | 1.10 | 0.924 |
| `hip_flexion_l` | 6.13° | 0.67 | 0.889 |
| `ankle_angle_l` | 11.56° | 0.99 | 0.296 |
| `ankle_angle_r` | 13.67° | 0.95 | 0.345 |

**Knee + hip flexion: 4.48° mean RMS**, with per-coordinate standard deviations of 0.28–1.10°
across 14 trials. This meets your supervisor's stated benchmark that a working Xsens-to-OpenSim
translation should show only a few degrees of error.

Note this is **agreement with OpenCap**, which is itself a video-based estimate, not gold-standard
marker mocap. It is also *not* comparable like-for-like with the superseded 16.4° / 24–32° figures:
those were IMU **orientation residuals** from IK, a different quantity entirely.

### The ankle disagreement is real, systematic, and not caused by this conversion

Ankle agreement with OpenCap is poor and *consistently* poor (r ≈ 0.30, sd ≈ 1.0 across all 15) —
a reproducible systematic difference, not noise. Three lines of evidence locate it on the OpenCap
side rather than in this pipeline:

**1. Against Xsens's own `<jointAngle>` data, our ankle is as good as our knee.** Using knee and
hip as controls to confirm DOF indexing (`jRightAnkle` = index 16, `jLeftAnkle` = 20,
`flexion_extension` = DOF 2), for CK-001:

| joint | Xsens vs **ours** | Xsens vs OpenCap | ours vs OpenCap |
|---|---|---|---|
| knee R / L | **+0.990 / +0.993** | +0.959 / +0.958 | +0.975 / +0.979 |
| hip R / L | **+0.988 / +0.985** | +0.851 / +0.826 | +0.887 / +0.849 |
| **ankle R / L** | **+0.985 / +0.976** | **+0.388 / +0.249** | +0.343 / +0.241 |

Our `.mot` reproduces Xsens's own ankle angles at r ≈ 0.98 / 4.3–4.5° RMS — the same fidelity we
achieve at knee and hip. And **Xsens's own ankle disagrees with OpenCap just as badly as ours
does.** Two independent IMU-side computations agree with each other and both diverge from video.

**2. OpenCap's ankle signal degrades exactly where agreement collapses.** Frame-to-frame jitter and
range of motion, CK-001 vs Trial1:

| coordinate | our jitter | OpenCap jitter | ratio | our ROM | OpenCap ROM |
|---|---|---|---|---|---|
| `knee_angle_r` | 2.21° | 2.93° | 1.3× | 59.7° | 67.2° |
| `hip_flexion_r` | 1.19° | 2.88° | 2.4× | 44.7° | 60.2° |
| `ankle_angle_r` | 1.38° | **4.13°** | **3.0×** | 40.5° | **80.8°** |

OpenCap degrades monotonically as you move distal (1.3× → 2.4× → 3.0× noisier), and agreement
falls in exactly that order (0.98 → 0.89 → 0.30). OpenCap also reports **80.8° of ankle range**;
normal walking is roughly 30°, and Xsens's 40° is already generous. An 81° ankle excursion is not
physiological.

**3. The ball-of-foot hypothesis is refuted, not merely doubted.** Xsens models `jRightBallFoot` /
`jLeftBallFoot` separately from the ankle, so the obvious theory is that OpenCap's wider ankle
excursion folds in toe motion our `RightFoot → calcn_r_imu` mapping discards. Adding the ball-foot
joint makes agreement **worse**: R 0.388 → 0.295, L 0.249 → **−0.069**.

**Standing caveat.** Xsens's `<jointAngle>` and our `.mot` both derive from the *same* IMU
orientations, so their agreement validates the **conversion**, not ground truth. Neither has been
checked against gold-standard mocap. The defensible claim is *"the ankle discrepancy is not
introduced by this conversion, and the evidence points at OpenCap's video-based ankle estimate"* —
**not** *"our ankle is correct."*

### `Trial8` / `CK-008` — open, needs human review

> **Superseded 2026-08-25** — see "`Trial8` / `CK-008` — anomaly relocated to the Xsens
> recording" at the end of this file. The anomaly is now dual-confirmed against Xsens's own
> solver, OpenCap and per-trial calibration are excluded as causes, and the error signature
> argues against magnetic drift. Kept for the per-trial numbers it records.

Left knee 15.74° and left hip 16.81° RMS, against ~3–6° everywhere else, while its **right** leg is
normal (4.14° / 5.21°). Correlations stay high (+0.929 / +0.856), and removing the constant bias
fixes the hip (16.81° → 8.02°, bias −14.78°) but only partly the knee (15.74° → 11.44°, bias
−10.81°) — so a left-leg offset *plus* degraded tracking. It is also the shortest OpenCap clip
(6.45 s), the largest trim overhead (5.87 s), the largest lag (4.82 s), and the lowest peak
correlation (0.956). Flagged for clinical/design review rather than patched in code.

### Gait analysis on a real walking trial

`CK-001` through the full clinician-GUI pipeline: **44.9 s, zero auto-trim retries**, 4 gait cycles
right / 5 left, with plausible metrics and tight bilateral agreement — gait speed 1.116 / 1.121 m/s
(0.4% apart), cadence 130.3 / 127.8 steps/min, stride length 1.038 / 1.064 m, step width
0.055 / 0.050 m.

For contrast, the same pipeline on a non-gait trial (the bed-to-shower-chair transfer) runs 238
auto-trim attempts over 313 s and still reports one "gait cycle" per leg. **The auto-trim retry
loop is not pathological — it was being fed a trial with no gait events to find.** See the
corrected `MIN_REMAINING_SECONDS_FOR_GAIT_DETECTION` comment in `gait_analysis_UCM_fixed.py`.

This also closes the previous section's "Not done": an end-to-end multi-trial run against real
walking data now exists — all 15 trials processed successfully.

### Parser fix required to read the real files: MVNX v4 `centerOfMass`

`parse_mvnx` rejected all 15 real files outright:

    ValueError: CK-001.mvnx: frame has 9 <centerOfMass> values, expected 3 (x, y, z).

MVNX v4 (MVN 2022+) writes `<centerOfMass>` as **9** values — position, velocity, then
acceleration — where the export shape this parser was first built against carried only the 3
position components. The layout was confirmed empirically against the real file rather than taken
from the schema: columns 0–2 hold a plausible standing CoM height (0.991 m, consistent with
the subject's recorded stature) that drifts slowly, columns 3–5 hold ~0.01 m/s velocities,
columns 6–8 hold noisy near-zero
accelerations. `parse_mvnx` now accepts 3 **or** 9 and keeps the leading 3; a length that is
neither still fails loudly rather than being truncated into a plausible-looking position.

The rest of the parser needed no changes — it already filtered `type == "normal"`, preferred
`tpose` over `npose` for calibration, and all 14 `SEGMENT_TO_IMU_FRAME` keys match the CK files'
segment labels exactly. (These files carry real segment labels, unlike the malformed online
`.mvnx` the parser was originally shaped against.)

Three tests added (`tests/test_xsens_to_opensim_joint_angles.py`): the 9-value layout parses and
keeps position, the 3-value layout still works, and a 6-value frame still raises. **101 tests pass.**

### Reproducing this

Interpreter note: `opensim` lives in the `opencap-processing` conda env, which has no `pytest`;
the base interpreter has `pytest` but no `opensim`. So:

    # pipeline / comparison (needs opensim)
    <miniconda3>\envs\opencap-processing\python.exe <script>
    # test suite (needs pytest)
    <miniconda3>\python.exe -m pytest tests -q

Procedure, per trial `N`:

1. Run `clinician_gui.run_pipeline(session_dir, CK-00N.mvnx)`. Outputs are trial-named
   (`CK-00N.trc/.sto/.mot`) and never overwrite OpenCap's own `TrialN.trc/.mot`, which is what
   makes them usable as the comparison reference.
2. Read both `.mot` files (skip to `endheader`, then whitespace-split columns).
3. Recover the lag by cross-correlating `knee_angle_r` and `knee_angle_l` **separately** over
   0–6 s; average them, and treat a disagreement of more than a few frames as evidence the pairing
   failed for that trial rather than something to average away.
4. Compare over OpenCap's window: `ours[lag : lag+n]` against `opencap[:n]`, reporting RMS and
   Pearson r per coordinate.

For the ankle investigation, `parse_mvnx(...)["joint_angles"]` gives Xsens's own joint kinematics
as a third, independent opinion — indexed by `STANDARD_22_JOINT_ORDER` with DOF order
`(abduction_adduction, internal_external_rotation, flexion_extension)`. Always compare knee and hip
alongside as controls: if those do not land near r ≈ 0.99 against our `.mot`, the joint index or
DOF index is wrong and the ankle numbers mean nothing.

### Still unresolved

The `ucrtbase 0xc0000409` native crash seen once in a GUI session **has never been reproduced** and
its cause is unknown. It did not appear in `run_pipeline` (3 runs), `shape_results_for_display`,
`build_curve_figure`, `export_report_to_pdf`, a threaded `pyplot`/TkAgg import under a live Tk root,
or any of the 15 matched-pair runs. **Closed out 2026-08-25:** the last remaining path was
exercised in a real interactive session — mapped visible window, live `mainloop`,
`start_pipeline_thread` running concurrently with rendering, and the full click flow through Run
and Export PDF on trial `CK-001` under `-X faulthandler`. It completed and exited 0 with no fault,
traceback or exception across 835 lines of output. **No known unexercised path remains.** The
crash was observed once and has never recurred; treat it as intermittent or environment-specific,
not as resolved. GitHub issue #1 is a separate main-thread rendering freeze, not a race — see the
threading-boundary audit. Edit #12 was originally written believing it fixed this crash; it does not.

### ⚠ IMU output has NO global translation — what this means for the spatial gait metrics

Surfaced 2026-08-24 while testing a proposed "reject trials below a minimum forward velocity"
guardrail. The guardrail could not be implemented as specified, because **there is no forward
velocity in this pipeline's output.**

Orientation-only IK cannot recover global translation, and OpenSense does not attempt to. In
`CK-001.mot` the pelvis translation coordinates are constant:

| coordinate | ours (IMU-driven) | OpenCap (video) |
|---|---|---|
| `pelvis_tx` | `0.0000` (range **0.0000**) | −3.9644 … 2.3107 (range **6.2750**) |
| `pelvis_ty` | `0.9300` (range **0.0000**) | 0.9827 … 1.0709 (range 0.0882) |
| `pelvis_tz` | `0.0000` (range **0.0000**) | −0.2578 … 0.2124 (range 0.4702) |

The generated `.trc` inherits this: our first marker moves 0.096 m across the trial where
OpenCap's moves 6.244 m. **The subject walks in place.** The joint-angle validation above is
unaffected — joint angles are orientation-derived and that is precisely what IMUs measure well —
but anything spatial needs care.

**How gait speed and stride length are actually being produced.** Both
`compute_gait_speed` and `compute_stride_length` are displacement-based and both add
`self.treadmillSpeed`. With translation pinned, the displacement terms are ~0, so the metrics are
essentially *entirely* the treadmill term. `compute_treadmill_speed` estimates that from the ankle
marker's velocity during stance (10%–70% of stance), and because a pelvis-fixed frame makes
overground walking geometrically identical to treadmill walking, that estimate does recover
something close to true walking speed — it exceeds the 0.3 m/s `overground_speed_threshold`, so
`gait_style='auto'` silently classifies **every** overground trial as treadmill.

Consequences to state plainly:

- Gait speed is a **stance-foot-velocity proxy**, not a displacement measurement. For CK-001 it
  reads 1.116 m/s against OpenCap's steady-state pelvis speed of 1.223 m/s — the right ballpark,
  but this needs proper per-gait-cycle validation across all 15 trials before being quoted.
- `stride_length ≈ treadmillSpeed × stride_time` by construction, so it is **not independent** of
  gait speed. The tight left/right agreement reported earlier (0.4% on speed, 2.5% on stride) is
  therefore *not* two corroborating measurements — it is one estimate appearing twice.
- `cadence` is derived from gait-event timing only, so it is independent and unaffected.
- `step_width` and any other global-frame spatial quantity should be treated as unverified.

**Not fixed here.** The options — deriving translation from foot-contact constraints, reporting
these metrics as treadmill-equivalent, or suppressing the displacement-based ones for IMU input —
are design decisions, not bugs to patch silently.

### `centerOfMass` truncation tripwire

Reviewer point, adopted with a corrected mechanism. Truncating a 9-value row to its leading 3 is
only safe while the layout is position|velocity|acceleration; a future MVN revision emitting 9
values in another arrangement would pass the length check and silently redefine the parsed
center-of-mass. `_validate_center_of_mass_layout` now rejects that.

Two design notes worth recording, because the obvious implementations are both wrong:

1. **Only 9-value rows are checked.** A 3-value row is used exactly as given, so there is no
   truncation assumption to defend. A first draft also policed 3-value rows and rejected
   legitimate fixtures whose CoM sat near the origin.
2. **The discriminator is the vertical component, not magnitude.** Magnitude cannot separate a
   position triple (~4 m) from a walking velocity triple (~1–2 m/s) — the ranges overlap, and a
   first draft using a magnitude threshold failed to catch a stacked-positions fixture. In
   Xsens's Z-up global frame a position's vertical component is stature-like and well above zero,
   while a velocity's or acceleration's averages to ~0. That separates them cleanly.

Severity is lower than it first appears: nothing downstream consumes `center_of_mass` (it is
parsed, returned, and reported by `--list-segments` only), so a bad slice would be latent rather
than actively corrupting. That is the argument for catching it at parse time rather than at first
use. Four tests added; **106 pass**; all 15 real files still parse.

### Trial8 magnetic-drift hypothesis: not testable from these exports

Proposed check — inspect Xsens calibration logs for left-shank magnetic drift. **The data is not
in the HD-reprocessed `.mvnx` files:** zero occurrences of `magneticField`, and no `accuracy=` or
`quality=` attributes anywhere in `CK-008.mvnx`. Frames carry `orientation`, `position`, and
`sensorOrientation` only.

The Xsens **`.xlsx`** export format *does* carry a `Sensor Magnetic Field` sheet (confirmed on the
unrelated S01 export, which also has `Sensor Free Acceleration` and `Sensor Orientation - Quat`).
So the check becomes possible by re-exporting the CK trials to `.xlsx` from MVN Studio, or by
enabling sensor-data output in the `.mvnx` export options. The raw `.mvn` files are present but are
a proprietary binary format this pipeline cannot read.

### Non-gait trial guardrail (2026-08-24) — REMOVED 2026-08-27

> **Removed 2026-08-27.** The guardrail no longer exists. `_validate_gait_pattern()`,
> `NonGaitTrialError`, `MIN_HEEL_STRIKES_PER_LEG`, `PHYSIOLOGICAL_CADENCE_STEPS_PER_MIN`, the
> `validate_gait_pattern` kwarg, `clinician_gui.NonGaitTrialRejectedError` and its message branch,
> and `tests/test_gait_pattern_validation.py` were all deleted. There are now **no hard cutoffs on
> physiological gait** — no minimum step/cycle count and no cadence window. Any trial that segments
> is analysed and reported. The failure mode below is therefore live again: a non-walking recording
> can still produce a complete, plausible-looking clinical report. The planned mitigation is a
> reporting one, not a blocking one — the re-run survey in
> `docs/plans/2026-08-27-001-feat-rerun-visualizer-joint-reduction-plan.md` emits cycle count and
> cadence as manifest **columns**, so the signal survives without any trial being refused. The rest
> of this section is kept as provenance for the thresholds and the data behind them, in past tense.

Closed the failure mode recorded above: a bed-to-shower-chair transfer produced a complete,
clean-looking clinical report with no warning. `gait_analysis.__init__` called
`_validate_gait_pattern()` immediately after segmentation and before any metric was computed,
raising `NonGaitTrialError`.

**Screening is event-count and event-timing only, by necessity.** A minimum-forward-velocity
screen is the obvious complement and is *not possible here*: root translation is pinned, so global
velocity is identically zero no matter what the subject did (see the section above). Cadence comes
from event timestamps and is unaffected by the missing translation, which is why it can carry this
job.

Two thresholds, both empirically grounded rather than guessed:

- `MIN_HEEL_STRIKES_PER_LEG = 3`. `ipsilateralIdx` is `(n × 3)` spanning HS→TO→HS so the
  ipsilateral leg sees `n + 1` heel strikes, while `contralateralIdx` is `(n × 2)` as TO→HS and
  sees exactly `n`. **The contralateral leg is the binding constraint**, so "3 per leg" means 3
  full gait cycles. Across the 15 verified matched-pair trials, detected cycles ranged **4–6 per
  leg**; the non-gait transfer produced **1**.
- `PHYSIOLOGICAL_CADENCE_STEPS_PER_MIN = (40, 160)`. Deliberately wide. The point is to reject
  transfers and rhythmic non-gait movement, not to adjudicate whether gait is clinically normal —
  hemiparetic or walker-assisted gait can sit far below a healthy cadence, and a narrow window
  would silently reject exactly the patients this tool exists for.

**Validation against real data** (all 15 matched trials × both legs, plus the real non-gait trial):

| | result |
|---|---|
| real gait trial-legs accepted | **30 / 30** |
| false rejections | **0** |
| non-gait trial-legs rejected | **2 / 2** |
| observed cadence range | 124.2 – 133.3 steps/min |
| margin to window bounds | 84.2 low, 26.7 high |

`validate_gait_pattern=False` overrode the check, for a genuinely short but real trial. A
screening heuristic should not be able to hard-block a clinician — which is the reasoning that was
followed to its conclusion on 2026-08-27, when the check was removed outright rather than left as a
default-on block.

Note what it did and did not do: it ran *after* segmentation, so a non-gait trial still paid the
auto-trim retry cost before being rejected. It prevented the bad report, not the wasted CPU.

Nine tests covered it in `tests/test_gait_pattern_validation.py`, including the real-world cycle
counts (4, 5, 6) pinned as a regression against a future threshold change quietly starting to
reject real data. That file was deleted with the guardrail.

### Spatial provenance stamped onto every report

`clinician_gui.SPATIAL_PROVENANCE` is merged into the metadata of every shaped result and rendered
on the PDF's metadata page:

    translation_type                 "Pinned root (orientation-only IK)"
    gait_speed_method                "Stance-phase ankle velocity proxy"
    spatial_displacement_validated   False

`report_export._build_metadata_page` renders the first two as metadata rows and, when
`spatial_displacement_validated` is `False`, adds a prose note on the same page as the numbers:
gait speed and stride length are inferred from stance-phase foot velocity rather than measured
from global displacement, are not independent of one another, and cadence is unaffected.

The reasoning for putting this in the artifact rather than only in this file: the numbers look
entirely ordinary. Nothing about `1.116 m/s` signals that it came from a treadmill-speed heuristic
on a pinned-root skeleton. A caveat that lives only in documentation will be separated from the
report the first time someone copies a value into a slide, so it has to travel with the data.

### Conversion fidelity across all 15 trials (2026-08-25)

Supersedes the single-trial figures quoted in "The ankle disagreement is real, systematic, and not
caused by this conversion" above, which came from `CK-001` alone. Comparing our `.mot` against
Xsens's own `<jointAngle>` for every trial gives 90 coordinate comparisons (15 trials × 6
coordinates), and confirms the single-trial numbers were representative.

**Excluding `Trial8`** (n = 14, 84 comparisons): **r 0.976–0.994, RMS 2.68–4.97°, mean 3.75°.**

| coordinate | mean r | mean RMS | sd | range (excl. Trial8) |
|---|---|---|---|---|
| `knee_angle_r` | 0.990 | 2.85° | 0.13 | 2.69–3.20° |
| `knee_angle_l` | 0.986 | 4.02° | 4.36 | 2.76–3.02° |
| `hip_flexion_r` | 0.989 | 3.85° | 0.30 | 3.62–4.95° |
| `hip_flexion_l` | 0.966 | 4.44° | 1.20 | 3.96–4.29° |
| `ankle_angle_r` | 0.984 | 4.30° | 0.10 | 4.12–4.47° |
| `ankle_angle_l` | 0.974 | 4.83° | 0.74 | 4.45–4.97° |

The `sd` and `mean` columns are inflated by `Trial8`; the final column shows the band the other 14
trials actually occupy, which is remarkably tight. Note this is **conversion fidelity** — our `.mot`
against Xsens's own solver, both fed by the same IMU orientations — and is a different quantity
from the cross-modality agreement with OpenCap reported earlier (r 0.857–0.986, 4.48° mean RMS for
knee + hip flexion). The two must not be quoted interchangeably.

### `Trial8` / `CK-008` — anomaly relocated to the Xsens recording (2026-08-25)

Supersedes the "open, needs human review" framing above. The left-leg divergence is now
**dual-confirmed**: it appears against OpenCap video *and* against Xsens's own internal solver.

| CK-008 | vs OpenCap | vs Xsens `jointAngle` |
|---|---|---|
| `knee_angle_l` | 15.74° (r 0.929) | **20.32° (r 0.89)** |
| `hip_flexion_l` | 16.81° (r 0.856) | **8.91° (r 0.70)** |
| `ankle_angle_l` | 17.65° (r 0.02) | **7.54° (r 0.87)** |
| right leg | 4.14° / 5.21° — normal | 3.20° / 4.95° / 4.47° — normal |

It is the only trial of 15 to leave the 2.68–4.97° band, and only on the left. Because our `.mot`
and Xsens's `jointAngle` both derive from the *same* `.mvnx` — ours by IK on `<orientation>` segment
data, Xsens's by its own constrained solver — a disagreement between them localises the anomaly
**inside the Xsens recording of CK-008's left leg**. That removes OpenCap from the list of
candidate causes entirely.

**Calibration is ruled out.** Our pipeline calibrates from each file's own `tpose` frame, so a
per-trial calibration failure was the obvious competing explanation. It does not survive: the
`tpose` frames are *identical* across all 15 files (0.00° angular deviation from the 14-trial mean
for every left- and right-leg segment; the 0.11° on `RightUpperLeg` is uniform across every trial).
Xsens writes the once-per-session calibration into all files, so IMUPlacer received exactly the
same calibration input for every trial. Whatever is wrong with `CK-008` is in its motion frames,
not its calibration.

**But the signature is not drift-shaped, so do not write this up as magnetic drift yet.** Magnetic
drift accumulates over a recording. The dominant error here does not:

| CK-008 | 1st quartile | 4th quartile | slope | mean bias |
|---|---|---|---|---|
| `knee_angle_l` | 17.74° | 16.05° | **−0.135 °/s** | 16.87° |
| `hip_flexion_l` | 4.83° | 9.21° | +0.460 °/s | 5.18° |
| `CK-001` `knee_angle_l` (reference) | 1.46° | 2.71° | +0.179 °/s | 1.58° |
| `CK-005` `knee_angle_l` (reference) | 1.88° | 2.97° | +0.106 °/s | 1.70° |

The knee error is large and essentially **constant** — it is very slightly *decreasing* — which is
the signature of a fixed sensor-to-segment misalignment or a fusion solution that settled into a
wrong offset early, not of accumulating magnetic interference. The hip does show a growing
component (+0.46 °/s), so the picture is mixed, but the dominant 17° knee offset argues against
pure drift.

**Status:** the anomaly is localised to CK-008's recorded left-leg segment orientations; OpenCap
and per-trial calibration are excluded; the specific mechanism is unresolved and the constant-offset
knee signature is evidence against the magnetic-drift hypothesis rather than for it. Confirming or
excluding drift still requires the `Sensor Magnetic Field` sheet from an MVN Studio `.xlsx`
re-export (the HD `.mvnx` carries no `magneticField` element and no per-sensor quality attributes).
Left for clinical/hardware review rather than patched in code.

---

## Project status & methodological boundaries (index, current as of 2026-08-25)

A single place to see what is established, what is excluded, and what is open — each paired with
the boundary that limits it. Every row is detailed in a section above; this is an index, not a
replacement. **Where this section and an earlier one disagree, this section is current** (several
earlier sections carry ⚠ SUPERSEDED banners).

### Established

| finding | value | boundary on the claim |
|---|---|---|
| Matched pair `CK-00N` ↔ `TrialN` | 15 trials | Proven two independent ways: Xsens `recDate` vs OpenCap `.mov` QuickTime `mvhd` stamps agree 0–4 s at exactly UTC−5 on all 15; per-trial knee cross-correlation recovers the same lag from left and right knees within ≤1 frame. Metadata and signal content agree. |
| **Conversion fidelity** — our `.mot` vs Xsens `<jointAngle>` | r 0.976–0.994, RMS 2.68–4.97°, **mean 3.75°** (n=14, 84 comparisons) | Both sides derive from the **same IMU orientations**. This measures coordinate and model-mapping fidelity **only** — not accuracy. Excludes `Trial8`. |
| **Cross-modality agreement** — our `.mot` vs OpenCap video | knee r 0.980/0.986 (3.76°/3.28°); hip flexion r 0.924/0.889 (4.75°/6.13°); hip adduction r 0.902/0.857 (3.72°/3.92°); **knee + hip flexion mean 4.48° RMS** (n=14) | OpenCap is itself a video-based estimate, not gold-standard mocap. Excludes `Trial8`. **Not interchangeable with conversion fidelity above** — different quantity, different reference. |
| Ankle disagreement is not ours | ours vs OpenCap r 0.296/0.345; ours vs Xsens ankle r 0.985/0.976 | Xsens's own ankle disagrees with OpenCap just as badly (r 0.388/0.249). OpenCap ankle is 3.0× noisier frame-to-frame and reports 80.8° ROM where normal gait is ~30°. Ball-of-foot explanation **refuted** (R 0.388→0.295, L 0.249→−0.069). |
| Non-gait guardrail | **removed 2026-08-27** | Historical result while it existed: 30/30 real trial-legs accepted, 0 false rejections, 2/2 non-gait rejected, at ≥3 heel strikes per leg and cadence 40–160 steps/min. No screen runs now — a non-gait trial is analysed and reported like any other. |
| MVNX v4 parsing | 3- or 9-value `centerOfMass` | Layout confirmed empirically, not from schema. Truncation guarded by a vertical-component tripwire on 9-value rows only. |
| Test suite | **287 tests pass** | This is a **pass rate, not a coverage measurement**. No coverage analysis has been run on this repo. |

### Excluded, and by which argument

| candidate cause | status | argument that excludes it |
|---|---|---|
| OpenCap error explains `Trial8` | excluded | `Trial8`'s left leg also diverges from **Xsens's own solver** (knee 20.32°, r 0.89), and both sources derive from the same `.mvnx`. The fault is inside the Xsens recording. |
| **Per-trial** calibration failure | excluded | All 15 `tpose` frames are identical (0.00° deviation from the 14-trial mean; the 0.11° on `RightUpperLeg` is uniform across every trial). IMUPlacer received the same input every time. |
| **Session-level** calibration failure | excluded | *Separate argument:* all 15 trials share that one session calibration, and 14 of them are clean. A bad session calibration would affect all 15. |
| Ball-of-foot / toe joint explains the ankle gap | excluded | Adding `jRightBallFoot`/`jLeftBallFoot` makes agreement **worse**, not better. |
| Auto-trim retry loop caused the native crash | excluded | A real non-gait trial runs 238 trims to completion; a real walking trial needs zero. Edit #12 does not fix that crash. |

### Open

| item | precise status |
|---|---|
| `Trial8` / `CK-008` mechanism | **Unresolved.** Localised to CK-008's recorded left-leg segment orientations. Magnetic drift is **not confirmed and the evidence leans against it**: drift accumulates, but `knee_angle_l` error runs 17.74° (Q1) → 16.05° (Q4), slope **−0.135 °/s** — a large near-constant offset, consistent with fixed sensor-to-segment misalignment or a fusion solution settling wrong early. `hip_flexion_l` does grow (+0.460 °/s), so the picture is mixed. Discriminating requires the `Sensor Magnetic Field` sheet from an MVN Studio `.xlsx` re-export; the HD `.mvnx` carries no `magneticField` element and no per-sensor quality attributes. |
| Spatial gait metrics | **Not fixed, only labelled.** Root translation is pinned (`pelvis_tx`/`tz` constant 0.0000 against ~6.3 m of real travel), so `gait_speed` and `stride_length` are stance-phase ankle-velocity proxies, and `stride_length ≈ treadmillSpeed × stride_time` makes them **not independent of each other**. `cadence` is event-timing derived and unaffected. Every overground trial is silently classified as treadmill. Provenance is stamped on every report via `SPATIAL_PROVENANCE`. |
| `ucrtbase 0xc0000409` | **Unreproduced and undiagnosed.** Absent from `run_pipeline` (3 runs), `shape_results_for_display`, `build_curve_figure`, `export_report_to_pdf`, a threaded `pyplot`/TkAgg import under a live Tk root, and all 15 matched-pair runs. **Updated 2026-08-25:** widget *construction* is no longer untested — a headless smoke test built a real `ClinicianGUI`, applied the design system, and ran `_render_metadata`/`_render_curves` (real `FigureCanvasTkAgg` embedding)/`_render_metrics` on real shaped data, then tore the root down, with no crash. But the root was **withdrawn/never mapped**, so the native paint path (GDI/screen draw, device context) did not run — if a crash lives in rendering, that is exactly where it would fail to reproduce. A thread-safety race is separately **ruled out**: the worker thread only puts tuples on a queue and every widget/Figure touch is main-thread (see "Threading-boundary audit"). **Updated again 2026-08-25 (interactive run):** a real user session — mapped visible window, live `mainloop`, `start_pipeline_thread` running concurrently with rendering, the full click flow through Run and Export PDF, on trial `CK-001` under `-X faulthandler` — completed and exited 0 with no fault, traceback or exception in 835 lines of output. **There is no longer any known unexercised path.** The crash remains undiagnosed and unreproduced; since it was observed once, treat it as intermittent or environment-specific rather than resolved. |
| UCM / synergy analysis | **Does not exist in this repo.** "UCM" is a filename suffix and a docstring label; there is no uncontrolled-manifold or variance-ratio computation. Guidance about restricting synergy joint space or filtering ankle DOFs applies to future code. |

### Standing methodological ceiling

Nothing in this repository has been validated against gold-standard optical motion capture
(Vicon/Qualisys). The strongest defensible claims are **conversion fidelity** (against Xsens's own
solver, shared input) and **cross-modality agreement** (against OpenCap video, independent but not
a reference standard). Neither is an accuracy measurement.

### Retracted

The earlier 16.4° overall and 24–32° per-segment figures are **withdrawn as invalid** — they were
IMU *orientation residuals* computed on mismatched data (one person's IMU stream driving a model
scaled to a different person, performing a different, non-walking motion). They are **not**
comparable to the joint-angle figures above, and the change from them is a metric and dataset
correction, not a reduction in error on like data.

### Clinician GUI: guardrail messaging and on-screen provenance (2026-08-25)

Two gaps found by auditing the GUI against changes made elsewhere in the pipeline. Both were
silent — the code ran fine, it just told the clinician the wrong thing.

**1. The non-gait guardrail gave actively wrong advice.** *(Moot as of 2026-08-27: the guardrail
and `NonGaitTrialRejectedError` were both removed. A gait-analysis failure now maps to
`GaitAnalysisFailedError` again, which is correct, because a detection failure is the only kind
left.)* `NonGaitTrialError` was not referenced in
`clinician_gui.py` at all, so a guardrail rejection fell through `run_pipeline`'s generic
`except Exception` into `GaitAnalysisFailedError`, whose headline reads *"Try a longer or cleaner
recording of the same activity."* For a rejected transfer that is wrong advice: a longer, cleaner
recording of a transfer is rejected for exactly the same reason, so the clinician spends another
session to reach the same screen. The specific text survived only as a `Details:` appendix.

Now a dedicated `NonGaitTrialRejectedError` with its own message, ending *"re-recording the same
activity will not change this result."* The class is pulled off the loaded module via `getattr`
rather than matched on `__name__`, because `gait_analysis_UCM_fixed` is loaded by path at runtime
and cannot be imported at module level — and a module predating the class (or a test fake without
it) still maps to the generic failure rather than raising `AttributeError`.

**2. The spatial-metric caveat reached the PDF but not the screen.** `_render_metadata` built its
rows from a hardcoded five-entry list, so `Root translation` and `Gait speed method` appeared only
on the exported report. The clinician reads gait speed **on screen first**. The provenance rows are
now appended when present (via `.get()`, so partial metadata still renders), and the metrics panel
carries the caveat sentence itself, on the panel showing the numbers it qualifies.

Per `DESIGN.md`: metadata rows follow the established label-in-`Secondary.TLabel` / value-in-data-
font pattern; the caveat is sentence-case rather than uppercase following KTD5's precedent that
long-form explanatory text stays sentence-case (all-caps is a readability regression at that
length); no new color; `wraplength` rather than hard line breaks so it reflows with the panel.

**Widget path exercised for the first time.** A headless smoke test (real `Tk` root, withdrawn)
constructed `ClinicianGUI`, applied the design system, and ran `_render_results` on real shaped
data — exercising `_build_widgets`, `_render_metadata`, `_render_curves` with genuine
`FigureCanvasTkAgg` embedding, and `_render_metrics` — then destroyed the root. No crash, and both
fixes confirmed present in the live widget tree. This is the first time any of that code has run.

Still not exercised, and worth being precise about: the **interactive** path — a live `mainloop`
with `start_pipeline_thread` running while figures render, plus the actual click flow
(`_pick_session_dir`, `_on_run_clicked`, `_poll_pipeline_queue`, `_on_export_clicked`). That
concurrency is what GitHub issue #1 actually describes, and it needs a person at a real window.

7 tests added (3 for the error mapping including the "must not tell them to re-record" regression,
3 for the PDF provenance rows and prose caveat, 1 for the shaped-metadata flags). **122 pass.**

### Threading-boundary audit, and what `root.withdraw()` does not prove (2026-08-25)

Two results that together reclassify GitHub issue #1 and bound what the widget smoke test above
actually established. Both are negative results — they remove hypotheses rather than fix anything —
which is exactly why they are worth writing down.

**The thread boundary is clean; there is no cross-thread GUI mutation.** The obvious explanation
for a native crash in a threaded Tk app is a worker thread touching widgets or Matplotlib figures
directly. Audited, and it does not happen here:

| | what runs there |
|---|---|
| **Worker thread** (`start_pipeline_thread._target`) | `run_pipeline` plus `result_queue.put((kind, payload))`. Pure data. `map_error_to_message` also runs here, but it is string logic with no Tk reference. No widget access, no Figure creation. |
| **Main thread** | `root.after(100, self._poll_pipeline_queue)` → `drain_queue` → `progress_var.set` / `_on_pipeline_result` → `_render_results` → `build_curve_figure` and all `FigureCanvasTkAgg` construction. |

Every widget mutation and every Matplotlib Figure is created on the main thread; the worker only
posts tuples onto a `queue.Queue`. This is the correct pattern, and it means a Tcl/Tk or Matplotlib
**thread-safety race is effectively ruled out** as the mechanism behind `ucrtbase 0xc0000409`.

**Consequently, GitHub issue #1 is reclassified.** It is not a latent concurrency crash. It is what
its title says: main-thread Figure rendering blocks the event loop, so the UI freezes while curves
are built. That is a responsiveness defect, not a stability one. Worth fixing on its own merits;
not a candidate explanation for the crash.

**What `root.withdraw()` did and did not exercise.** The smoke test above used a withdrawn — never
mapped — window, so its result must not be over-read:

| exercised | not exercised |
|---|---|
| Python object construction, widget hierarchy, `apply_design_system` | native OS window mapping |
| `FigureCanvasTkAgg` embedding and memory allocation | GDI/screen paint calls, device-context creation |
| `_render_metadata` / `_render_curves` / `_render_metrics` code paths | physical layout reflow, `wraplength` wrapping, overlap |
| clean teardown via `root.destroy()` | anything requiring a visible window |

So static construction is verified; **the native paint path is not**. If a crash lives in rendering,
an unmapped window is precisely where it would fail to reproduce. Similarly, the on-screen
provenance rows and the metrics caveat are confirmed **present in the widget tree** — their *visual*
correctness (position, wrapping at the real panel width, collision with the metrics table) is
unverified, because no window was ever displayed.

**Remaining unexercised surface**, stated precisely so it is not quietly assumed away: a mapped,
visible window; the native paint path; a live `mainloop` running concurrently with
`start_pipeline_thread`; and the click flow (`_pick_session_dir`, `_on_run_clicked`,
`_poll_pipeline_queue` firing for real, `_on_export_clicked`). One interactive session against a
`CK-00N` trial covers all four at once, and is the single highest-value remaining test on this
codebase.

## Update 2026-08-25: all 15 trials batched, GDI recovered, UCM still absent

Driven by the actual research goal, stated this session: GDI and a synergy (UCM) index, both of
which need variance across trials, which a one-trial-at-a-time GUI structurally cannot provide.

### `run_batch` cannot process locally-generated trials

`Examples/gaitAnalysis-UCM.py`'s `process_trial()` calls `get_trial_id()` then `download_trial()` —
it **re-downloads every trial from OpenCap's servers** before analysing it. The `CK-*` trials are
IMU-derived and written locally by this pipeline; they have never existed on OpenCap. All 15 failed
with *"This session is not in your username, nor is it public."*

This is architectural, not a bug to patch: `run_batch` assumes every trial originated in OpenCap.
`run_gait_analysis()` and `export_individual_curves_csv()` underneath it are fully offline, so the
batch driver calls those two directly and skips the download. Worth knowing before anyone reaches
for `--all-trials` on Xsens-derived data again.

Note also `discover_trials()` globs `*.mot`, and the session now holds **31** — 15 IMU-derived
`CK-*` plus 16 video-derived `Trial*`. `--all-trials` would silently process both sets as though
they were one cohort. Trial names are passed explicitly instead.

### Upstream bug in `utilsKinematics.py`: the filtered path is broken

```python
if lowpass_cutoff_frequency_for_coordinate_values > 0:
    ...
    self.table.trim(...)          # shortens the table
...
self.Qs = self.table.getMatrix().to_numpy()                    # trimmed length
spline = InterpolatedUnivariateSpline(self.time, self.Qs[:,i])  # self.time never updated
```

The trim shortens `self.table` but leaves `self.time` at its original length, so **any** call with
a positive cutoff raises `ValueError: x and y should have a same length` whenever the trim actually
removes a row. `run_gait_analysis` defaults to `filter_frequency=6` and hits it on every trial;
`clinician_gui.run_pipeline` passes nothing (default `-1`), skips the branch, and works.

Not fixed here: `utilsKinematics.py` is one of the coworker-supplied files under the "copies only"
rule. **Consequence worth stating plainly: every validated number in this file was produced
unfiltered**, because `run_pipeline` never passes a cutoff. The batch was run the same way, so it
is consistent with the validation — but if the protocol calls for 6 Hz filtering, that fix belongs
in a `_UCM`-suffixed copy and the accuracy work would need re-running.

### Batch result: 15/15

All 15 CK trials → `context/gait_curves/` (gitignored), 319 s, both legs each, 30 CSVs.

**Format note.** The export is `np.savetxt(matrix, delimiter=',', fmt='%f')` — raw numbers, no
coordinate-name or frame-index columns. This is *not* a regression from the 2026-08-17 rewrite: the
pre-rewrite version used the identical `np.savetxt` call. The labels in `Data/UCM
Analysis-test1_right.csv` (`pelvis_tilt,0,...`) were added by something downstream of this
pipeline, not by it.

**Row-count compatibility.** Ours are `38 × 101 = 3838` rows; that reference file is `36 × 101 =
3636`. The difference is `fpa_r`/`fpa_l`, added to `JOINT_NAMES` on 2026-08-20. Any downstream
matrix built against the 36-coordinate layout will not accept these files unmodified.

### GDI recovered and repaired → `gdi.py`

The ~810 lines removed on 2026-08-17 are restored as live, tested code in a new module (same
"new file, not an edit of a coworker's" pattern as `gait_analysis_UCM_fixed.py`). Five bugs fixed,
each of which produced a wrong answer or an obscure crash rather than an obvious failure:

1. Checked for `matrix.csv` but opened `matrix_ms_reduced.csv`; checked `controlCalc.csv` but
   opened `controlCalc_ms_reduced.csv`. Either way one path was wrong — a missing `_ms_reduced`
   file raised `FileNotFoundError`, a missing plain-named one skipped silently and left `matrix`
   undefined until a `NameError` much later.
2. Searched via `os.walk` from three directory levels above the repo, with no `break`, so the last
   copy found anywhere in that tree silently won. Now an explicit directory argument.
3. **The right-leg feature vector was wrong.** It used all 36 coordinates at 101 points (3636
   values) with the `num % 2 == 0` downsampling commented out, while the left-leg version used the
   correct 9-variable list at 51 points. GDI is defined on 9 × 51 = 459; the right-leg vector was
   neither the right features nor the right sampling.
4. The reference load ran at import time, walking the filesystem as an import side effect.
5. No validation that vector length matched the reference matrix, so a shape mismatch surfaced as
   an opaque numpy error.

Verified against real data: both sides of `CK-001` build a finite 459-value vector
(r: −26.28…58.93, l: −28.83…62.82). 17 tests; **139 pass** overall.

**GDI still cannot produce a score.** `matrix_ms_reduced.csv` and `controlCalc_ms_reduced.csv` are
not in this repo, and GDI is *defined* relative to a normative control group — it is not derivable
from subject data. `load_gdi_reference` now fails with a message naming exactly what is missing and
why. The normative constants `LN_CONTROL_MEAN = 4.443685139` / `LN_CONTROL_SD = 0.223457646` belong
to that same control dataset and must be replaced together with it.

**GDI is unaffected by the pinned-root limitation.** Its 9 variables are joint angles plus pelvis
*orientation* (tilt/list/rotation) — no translation, no centre-of-mass term. All 9 are present in
the IMU `.mot` output, `subtalar_angle` included. So unlike `gait_speed`/`stride_length`, GDI is
computable from this pipeline's data as soon as the reference dataset exists.

### UCM / synergy index: does not exist anywhere in this repo

Searched every commit and every file type (`.py`, `.m`, `.mlx`, `.ipynb`, `.mat`, `.csv`) including
`context/`. There is no nullspace projection, no V_UCM/V_ORT variance decomposition, and no
task-variable Jacobian — not even commented out, unlike GDI. The `-UCM` filename suffix and the
repository's name are the only traces.

`Data/UCM Analysis-test1_right.csv` is **not** UCM output: it is 36 coordinates × 101 frames with
one column per gait cycle, exactly `_build_individual_curves_matrix`'s shape, and its filename
parses as `subject_id="UCM Analysis"`, `trial_name="test1"`. It is the per-gait-cycle curves export
— the *input* a UCM analysis consumes.

If the math exists, it is outside this repository. Re-deriving it risks a different formulation
than the lab's, so it is worth asking for rather than reconstructing.

**One constraint to settle before any UCM work starts:** `JOINT_NAMES` carries `pelvis_tx/ty/tz`
and `comx/comy/comz`, and `_build_individual_curves_matrix` expresses the COM terms *relative to
the matching pelvis translation*. For IMU-derived trials the root is pinned, so those six are
degenerate. If the task variable is COM position — the standard gait UCM formulation — it cannot be
computed from the IMU data as it currently stands. That is a modelling decision, not a coding one.

### Batch inspection: stride inventory and which coordinates are actually usable (2026-08-25)

Inspection of the 30 exported curve matrices. The headline is that **five coordinates carry
exactly zero variance and the upper limb is invalid**, so any variance decomposition must strip
those columns rather than project noise into the V_UCM / V_ORT subspaces.

**Stride inventory: 145 pooled** — 72 right, 73 left, 4–6 per trial per side across all 15 trials.
Adequate for across-stride variance work.

**Coordinate usability** (across-stride SD in **degrees**, pooled over 15 trials, right-side file):

| group | across-stride SD | status | consequence |
|---|---|---|---|
| pelvis orientation (`tilt`/`list`/`rotation`) | 0.71–1.86 | clean | usable in `q` |
| lower limb (hip/knee/ankle/subtalar, both sides) | 0.78–1.70 | clean | usable in `q` |
| lumbar (`extension`/`bending`/`rotation`) | 0.74–1.40 | clean | usable in `q` |
| `pelvis_tx` / `ty` / `tz` | **0.000000** | degenerate | pinned root — exclude |
| `mtp_angle_r` / `mtp_angle_l` | **0.000000** | degenerate | exclude (see below) |
| `comx` / `comy` / `comz` | 0.0025–0.0033 **m** | pelvis-relative only | task-variable candidate, not `q` |
| upper limb (10 DOF) | see below | invalid | exclude |

**`mtp_angle_r/l` are frozen for a specific, fixable reason.** `SEGMENT_TO_IMU_FRAME` maps
`RightFoot → calcn_r_imu` but nothing maps `RightToe`/`LeftToe`, so the metatarsophalangeal joint is
unconstrained by any IMU and never leaves its default value. The Xsens file *does* carry
`RightToe`/`LeftToe` segments (23 segments, both present), so this is a mapping gap rather than a
data limitation — addressable if toe kinematics ever matter.

**`comx/comy/comz` are not degenerate, but they are not global COM either.**
`_build_individual_curves_matrix` expresses each COM component *relative to the matching pelvis
translation*, and with translation pinned that reduces to COM in a **pelvis-fixed frame**. It does
vary (~3 mm across strides) from limb motion. That is a different construct from global COM
control, so a COM-based UCM task variable computed here would not mean what the standard gait
formulation means. Modelling decision, not a coding one.

**The upper limb is invalid — the 2026-08-19 T-pose hypothesis, now confirmed.** That entry
predicted the arms would be wrong because "the calibration pose has arms out; this model's default
pose has arms down," and left it untested. It is now demonstrated:

| coordinate | range across all 15 trials | verdict |
|---|---|---|
| `arm_flex_l` | −566.4° … 140.3° | **saturating** |
| `arm_rot_l` | −126.1° … **572.9°** | **saturating** |
| `arm_flex_r` | 181.2° … 363.9° | **non-physiological** |
| `arm_add_r`, `arm_rot_r`, `elbow_flex_r`, `arm_add_l`, `elbow_flex_l` | within plausible bounds | not proven bad |

**10 radians = 573.0°.** Those coordinates are pinned against their OpenSim joint bounds in 11 of
15 trials — IMUPlacer derives a large bogus shoulder offset from the T-pose, and IK then drives the
coordinate to its limit.

State the scope precisely: **three** coordinates demonstrably saturate; the remaining upper-limb
DOFs sit in plausible ranges but are produced by the same corrupted shoulder calibration and are
coupled to the broken ones through the shoulder's Euler triplet. They are *not trustworthy by
association*, not *proven wrong*. The conservative and correct call is to exclude all 10 upper-limb
DOFs from any joint vector.

**Legs and pelvis are clean** across all 15: knee 0.0–68.8°, hip −29.9…35.0°, ankle −37.4…15.4°,
pelvis within ±30.9°. All physiological.

**Resulting partition of `JOINT_NAMES` (38 entries):**

- **18 usable as `q`** — 3 pelvis orientation, 12 lower limb (6 per side), 3 lumbar.
- **5 zero-variance, must be stripped** — `pelvis_tx/ty/tz`, `mtp_angle_r/l`.
- **10 upper-limb, excluded** — invalid calibration.
- **3 COM** — task-variable candidates, pelvis-relative, not part of `q`.
- **2 derived** — `fpa_r`/`fpa_l` are computed foot-progression angles, not model DOFs.

**Impact by analysis:**

- **GDI: unaffected.** Its 9 variables are pelvis orientation plus one leg — no translation, no COM,
  no arm coordinate. All 9 are clean here.
- **Lower-limb UCM formulations: unaffected.** Foot-position-relative-to-hip and lower-limb angular
  coordination both draw only on the clean 18.
- **Any formulation including the upper limb would decompose garbage,** and `JOINT_NAMES` carries
  those coordinates by default, so the exclusion has to be explicit rather than assumed.

### Contingency scoping for the three UCM formulations (2026-08-25)

Recorded before any of it is attempted, because the cost differences are large and not obvious from
the code. Which path applies depends on the task variable the collaborator's prior formulation used
— an open question at time of writing.

**A — lower-limb / pelvic synergy: zero compute.** The 18-DOF `q` (3 pelvis orientation, 12 lower
limb, 3 lumbar) for all 145 strides is already on disk in `context/gait_curves/`. Nothing to
re-run.

**B — foot/toe kinematics included: full pipeline re-run, ~15-20 min.** `mtp_angle_r/l` are frozen
because `SEGMENT_TO_IMU_FRAME` never maps `RightToe`/`LeftToe`, so mapping them is the fix. But
note what that actually changes: it adds two more **tracked IMU frames to the IK problem**, so
`run_imu_ik` produces a different solution. Every `CK-*.mot` is replaced, and `.trc`/`.sto` and the
curve CSVs regenerate from it. This is not a matter of appending two columns at export time —
`mtp_angle` comes out of the IK, not the exporter. Budget the full conversion pipeline (~45 s/trial)
plus the curve batch (~20 s/trial), and expect the existing outputs to be invalidated.

**C — whole-body synergy: a validation project, not a calibration fix.** Recovering the 10
upper-limb DOFs means addressing the T-pose-vs-arms-down shoulder offset (see the batch-inspection
section above). Even if the geometry fix works, **the resulting arm kinematics would be newly
generated and entirely unvalidated**: every validation figure in this file covers knee, hip, ankle
and pelvis only — no arm coordinate has ever been compared against OpenCap or against Xsens's own
`<jointAngle>`. Feeding unvalidated arm DOFs into a variance decomposition would project calibration
artifacts straight into V_UCM / V_ORT, which is exactly the failure the exclusion exists to prevent.
C therefore carries its own validation pass as a prerequisite, and is materially larger than B.

Deliberately not started. Doing either B or C before the task variable is known risks rebuilding
DOFs the formulation does not use.

### Clinician GUI: scrollable results, and a multi-trial methodology comparison (2026-08-25)

Two errors reported from a real interactive session.

**1. Results were unreachable below the window edge.** There was no scrolling machinery anywhere in
`clinician_gui.py` — no `Canvas`, no `Scrollbar`, no `yview` — and no `rowconfigure`/
`columnconfigure`/`geometry`, so the window did not expand either. With six joint-angle figures laid
out three-across plus metadata and metrics, the content measures **1166 px** against a default
window of ~820 px: roughly 350 px, including the second row of flexion curves, simply could not be
reached.

Fixed with the standard tkinter composition (there is no scrollable Frame): a `Canvas` owning the
scroll, a `Scrollbar` driving its `yview`, and an inner `Frame` placed via `create_window`, with
`_render_results` building into that inner frame. The canvas item width tracks the viewport so
panels do not sit in a narrow column, the scrollregion is resynced after each render, and the view
returns to the top on a re-run rather than staying scrolled into the previous trial's results.
Mouse-wheel is bound on enter/leave of the canvas rather than via `bind_all`, so it cannot hijack
the wheel over unrelated widgets. Window now defaults to 1180x820 with a 900x600 minimum.
Verified: `yview` reaches `(0.999, 1.0)`, i.e. the bottom of the content.

**2. No way to compare methodologies across trials** → `methodology_comparison.py` (+18 tests).

Both pipelines' per-stride curves now exist for the same 15 motions, produced through the identical
offline unfiltered path: 15 Xsens trials (72 right-side strides) and 15 OpenCap trials (50). The
module reads the exported matrices and reports them side by side.

The row-mapping guard is the important part. The CSVs carry **no labels** — row position is the only
thing identifying a coordinate — so `JOINT_NAMES` is imported from the driver rather than copied,
and a length mismatch raises instead of mislabelling every number in the report. `fpa_r`/`fpa_l`
were added to that list on 2026-08-20, which is exactly the kind of change that would otherwise
desynchronise a local copy silently.

What the comparison shows across all 15 matched trials:

| | Xsens / IMU | OpenCap / video |
|---|---|---|
| strides (right side) | 72 | 50 |
| `pelvis_tx/ty/tz` | **0.00000** (pinned root) | 1.247 / 0.010 / 0.093 — real translation |
| `mtp_angle_r/l` | 0.00000 (frozen at −7.50°) | 0.00000 (frozen at 0.00°) |
| `arm_flex_l` / `arm_rot_l` | **156.8 / 156.6** — saturating | 2.28 / 3.26 — physiological |
| knee / hip / ankle SD | 1.17 / 1.34 / 1.19 | 2.26 / 2.42 / 4.76 |
| `comx/comy/comz` | 0.0029 / 0.0025 / 0.0033 | 0.0034 / 0.0036 / 0.0034 |

Three findings worth carrying forward:

- **The toe joint is degenerate in *both* methodologies**, not just ours — OpenCap freezes it at
  0.00° and the IMU pipeline at −7.50°. Earlier notes attributed this solely to the missing
  `RightToe`/`LeftToe` mapping in `SEGMENT_TO_IMU_FRAME`; that gap is real, but OpenCap does not
  drive `mtp_angle` either, so it is not a coordinate either methodology currently supports.
- **OpenCap's arms are fine.** `arm_flex_l` spans −37…16° there against −566…140° in the IMU
  pipeline, confirming the saturation is specific to the T-pose calibration rather than to the
  subject or the model.
- **OpenCap is roughly 2× more variable stride to stride at knee and hip, and 4× at the ankle** —
  the same distal degradation pattern the joint-angle validation found, now visible in
  across-stride variance rather than frame-to-frame jitter.

`gdi_comparison()` computes GDI for every methodology as soon as a reference directory is supplied
and otherwise reports exactly what is missing; `synergy_status()` reports unavailability rather than
returning a placeholder, since a zero or NaN in a results table is indistinguishable from a real
measurement. Both are pinned by tests. It also records the decisive asymmetry: **a global-COM task
variable is available to the OpenCap methodology but not to the IMU one**, whose root translation is
pinned — the COM columns in both exports are pelvis-relative.

### UCM decomposition implemented, and a first result that must not be quoted naively (2026-08-25)

`ucm.py` (projection maths) and `com_task.py` (the task function) built test-first — see the commit
messages for the TDD/mutation-sweep record. **The formulation is a default chosen here, not a
reproduction of any prior analysis.**

Formulation: `q` = the 18 clean DOFs; `x` = pelvis-relative COM, chosen over global COM so both
methodologies remain comparable (global COM does not exist for the pinned-root IMU pipeline).
Jacobian by central differences through the real scaled OpenSim model — rank 3, so the uncontrolled
manifold is 15-dimensional, as designed.

First result, all strides pooled:

| methodology | strides | V_UCM | V_ORT | mean ΔV | ΔV_z | phases with synergy |
|---|---|---|---|---|---|---|
| Xsens | 72 | 9.695 | 5.777 | 0.407 | 0.365 | 100/101 |
| OpenCap | 50 | 19.329 | 4.962 | 0.803 | 0.838 | 101/101 |

Both show a COM-stabilising synergy. **The methodology difference is largely an artifact, and this
is the number most likely to be misread.**

The task is **80× more sensitive to proximal than distal DOFs** (mean |J| 1.515 mm/deg for
hip/pelvis/lumbar against 0.019 for ankle/subtalar; 121× between the extremes). Pelvis-relative COM
barely moves when the ankle does, so ankle and subtalar variance is close to *free* — it lands in
the uncontrolled manifold by construction, inflating V_UCM and therefore ΔV.

OpenCap's excess variance sits precisely there (ankle across-stride SD 4.76 against the IMU
pipeline's 1.19). Re-running with those four DOFs removed:

| | with ankle/subtalar | without | change |
|---|---|---|---|
| Xsens ΔV | 0.407 | 0.477 | +0.070 |
| OpenCap ΔV | 0.803 | 0.643 | −0.160 |
| **gap** | **0.396** | **0.166** | **−58%** |

OpenCap's V_UCM falls 33% (19.33 → 12.86) while the IMU pipeline's *rises*. **Roughly 58% of the
apparent methodology difference was distal measurement noise projecting into COM-insensitive
directions**, not better motor coordination. The residual gap may be real or may be the same effect
in other DOFs; it is not established either way.

Consequences to carry forward:

- Do not report "OpenCap shows a stronger synergy". On this task variable, a noisier signal can
  score *higher* whenever its noise concentrates in low-sensitivity DOFs.
- Any ΔV quoted from this pipeline needs the Jacobian sensitivity profile alongside it. A synergy
  index is only interpretable against how much each DOF actually moves the task variable.
- This is an argument for choosing the task variable on domain grounds rather than convenience.
  Pelvis-relative COM was picked for cross-methodology comparability, and it happens to be nearly
  blind to the distal joints where the two methodologies differ most — close to a worst case for
  this particular comparison.
- Strides are pooled across trials, so between-bout differences count as deviation from the pooled
  mean. Defensible for "across-stride variance", applied identically to both methodologies, but it
  is not within-bout variability and should not be described as such.

### The synergy ranking reverses with the task variable (2026-08-25)

Follow-up to the COM result above, and the reason `analyse_cycle` takes the task function as a
callable. `FootPlacementTask` (position of `calcn_r` relative to the pelvis) was added and run
against the same strides.

| task variable | Xsens ΔV | OpenCap ΔV | gap | OpenCap V_ORT |
|---|---|---|---|---|
| pelvis-relative COM | 0.407 | **0.803** | **+0.396** | 4.962 |
| foot placement, 18-DOF q | 0.475 | 0.179 | **−0.297** | 15.117 |
| foot placement, 9-DOF ipsilateral q | 0.448 | 0.195 | −0.253 | 15.117 |

**The ranking flips sign.** Under COM, OpenCap looks markedly more synergistic; under foot
placement, markedly less. Xsens moves hardly at all (0.407 → 0.475) because its variance is not
concentrated distally.

The mechanism is visible in V_ORT: OpenCap's **triples**, 4.962 → 15.117, while the IMU pipeline's
falls slightly. Sensitivity to the ankle rises 45× between the two task variables (0.022 →
0.995 mm/deg), so OpenCap's distal noise stops being invisible to the task and starts disrupting
it — moving out of V_UCM and into V_ORT, which is where measurement noise belongs.

**So "which methodology shows more synergy" is not a property of the data.** It is determined by
how the chosen task variable weights the DOFs where the two methodologies differ. Any ΔV comparison
quoted without its task variable and sensitivity profile is uninterpretable.

Of the two, foot placement is the more honest basis for judging measurement quality, precisely
because it stops rewarding distal noise. That does not make it the right task variable for the
research question — that remains a domain decision.

One modelling note found while building it: for a right-foot task, the left leg and lumbar have
**exactly zero** sensitivity (they are not in the pelvis→right-foot kinematic chain), so with an
18-DOF q half the joints sit in the uncontrolled manifold by construction rather than by any
motor-control fact. The 9-DOF ipsilateral q is the defensible formulation; both are reported above
and they agree closely (−0.297 vs −0.253), so the conclusion does not rest on that choice.

`subtalar_angle_r` also has zero sensitivity to foot placement: subtalar rotation turns the
calcaneus about its own origin without translating it. Expected, not a bug, but it means the
ipsilateral q effectively contributes 8 informative DOFs, not 9.

### `xtoo.py` — second conversion route, ported from the supervisor's XtoO.m (2026-08-25)

Built test-first from `context/XtoO.m` and `context/jointcheck/`. It relabels Xsens's **own** joint
angles into OpenSim coordinate names and writes a `.mot` directly — no IMUPlacer, no IK, no model.

**It supplies the three things the IK path cannot.** Measured on CK-001:

| | XtoO port | OpenSense IK | OpenCap |
|---|---|---|---|
| `pelvis_tx` range | **6.998 m** | 0.000 m (pinned) | 6.275 m |
| `mtp_angle_r` range | **57.4°** | 1.21° (frozen) | 0.00° |
| `arm_flex_l` range | **45.2°** | 419.8° (saturated) | — |

Where both paths are valid they agree: knee r 0.990, hip 0.988, ankle 0.985, pelvis 0.984–0.992.

Reads `.mvnx` directly — `<jointAngle>`, `<orientation>` and `<position>` carry everything XtoO.m
pulls from `.xlsx`, so the spreadsheet export and its column-naming drift are skipped.

**Two axis assignments in XtoO.m are wrong, and this port corrects them.** Both were established
empirically, not read off the MATLAB:

- **Pelvis rotations.** XtoO.m assigns tilt←roll, list←−yaw, rotation←−pitch. Measured against our
  IK solution: tilt is **−pitch** (r −0.992), list is **+roll** (r +0.984), rotation is **+yaw**
  (r +0.989). This is not a column-naming confusion — the xlsx `Pelvis x/y/z` columns were verified
  to be exactly roll/pitch/yaw (r = 1.000 against the quaternion sheet of the same file).
- **Pelvis translation.** XtoO.m assigns `pelvis_ty` ← Xsens Y and `pelvis_tz` ← Xsens Z. Xsens is
  Z-up, OpenSim is Y-up: Xsens Z sits at 0.95–0.98 m (stature) and tracks OpenCap's `pelvis_ty`,
  while Xsens Y tracks `pelvis_tz` at r −0.994. **XtoO.m routes the subject's height into the
  lateral coordinate.** `pelvis_tx` ← Xsens X is correct in both, and correlates with OpenCap's at
  **r = +1.000**.

`legacy_axes=True` reproduces XtoO.m's original assignment so its exact output can be regenerated.

`q_to_euler.m` is ported verbatim including its use of `atan` rather than `atan2`, which limits
roll and yaw to ±90° and discards quadrant information. Kept deliberately: switching to `atan2`
would be a considered improvement needing re-validation, not a silent bug fix.

**Independent confirmation of our DOF partition.** `matrix_general.m` deletes rows
`[304:606, 1213:1313, 1920:2020, 2728:2828, 3233:3333]` — worked out against XtoO's column order,
exactly `pelvis_tx/ty/tz`, `mtp_angle_r/l` and `pro_sup_r/l`, leaving 26 coordinates. That is
essentially the exclusion set we reached independently from the variance analysis. It also carries
±180° unwrap corrections on the arm columns, so the arms gave trouble there too.

**Standing caveat.** This output *is* Xsens's joint angles under OpenSim names. Nothing solves a
model, so it inherits Xsens's biomechanics wholesale — a different scientific claim from IK. Our
earlier "conversion fidelity" figure (our `.mot` vs Xsens `<jointAngle>`, r ≈ 0.98) is trivially
1.0 for this path, because it *is* that data. A write-up must say which route produced its numbers.

**Not yet done:** `jointcheck.m`'s comparison plot (mean ± SD bands, Xsens vs OpenCap, 26
coordinates + 3 COM channels) and `matrix_general.m`'s ±180° unwrap, both of which operate on the
curve matrix rather than the `.mot`.

### The `atan` truncation in `q_to_euler.m` is real, and it corrupts one trial (2026-08-25)

Follow-up to the XtoO port. `q_to_euler.m` computes roll and yaw with `atan`, which caps them at
±90° and discards the quadrant. Initially ported verbatim; then checked against the data rather
than left as a theoretical caveat.

**It bites once in 15 trials, and the failure is invisible without looking for it.** CK-004's
pelvis yaw genuinely rotates to **−167.4°**. `atan` folds that back to **+88.2°**, producing a
false **175.3°** frame-to-frame discontinuity:

| convention | yaw range | discontinuities >90° | max frame-to-frame change |
|---|---|---|---|
| `atan` (XtoO.m) | −87.1 … 88.2 | **1** | **175.3°** |
| `atan2` | −167.4 … 14.3 | **0** | 4.9° |

The clipped range sitting exactly on ±87/88 is the truncation signature. `pelvis_rotation` is one
of the 26 coordinates the comparison uses, so a trial with a folded yaw carries a spurious 175°
step through every downstream analysis.

`use_atan2=True` is now the default: same numerators and denominators, quadrant resolved properly.
Inside ±90° the two are identical, so this only changes cases `atan` could not represent at all.
`use_atan2=False` reproduces the MATLAB exactly, and `legacy_axes=True` selects it automatically —
reproducing XtoO.m means reproducing all of it, not just the axis assignment.

**The ±180° unwrap from `matrix_general.m` was NOT ported, because this port does not need it.**
Across 15 trials and 11,785 frames, zero arm-coordinate samples fall below −140° (`arm_flex_r`
−31.2…147.0, `arm_flex_l` −24.8…30.4, and so on — all physiological). Those corrections were
patching a symptom in the original pipeline; with the axis assignment corrected and `atan2` in
place, the symptom does not arise. Porting them would have been cargo-culted cleanup on data that
does not exhibit the problem.

### Edit #15 — the foot progression angle reference heading was never the walking direction (2026-08-31)

The most consequential defect found in this codebase so far, because it is silent, it is in the
supervisor's own `getpelvis`, and it corrupts a variable that GDI is scored on.

`compute_foot_progression_angles` (our reformatting of `getpelvis`; math previously unchanged)
established the direction the subject walked, then expressed each foot's angle relative to it:

```python
x2, x1 = mean(direction[-4:, 0]), mean(direction[0:4, 0])
y2, y1 = mean(direction[-4:, 1]), mean(direction[0:4, 1])
heading = degrees(arctan2([y2 - y1], [x2 - x1]))[0]
```

**Two independent errors, both pushing the heading to approximately zero.**

**1. Wrong plane.** OpenSim's ground frame is X forward, **Y vertical**, Z lateral. Walking
happens in X-Z. The expression above measures forward travel against *vertical bob*. Measured on
ten OpenCap trials where the pelvis genuinely travels ~6 m:

| | as written | ground plane | error |
|---|---|---|---|
| `Trial1` | -0.77 deg | +5.78 deg | 6.55 |
| `Trial10` | -0.63 deg | +5.73 deg | 6.35 |
| `Trial3` | -0.93 deg | +2.34 deg | 3.27 |
| **mean over 10** | | | **5.26 deg** (max 6.55) |

The vertical term is 8 cm of body sway against 6 m of travel, so the result is always near zero.
That is *approximately* correct whenever a subject walks straight along +X, which is why it never
looked wrong — and wrong by the subject's actual walking angle whenever they did not.

**2. Degenerate under a pinned root.** The IMU route leaves `pelvis_tx/ty/tz` **exactly** constant
(measured range `0.00e+00`), so the expression evaluates `arctan2(0, 0) = 0` for every trial. FPA
then is not a progression angle at all: it is absolute foot yaw in the lab frame.

**What that did to the results.** Absolute foot yaw tracks the orientation estimate's heading
drift directly. Across all six participants, `|pelvis heading drift|` predicts the within-session
GDI change at **r = -0.947, about -0.72 GDI points per degree**:

| participant | pelvis drift | fpa right | fpa left | GDI right |
|---|---|---|---|---|
| AN | +27.3 | +20.7 | -27.9 | -18.4 |
| CK | +4.7 | +3.4 | -3.8 | -7.5 |
| HH | -1.5 | -1.4 | +2.7 | +0.7 |
| KM | -20.3 | -15.3 | +15.4 | -12.8 |
| MS | **-36.1** | -26.6 | +31.8 | **-29.6** |
| SB | -10.6 | +9.7 | -9.0 | -12.8 |

Four of six sessions carry 10-36 degrees of heading drift, so for those participants most of the
GDI movement within a session was the sensors, not the subject. The mirror-image sign between the
two feet is *not* physical: `fpa_l = heading - euler_l` is negated by construction, so with
`heading = 0` a common-mode drift necessarily appears with opposite signs on the two feet.

**The repair.** `walking_heading()` measures `arctan2(dz, dx)` in the ground plane, and falls back
to the circular mean of pelvis yaw when displacement is under 10 cm — the only body-referenced
direction available on a pinned-root route, and one that makes FPA immune to common-mode heading
drift by construction.

Deliberately **preserved**, because they are the supervisor's conventions rather than errors: the
`+/-5` degree foot offsets, the mirrored left/right sign, one scalar heading per trial, the Euler
`xyz` component `[1]`, and FPA's membership of the GDI feature set.

**Verified on the worst case** (MS, -36.1 deg heading drift):

| | before | after | reduction |
|---|---|---|---|
| `fpa_l` drift | +31.80 deg | -1.01 deg | 97% |
| `fpa_r` drift | -26.64 deg | +6.16 deg | 77% |

The residual on the right is on the side that shows genuine right-foot divergence in the raw
recording, so some of it is expected to be real rather than an incomplete fix.

**Scope of what this invalidates.** Every FPA value and every GDI score this project produced
before 2026-08-31, on both routes. Pre-fix curve exports are retained per session as
`GaitCurves_pre-fpa-fix/` rather than deleted. It also affects the supervisor's own OpenCap
results, independently of anything in this repository — there by ~5 degrees rather than totally,
which is small enough to have gone unnoticed and large enough to move a score.


---

### Found in the vendored GDI driver, deliberately NOT ported (2026-08-31)

Recorded because the natural instinct on seeing `context/replay-os-small/gaitAnalysis.py` is to
port its cycle-selection stage into the live pipeline. Do not. The stage is broken, the live
pipeline has no equivalent, and it does not need one. Full analysis in
`docs/2026-08-31-gdi-vs-ucm-audit.md`.

**The per-cycle selection is index-confused** (`gaitAnalysis.py:413`, and again at `:659` for the
left leg). It computes a functional depth per cycle, argsorts it, then writes:

```python
c = np.argsort(overalldepth)                     # c[k] = index of the k-th most central cycle
data3 = reduceddat[:, (abs(rsco) < 3).flatten()] # MAD outlier rejection
c2    = c[(abs(rsco) < 3).flatten()]
if len(c2) > 5:
    data2 = reduceddat[:, (c < 6).flatten()]     # both defects are on this line
```

`(c < 6)` masks the *ranks*, not the cycles. With eight cycles of depth `[5,1,9,2,8,3,7,4]` the six
most central are columns `[1,3,5,7,0,6]`; this selects columns `[0,1,2,4,6,7]`, which includes the
two **deepest**. The intended expression is `reduceddat[:, c[:6]]`.

The same line indexes `reduceddat` rather than `data3`, so whenever more than five cycles survive
MAD rejection — the normal case — **the outlier rejection is computed and then discarded.**

**The depth measure misses a point per variable** (`gaitAnalysis.py:395`, `:641`).
`reduceddat[starts[j]+1 : starts[j+1]-2]` plus the two endpoints covers 50 of each variable's 51
indices — index 49 of each block is never included — and the sum is divided by 50.

**Two aliases that are safe today and must not be "tidied".** `diff = subject` and `rsco = ap`
create references, not copies. Both happen to be correct because each column is read before it is
written; a refactor that reorders those reads would silently corrupt the distance.

**Why nothing was ported.** `joint_confidence.py` is the only repo file containing `argsort` and it
sorts timestamps. The live route scores every stride (`curve_features.score_curves`) and averages
the scores, which needs no cycle selection at all: `session_drift.py` already consumes it that way.
If per-cycle selection is ever wanted, write it fresh against the corrected expression above.

**Also present in the supplied `context/gait_analysis/gait_analysis.py`,** which the GDI driver
imports and which is missing every repair this file records: edits #3, #4, #5, #12 and #14. Its
`getpelvis` still carries edit #15's vertical-plane heading. This is the argument for retiring the
vendored GDI path rather than repairing it.

**One correction to an earlier claim.** Edit #13's left/right return-order swap is **not** in the
supplied copy — all three of its returns are `rHS, lHS, rTO, lTO`
(`context/gait_analysis/gait_analysis.py:772, 871, 906`). Whatever copy the swap was found in, it
was not this one, and results processed through the supplied file are unaffected by it.
