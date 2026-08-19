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

**Timing was never recorded during this run** — the ~5-minute total (parse+write ~1s,
calibrate <1s, IMU IK ~4m58s, i.e. ~115ms/frame) was reconstructed after the fact from output-file
timestamps, not measured directly. Fixed 2026-08-18: `xsens_to_opensim.py`'s `main()` now times
each of the three stages with `time.perf_counter()`, prints them, and writes them to
`<results-dir>/timing.txt` alongside the IK output on every run, so this doesn't need forensic
reconstruction again. Verified with a smoke test (stage functions replaced with fast stand-ins) and
the existing 26-test suite; not re-verified against a real 5-minute run since the original run's
uncalibrated scaled model isn't available in this session to redo it cheaply.

## Update 2026-08-19: re-ran against the real trial with real timing, results reproducible

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
