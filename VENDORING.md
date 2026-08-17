# Vendoring notes

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

## ⚠ No git commits yet

This repo has never been committed to (`git log` shows no commits; `git status` lists every
file, including the untouched vendored ones, as untracked). That means the "root `utils.py`/
`utilsKinematics.py` stay byte-identical to upstream" rule above is currently just an assertion in
this doc — there's no git history to actually verify it against, and nothing here is protected
from being accidentally overwritten or deleted. Recommend committing soon: first the untouched
vendored files as a clean baseline (ideally referencing the upstream commit hash above), then the
Synergy-specific overlay files and fixes as a separate commit on top, so future diffs against
upstream are actually checkable instead of resting on this file's word for it. Not done yet
pending your go-ahead (nothing gets committed without you asking for it).

## Files added from `utilsKinematics.zip` (sent 2026-08-14)

Nothing upstream is overwritten in place. Your versions live alongside the stock files as
separate `_UCM`-suffixed copies:

| File | Location | Status |
|---|---|---|
| `utils.py` (yours) | `utils_UCM.py` | Byte-identical to upstream HEAD content (only line-ending differed: your copy is LF, upstream ships CRLF). No functional edits detected. |
| `utilsKinematics.py` (yours) | `utilsKinematics_UCM.py` | Real edits. See "utilsKinematics_UCM.py diff" below. **Not currently imported by anything** — see "Import-name mismatch" below. |
| `gaitAnalysis-UCM.py` | `Examples/gaitAnalysis-UCM.py` | Added alongside the untouched `Examples/example_gait_analysis.py` it was based on (you said you *added* this one, not replaced). |
| `getMarkers.py` | repo root | Added; no upstream equivalent, so nothing to diff against. **Never reviewed in depth until 2026-08-17 — see below.** |

`utils.py` and `utilsKinematics.py` at the repo root are untouched stock upstream files.

### What `getMarkers.py` actually does (reviewed 2026-08-17)

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
- `test_utilsKinematics_UCM_modelpath.py` (2 tests) — kept deliberately small. Originally written
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
