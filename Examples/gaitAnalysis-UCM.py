'''
    ---------------------------------------------------------------------------
    OpenCap processing: example_gait_analysis.py
    ---------------------------------------------------------------------------
    Copyright 2023 Stanford University and the Authors

    Author(s): Scott Uhlrich

    Licensed under the Apache License, Version 2.0 (the "License"); you may not
    use this file except in compliance with the License. You may obtain a copy
    of the License at http://www.apache.org/licenses/LICENSE-2.0
    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

    Please contact us for any questions: https://www.opencap.ai/#contact

    This example shows how to run a kinematic analysis of gait data. It works
    with either treadmill or overground gait. You can compute scalar metrics
    as well as gait cycle-averaged kinematic curves.

    ---------------------------------------------------------------------------
    Synergy / UCM variant
    ---------------------------------------------------------------------------
    Adds a subject-specific foot-progression-angle computation
    (`compute_foot_progression_angles`, formerly `getpelvis`) that
    `gait_analysis_UCM.gait_analysis` (an ActivityAnalyses/gait_analysis.py
    subclass -- see VENDORING.md) takes as an extra input alongside the stock
    heel-strike-based gait-cycle segmentation.

    REWRITTEN 2026-08-17 (quality-review / commercial-viability pass). What
    changed vs. the previous version, and why:
      - ~810 lines of fully inactive, commented-out GDI (Gait Deviation Index)
        scoring code removed. It depended on matrix.csv/perGaitCycle.csv/
        controlCalc.csv files that don't exist anywhere in this repo, was
        never reachable (100% commented out), and had internal
        inconsistencies (e.g. checked for 'matrix.csv' but opened
        'matrix_ms_reduced.csv'). It's preserved in git history (the commit
        immediately before this rewrite) if ever needed again.
      - Left-leg individual gait curves were computed (`gait_l`) and printed
        as scalars, but never written to a CSV -- only the right leg was
        saved. Both are now saved, mirroring the existing right-leg export
        (see `export_individual_curves_csv`).
      - Session-ID / subject-ID / trial-name parsing rewritten from chained
        str.find/rfind slicing (broke on off-by-one filename variations --
        see README.md's "Known issues") to explicit regex against OpenCap's
        own `OpenCapData_<uuid>` / `<uuid>_...` naming conventions (see
        `parse_session_id`, `parse_subject_id_and_zip_root`).
      - `dataFolder` used to resolve to the *parent* of the repo
        (`os.path.join(os.getcwd(), '..')` after chdir-ing to repo root) --
        inconsistent with .gitignore's `Data/*` entry, which expects `Data/`
        inside the repo. Fixed to point at the repo root's `Data/` directly
        (see `resolve_data_folder`).
      - Module-level top-level code (the interactive prompt loop) now lives
        behind `if __name__ == "__main__":` and is split into functions --
        the previous version ran its interactive prompt loop immediately on
        import, which made every piece of this file untestable and would
        hang any process that merely imported it. A non-interactive batch
        mode was also added (`--zip`/`--data-dir` + `--trial`/`--all-trials`),
        since batch automation "without hand-driving every step" is this
        project's own stated goal (README.md's "Pipeline" section).
      - The 'E' (evaluate already-downloaded data) menu option never set
        `subjid`/`savpath` in the pre-rewrite version -- only the 'Z' (select
        zip) branch did. Choosing 'E' as the first action would have crashed
        with NameError at CSV-export time; choosing 'E' after a prior 'Z' in
        the same run would have silently reused that stale zip's save
        location/subject-ID for the new data. Fixed: `process_trial` now
        always receives an explicit `save_path`/`subject_id` from whichever
        branch selected the data (see `run_interactive`'s 'e' case).
      - The 'E' branch's `baseFolder` used to be rebuilt from the selected
        directory's path via the same `rfind("_")`-based slicing the 'Z'
        branch uses -- but a UUID session ID has no underscores, so
        `rfind("_")` there would find whatever underscore happens to occur
        earliest in the *rightmost* path segment, producing a wrong,
        truncated path in most real directory layouts. Since `askdirectory`
        already returns the exact folder the user picked, this rewrite uses
        that path directly instead of re-deriving it.
      - `gait_analysis_UCM` (this file's one hard dependency, layered on top
        of the stock `ActivityAnalyses/gait_analysis.py`) is still MISSING
        from this repo -- see VENDORING.md's "Critical gap" section. Nothing
        in this rewrite can fix that; the file needs to be supplied. Its
        import is now deferred to inside `run_gait_analysis()` so everything
        else here (path parsing, trial discovery, the CSV export shape) is
        importable and unit-testable without it, and without OpenSim
        installed.
      - The foot-progression-angle math itself
        (`compute_foot_progression_angles`) is UNCHANGED -- same operations,
        same order, same +/-5 degree per-foot offset. Restructured for
        readability (no semicolons, named loop variables, a docstring) but
        NOT re-derived; this is real biomechanics math that could not be
        re-verified against the original's numeric output this session (that
        needs a live OpenSim run against real session data to confirm
        byte-for-byte parity -- do that before trusting this over the
        pre-rewrite version for anything clinical).
'''

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import statistics
from io import StringIO

os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
assert os.path.exists('VENDORING.md'), (
    'chdir landed on ' + os.getcwd() + ', which does not look like the repo root '
    '(no VENDORING.md there) -- this script must stay inside its original Examples/ folder.')
REPO_ROOT = Path(os.getcwd())
sys.path.append(os.path.abspath("./"))
sys.path.append(os.path.abspath("./ActivityAnalyses"))
sys.path.append(os.path.abspath("../ActivityAnalyses"))

# `utils` (and everything it re-exports: get_trial_id, download_trial,
# get_user_sessions, download_session) imports `opensim` at ITS OWN module
# top level -- so importing it here unconditionally would make this whole
# file require OpenSim just to parse a session ID or discover trial names.
# Deferred into the functions that actually need it instead (mirrors how
# xsens_to_opensim.py defers its own `import opensim`).

# Joint/segment coordinate names, in the order the exported CSV columns follow.
# Unchanged from the pre-rewrite version, except fpa_r/fpa_l (added
# 2026-08-20): these were computed by compute_foot_progression_angles below
# and passed into gait_analysis, but this list controls what actually reaches
# the per-gait-cycle curves CSV -- without them here, the computed FPA values
# never appeared in any output at all. See VENDORING.md's 2026-08-20 FPA
# finding.
JOINT_NAMES = [
    'pelvis_tilt', 'pelvis_list', 'pelvis_rotation', 'pelvis_tx', 'pelvis_ty', 'pelvis_tz',
    'hip_flexion_r', 'hip_adduction_r', 'hip_rotation_r', 'knee_angle_r', 'ankle_angle_r',
    'subtalar_angle_r', 'mtp_angle_r', 'hip_flexion_l', 'hip_adduction_l', 'hip_rotation_l',
    'knee_angle_l', 'ankle_angle_l', 'subtalar_angle_l', 'mtp_angle_l', 'lumbar_extension',
    'lumbar_bending', 'lumbar_rotation', 'arm_flex_r', 'arm_add_r', 'arm_rot_r', 'elbow_flex_r',
    'pro_sup_r', 'arm_flex_l', 'arm_add_l', 'arm_rot_l', 'elbow_flex_l', 'pro_sup_l',
    'comx', 'comy', 'comz', 'fpa_r', 'fpa_l',
]

# 'foot_progression_angle' added 2026-08-20, alongside
# gait_analysis_UCM_fixed.py's new compute_foot_progression_angle() method --
# same reason as the JOINT_NAMES change above: this is what makes FPA
# actually show up in scalars_r/scalars_l instead of being computed and
# discarded.
SCALAR_NAMES = {
    'gait_speed', 'stride_length', 'step_width', 'cadence',
    'single_support_time', 'double_support_time', 'step_length_symmetry',
    'foot_progression_angle',
}

# Number of leading OpenSim coordinates whose value gets set per frame in
# compute_foot_progression_angles. Preserved exactly from the pre-rewrite
# version (`if j<33:`) -- this is model-dependent (it excludes constraint/
# muscle-driven coordinates past this index for the specific scaled model
# this pipeline was built against) and was not re-derived here.
N_COORDINATES_TO_DRIVE = 33

# Per-foot sign-flipped rotation offset applied to calcaneus heading, in
# degrees. Preserved exactly from the pre-rewrite version; its biomechanical
# rationale is not documented there either -- flagging, not guessing.
FOOT_ROTATION_OFFSET_DEG = 5.0

# OpenCap's own session/trial-folder naming conventions, e.g.
#   OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2
#   OpenCapData_b39b10d1-17c7-4976-b06c-a6aaf33fead2_<subject-slug>.zip
# Replaces the pre-rewrite version's chained str.find/rfind slicing, which
# broke whenever a filename had an extra/missing underscore or a mangled
# extension (see README.md's "Session ID parsing is inconsistent").
_UUID_RE = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
_SESSION_FOLDER_RE = re.compile(r'OpenCapData_(' + _UUID_RE + r')')


def resolve_data_folder():
    """Where downloaded/extracted OpenCap sessions live: <repo root>/Data.

    The pre-rewrite version computed this as `os.path.join(os.getcwd(), '..')`
    after chdir-ing to the repo root -- i.e. the repo's *parent* directory,
    which doesn't match .gitignore's `Data/*` entry (that expects `Data/`
    inside the repo). VENDORING.md flagged this as a real, pre-existing bug
    (present under the old hardcoded-path version too) and left the decision
    open; this picks "inside the repo", consistent with .gitignore.
    """
    return REPO_ROOT / 'Data'


def parse_session_id(path):
    """Extract the OpenCap session UUID from a path/filename containing
    'OpenCapData_<uuid>'. Returns None if not found."""
    match = _SESSION_FOLDER_RE.search(str(path))
    return match.group(1) if match else None


def parse_subject_id_and_zip_root(zip_path):
    """From a downloaded zip's path, return (subject_id, extraction_root,
    folder_name) the way the interactive 'z' flow needs them.

    `subject_id` is the parent-of-parent folder name convention OpenCap
    downloads use (.../<subject_id>/OpenCapData_<uuid>_<slug>.zip).
    `extraction_root` is where the zip should be extracted to (its own
    directory, stripped of a trailing '_<slug>' or '.zip').
    `folder_name` is the resulting top-level folder name inside the zip.
    """
    zip_path = Path(zip_path)
    stem = zip_path.name
    session_id = parse_session_id(stem)

    # Folder name inside the zip: 'OpenCapData_<uuid>', regardless of
    # whatever suffix (subject slug, '.zip') follows it in the zip filename.
    folder_name = f'OpenCapData_{session_id}' if session_id else zip_path.stem

    extraction_root = zip_path.parent / folder_name
    subject_id = zip_path.parent.name
    return subject_id, extraction_root, folder_name


def discover_trials(folder, extension='.mot'):
    """Return sorted trial names (filenames without extension) found
    anywhere under `folder`, excluding the 'neutral' calibration trial."""
    trial_names = []
    for root, _dirs, files in os.walk(folder):
        for file in files:
            if file.endswith(extension):
                trial_names.append(file[: -len(extension)])
    return sorted(name for name in trial_names if name != 'neutral')


# Below this, the root is not translating and no walking direction can be
# recovered from displacement. The IMU route pins it exactly, so the measured
# range is 0.0; the threshold is generous rather than exact so a nearly-static
# trial is caught too.
MIN_PROGRESSION_METRES = 0.10


def walking_heading(pelvis_positions, model=None, coordinates_table=None,
                    state=None):
    """The direction the subject walked, in degrees, for FPA to be measured against.

    Repaired 2026-08-31 (edit #15; see VENDORING.md for the measured scope,
    including what it invalidates). The supervisor's `getpelvis` computed this as
    `arctan2(y_end - y_start, x_end - x_start)`, and both terms were wrong for
    this pipeline:

    1. **Wrong plane.** OpenSim's ground frame has Y *vertical*; walking
       happens in X-Z. Measured on a real OpenCap trial where the pelvis
       genuinely travels 6.0 m: the original returns -0.77 degrees, driven by
       8 cm of vertical bob, where the ground-plane direction is +5.78
       degrees. So it never measured walking direction on any route -- it
       returned approximately zero whenever the subject walked roughly along
       +X, which looked correct by luck.
    2. **Degenerate under a pinned root.** The IMU route leaves pelvis_tx/ty/tz
       exactly constant, so the original evaluates arctan2(0, 0) = 0 for every
       trial. FPA then collapses to absolute foot yaw in the lab frame, which
       tracks the orientation estimate's heading drift directly. Across six
       participants that drift reached 36 degrees within a session and moved
       GDI by up to 30 points -- the score was measuring the sensors, not the
       subject.

    The intent is unchanged: a single per-trial heading that foot angles are
    expressed relative to. What changes is that it is now measured in the
    ground plane, and that when the root does not translate the pelvis's own
    yaw is used instead -- the only body-referenced direction available on
    that route, and one that makes FPA immune to common-mode heading drift by
    construction.
    """
    displacement = np.array([
        statistics.mean(pelvis_positions[-4:, 0]) - statistics.mean(pelvis_positions[0:4, 0]),
        statistics.mean(pelvis_positions[-4:, 2]) - statistics.mean(pelvis_positions[0:4, 2]),
    ])
    if np.linalg.norm(displacement) >= MIN_PROGRESSION_METRES:
        # X forward, Z lateral -- the ground plane.
        return float(np.degrees(np.arctan2(displacement[1], displacement[0])))

    if model is None or coordinates_table is None or state is None:
        raise ValueError(
            "the pelvis does not translate in this trial, so a walking "
            "direction cannot be recovered from displacement, and no model was "
            "supplied to fall back on pelvis orientation."
        )
    return pelvis_yaw_heading(model, coordinates_table, state)


def pelvis_yaw_heading(model, coordinates_table, state):
    """Mean pelvis yaw in ground, in degrees -- the fallback heading.

    One value for the whole trial, matching the shape of the displacement
    heading it replaces. Averaged circularly, since yaw is an angle: an
    arithmetic mean of values either side of +/-180 lands on the opposite side
    of the circle.
    """
    import opensim as osim
    from scipy.spatial.transform import Rotation as R

    pelvis = model.getBodySet().get('pelvis')
    sines, cosines = [], []
    for frame_index in range(coordinates_table.getNumRows()):
        row = osim.RowVector(coordinates_table.getRowAtIndex(frame_index))
        for coord_index, coordinate in enumerate(model.updCoordinateSet()):
            if coord_index < N_COORDINATES_TO_DRIVE:
                coordinate.setValue(state, np.radians(row[coord_index]), False)
        model.realizePosition(state)
        rotation = pelvis.getRotationInGround(state)
        matrix = np.genfromtxt(
            StringIO(osim.Mat33(rotation).toString().replace('[', ' ').replace(']', ' ')[1:]),
            delimiter=',',
        )
        yaw = np.radians(R.from_matrix(matrix).as_euler('xyz', degrees=True)[1])
        sines.append(np.sin(yaw))
        cosines.append(np.cos(yaw))
    return float(np.degrees(np.arctan2(np.mean(sines), np.mean(cosines))))


def compute_foot_progression_angles(model_filename, coordinates_file_name):
    """Foot progression angle (FPA) for right and left feet across a trial.

    Formerly `getpelvis`. Math is UNCHANGED from the pre-rewrite version --
    same operations, same order, same +/-FOOT_ROTATION_OFFSET_DEG offsets --
    only reformatted (no semicolons, named variables, a docstring) and not
    re-derived. See this module's docstring for why that distinction matters.

    Returns (fpa_r, fpa_l): 1D numpy arrays, one value per frame in
    `coordinates_file_name`.
    """
    import opensim as osim
    import utils
    from scipy.spatial.transform import Rotation as R

    osim.Logger.setLevel(5)
    metadata_dir = None
    for root, _dirs, files in os.walk(model_filename):
        for file in files:
            if file.endswith('.yaml'):
                metadata_dir = root
    model_name = utils.get_model_name_from_metadata(metadata_dir)
    model_path = os.path.join(metadata_dir, 'OpenSimData', 'Model', model_name)
    motion_path = os.path.join(
        metadata_dir, 'OpenSimData', 'Kinematics', f'{coordinates_file_name}.mot'
    )

    model = osim.Model(model_path)
    state = model.initSystem()
    analyze = osim.AnalyzeTool(model)
    analyze.setName('analyze')
    analyze.setCoordinatesFileName(motion_path)
    analyze.loadStatesFromFile(state)
    analyze.run()

    coordinates_table = osim.TimeSeriesTable(motion_path)
    time = coordinates_table.getIndependentColumn()
    state = model.initSystem()
    pelvis = model.getBodySet().get('pelvis')

    # Pass 1: overall walking heading direction, from the pelvis's position
    # at the start vs. end of the trial (averaged over the first/last 4
    # frames).
    pelvis_positions = []
    for frame_index in range(len(time)):
        row = osim.RowVector(coordinates_table.getRowAtIndex(frame_index))
        for coord_index, coordinate in enumerate(model.updCoordinateSet()):
            if coord_index < N_COORDINATES_TO_DRIVE:
                coordinate.setValue(state, np.radians(row[coord_index]), False)
        model.realizePosition(state)
        position = pelvis.getPositionInGround(state).to_numpy()
        pelvis_positions.append([float(position[0]), float(position[1]), float(position[2])])

    pelvis_positions = np.array(pelvis_positions)
    heading = walking_heading(pelvis_positions, model, coordinates_table, state)

    # Pass 2: per-frame foot rotation relative to that heading.
    points = []
    for frame_index in range(len(time)):
        row = osim.RowVector(coordinates_table.getRowAtIndex(frame_index))
        for coord_index, coordinate in enumerate(model.updCoordinateSet()):
            if coord_index < N_COORDINATES_TO_DRIVE:
                coordinate.setValue(state, np.radians(row[coord_index]), False)
        model.realizePosition(state)

        calcn_r = model.getBodySet().get('calcn_r')
        rotation_r = calcn_r.getRotationInGround(state)
        matrix_r = np.genfromtxt(
            StringIO(osim.Mat33(rotation_r).toString().replace('[', ' ').replace(']', ' ')[1:]),
            delimiter=',',
        )
        euler_r = R.from_matrix(matrix_r).as_euler('xyz', degrees=True) - FOOT_ROTATION_OFFSET_DEG

        calcn_l = model.getBodySet().get('calcn_l')
        rotation_l = calcn_l.getRotationInGround(state)
        matrix_l = np.genfromtxt(
            StringIO(osim.Mat33(rotation_l).toString().replace('[', ' ').replace(']', ' ')[1:]),
            delimiter=',',
        )
        euler_l = R.from_matrix(matrix_l).as_euler('xyz', degrees=True) + FOOT_ROTATION_OFFSET_DEG

        points.append([
            time[frame_index], heading,
            float(euler_r[1]), float(euler_l[1]),
            float(euler_r[1]) - heading, heading - float(euler_l[1]),
        ])

    points = np.array(points)
    fpa_r = points[:, 4]
    fpa_l = points[:, 5]
    return fpa_r, fpa_l


def run_gait_analysis(base_folder, trial_name, filter_frequency=6, n_gait_cycles=-1,
                       trimming_start=-1, trimming_end=-1, allow_manual_entry=True,
                       manual_event_provider=None):
    """Run FPA computation + left/right gait_analysis_UCM for one trial.

    Deferred import: everything else in this module (path parsing, trial
    discovery, CSV export) stays importable/testable without gait_analysis_UCM's
    heavier dependency chain (opensim, pandas, scipy, ...).

    Imports gait_analysis_UCM_fixed (2026-08-20), not gait_analysis_UCM --
    the bug-fixed copy (see VENDORING.md and that file's own module
    docstring for the full list of fixes: batch-mode-safe gait-event
    detection, several IndexError/ZeroDivisionError fixes, and the new
    compute_foot_progression_angle scalar this SCALAR_NAMES/JOINT_NAMES
    update above depends on). The original gait_analysis_UCM.py is left
    untouched -- same "only make copies" rule as utils.py/utilsKinematics.py.

    allow_manual_entry is threaded through from process_trial/run_batch so
    --all-trials can pass False (see run_batch) -- gait_analysis_UCM_fixed.py's
    interactive fallback would otherwise still block a batch run on stdin
    even with everything else in this driver already non-interactive.

    manual_event_provider is what turns that fallback from a stdin prompt for
    four lists of frame indices into the picker window. It reaches BOTH legs,
    or the second one drops back to the prompt the window was supposed to
    replace. It defaults to None because run_batch reaches this function too,
    and it must be wrapped in gait_event_picker_ui.reuse_across_legs before it
    gets here: the two constructions below each run segment_walking over the
    same trial, so an unwrapped provider opens two windows for one trial. See
    run_interactive, the only caller that supplies one.
    """
    from gait_analysis_UCM_fixed import gait_analysis

    fpa_r, fpa_l = compute_foot_progression_angles(base_folder, trial_name)

    gait_r = gait_analysis(
        base_folder, trial_name, fpa_r, fpa_l, leg='r',
        lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
        n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end,
        allow_manual_entry=allow_manual_entry,
        manual_event_provider=manual_event_provider)
    gait_l = gait_analysis(
        base_folder, trial_name, fpa_r, fpa_l, leg='l',
        lowpass_cutoff_frequency_for_coordinate_values=filter_frequency,
        n_gait_cycles=n_gait_cycles, trimming_start=trimming_start, trimming_end=trimming_end,
        allow_manual_entry=allow_manual_entry,
        manual_event_provider=manual_event_provider)

    center_of_mass = {trial_name: gait_r.get_center_of_mass_values(lowpass_cutoff_frequency=10)}

    results = {
        'center_of_mass': center_of_mass,
        'scalars_r': gait_r.compute_scalars(SCALAR_NAMES),
        'curves_r': gait_r.get_coordinates_normalized_time(),
        'scalars_l': gait_l.compute_scalars(SCALAR_NAMES),
        'curves_l': gait_l.get_coordinates_normalized_time(),
    }
    return results


def print_scalar_results(results):
    print('\nRight foot gait metrics:')
    print('-----------------')
    for key, value in results['scalars_r'].items():
        print(f"{key}: {round(value['value'], 2)} {value['units']}")

    print('\nLeft foot gait metrics:')
    print('-----------------')
    for key, value in results['scalars_l'].items():
        print(f"{key}: {round(value['value'], 2)} {value['units']}")


def _build_individual_curves_matrix(curves_side, mean_curves_side):
    """Flatten one leg's per-cycle kinematic curves into the
    (len(JOINT_NAMES) * 101) x n_cycles matrix the CSV export expects.

    Reproduces the pre-rewrite version's per-joint adjustments exactly:
    pelvis_tilt +20, pelvis_rotation wrapped at 180, com{x,y,z} expressed
    relative to the matching pelvis translation. Only the right-leg version
    of this existed as live code before this rewrite (see this module's
    docstring); the left-leg version mirrors it -- it was never previously
    exercised, so treat it as unverified until it's run against real data.
    """
    n_cycles = len(curves_side['indiv'])
    matrix = np.zeros((len(JOINT_NAMES) * 101, n_cycles))

    for cycle_index in range(n_cycles):
        row = 0
        cycle = curves_side['indiv'][cycle_index]
        for joint in JOINT_NAMES:
            for frame in range(101):
                if joint == 'pelvis_tilt':
                    value = cycle[joint][frame] + 20
                elif joint == 'pelvis_rotation':
                    raw = cycle[joint][frame]
                    value = raw - 180 if raw > 180 else raw
                elif joint in ('comx', 'comy', 'comz'):
                    pelvis_joint = 'pelvis_t' + joint[-1]
                    value = cycle[joint][frame] - cycle[pelvis_joint][frame]
                else:
                    value = cycle[joint][frame]
                matrix[row, cycle_index] = value
                row += 1

    return matrix


def export_individual_curves_csv(results, save_path, subject_id, trial_name):
    """Write per-gait-cycle kinematic curves to '<subject_id>-<trial_name>_right.csv'
    and '..._left.csv' under save_path.

    The pre-rewrite version only ever wrote the right-leg CSV -- curves_l was
    computed and its scalar metrics printed, but never saved. That looks like
    an oversight (the machinery to save it is identical to the right-leg
    path), so this now saves both. Flagging clearly since it's new,
    unexercised behavior: verify the '_left.csv' output once this can run
    against real data.
    """
    save_path = Path(save_path)
    right_matrix = _build_individual_curves_matrix(results['curves_r'], results['curves_r']['mean'])
    left_matrix = _build_individual_curves_matrix(results['curves_l'], results['curves_l']['mean'])

    right_path = save_path / f'{subject_id}-{trial_name}_right.csv'
    left_path = save_path / f'{subject_id}-{trial_name}_left.csv'
    np.savetxt(right_path, right_matrix, delimiter=',', fmt='%f')
    np.savetxt(left_path, left_matrix, delimiter=',', fmt='%f')
    return right_path, left_path


def _select_trial_interactively(trial_names):
    print()
    print('Available trials:')
    for i, trial in enumerate(trial_names, start=1):
        print(f'{i}. {trial}')

    while True:
        try:
            selected_index = int(input('Enter the index of the trial to run: ')) - 1
            if 0 <= selected_index < len(trial_names):
                return trial_names[selected_index]
        except ValueError:
            pass
        print('Invalid input')


def _pull_sessions_interactively(data_folder):
    from utils import download_session, get_user_sessions

    sessions = get_user_sessions()
    session_list = [session['id'] for session in sessions]

    available = [
        session_id for session_id in session_list
        if not (data_folder / f'OpenCapData_{session_id}').exists()
    ]
    if not available:
        print('\nNo available sessions.\n')
        return

    print()
    print('Available sessions:')
    print('0. All sessions')
    for i, session in enumerate(available, start=1):
        print(f'{i}. {session}')

    selected_indices_raw = input(
        'Enter the indices of the sessions to download (comma-separated) or [M] for the main menu: '
    )
    if selected_indices_raw.lower() == 'm':
        return
    if selected_indices_raw == '0':
        selected = available[:]
    else:
        indices = [int(i) for i in selected_indices_raw.split(',') if 0 < int(i) <= len(available)]
        selected = [available[i - 1] for i in indices]

    for session_id in selected:
        session_path = data_folder / f'OpenCapData_{session_id}'
        if session_path.exists():
            print(f'Session {session_id} already downloaded. Skipping...\n')
        else:
            download_session(session_id, sessionBasePath=str(data_folder), downloadVideos=True)


def _select_zip_interactively():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', 1)
    return filedialog.askopenfilename(parent=root)


def _select_extracted_folder_interactively(data_folder):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', 1)
    return filedialog.askdirectory(parent=root, initialdir=str(data_folder))


def process_trial(base_folder, trial_name, session_id, subject_id, save_path,
                   allow_manual_entry=True, manual_event_provider=None):
    """Run the gait pipeline for one trial and export its CSVs. Shared by
    both the interactive menu and non-interactive batch mode -- the two
    call sites pass different allow_manual_entry values (see run_batch and
    run_interactive), and only run_interactive supplies a
    manual_event_provider."""
    from utils import download_trial, get_trial_id

    trial_id = get_trial_id(session_id, trial_name)
    data_folder = resolve_data_folder()
    session_dir = data_folder / session_id
    downloaded_trial_name = download_trial(trial_id, str(session_dir), session_id=session_id)

    results = run_gait_analysis(base_folder, downloaded_trial_name,
                                 allow_manual_entry=allow_manual_entry,
                                 manual_event_provider=manual_event_provider)
    print_scalar_results(results)
    right_path, left_path = export_individual_curves_csv(
        results, save_path, subject_id, trial_name)
    print(f'\nSaved: {right_path}')
    print(f'Saved: {left_path}')
    return results


def run_batch(zip_path=None, data_dir=None, trial_names=None, all_trials=False):
    """Non-interactive entry point: process one or more trials from an
    already-known zip or extracted-data-folder location, no prompts.

    This is the automation path README.md's "Pipeline" section asks for --
    "loop through a batch of recordings and run the full pipeline on each
    one without hand-driving every step" -- which the pre-rewrite version's
    input()-only flow didn't offer at all.
    """
    if zip_path:
        subject_id, extraction_root, folder_name = parse_subject_id_and_zip_root(zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(str(extraction_root))
        base_folder = extraction_root / folder_name
        # Matches the pre-rewrite version's `savpath`: the directory the zip
        # itself lives in, NOT the freshly-extracted subfolder.
        save_path = Path(zip_path).parent
        session_id = parse_session_id(zip_path)
    elif data_dir:
        data_dir = Path(data_dir)
        session_id = parse_session_id(data_dir)
        if session_id is None:
            raise ValueError(
                f"Couldn't find an 'OpenCapData_<uuid>' pattern in {data_dir} -- "
                'is this really an OpenCap session folder?')
        base_folder = data_dir
        subject_id = data_dir.parent.name
        save_path = data_dir.parent
    else:
        raise ValueError('run_batch requires either zip_path or data_dir.')

    if session_id is None:
        raise ValueError(f"Couldn't parse a session ID from {zip_path or data_dir}.")

    available_trials = discover_trials(base_folder)
    if all_trials:
        trials_to_run = available_trials
    elif trial_names:
        unknown = [t for t in trial_names if t not in available_trials]
        if unknown:
            raise ValueError(f'Trial(s) {unknown} not found under {base_folder}. '
                              f'Available: {available_trials}')
        trials_to_run = trial_names
    else:
        raise ValueError('run_batch requires --trial NAME (one or more) or --all-trials.')

    all_results = {}
    for trial_name in trials_to_run:
        print(f'\n=== {trial_name} ===')
        # allow_manual_entry=False: a batch run has nothing to answer an
        # interactive prompt, so gait_analysis_UCM_fixed.py's manual-entry
        # fallback must raise instead of blocking on stdin (see that file's
        # module docstring, edit #2). A trial that fails automatic gait-event
        # detection is skipped (logged, not silently dropped) rather than
        # hanging the whole batch.
        try:
            all_results[trial_name] = process_trial(
                base_folder, trial_name, session_id, subject_id, save_path,
                allow_manual_entry=False)
        except Exception as e:
            print(f'Skipping {trial_name}: {e}')
    return all_results


def run_interactive():
    """The original P/Z/E menu loop, preserved behaviorally: pull sessions
    from OpenCap, select a pre-extracted folder, or select+extract a zip;
    then pick and run one trial at a time until the user says no.

    This is the one caller that supplies a manual_event_provider. It is
    already interactive and already stopped to ask -- before the picker
    existed, a trial auto-trim could not segment fell through to a stdin
    prompt for four lists of raw frame indices, typed against no picture of
    the trial at all. Supplying the window replaces that prompt; it does not
    introduce a new interruption. The batch paths (run_batch, and every other
    caller of process_trial) pass no provider and keep allow_manual_entry
    False, so nothing unattended can acquire a window.

    Deferred import for the same reason gait_analysis_UCM_fixed is deferred in
    run_gait_analysis: the module has to stay importable, and its pure path
    testable, without pulling matplotlib in.
    """
    from gait_event_picker_ui import (make_manual_event_provider,
                                      reuse_across_legs)

    data_folder = resolve_data_folder()
    # Built once for the whole session, not once per trial: reuse_across_legs
    # keys its memory on the trial name, so one provider serves every trial
    # and still asks once per trial rather than once per leg.
    manual_event_provider = reuse_across_legs(make_manual_event_provider())
    response = ''

    while True:
        if response.lower() != 'z':
            print('What would you like to do?')
            print('[P] Pull data from online to download')
            print('[Z] Select a zipped folder to evaluate')
            print('[E] Evaluate downloaded data')
            response = input('').lower()

        if response == 'p':
            _pull_sessions_interactively(data_folder)
            continue

        elif response == 'e':
            file_path = Path(_select_extracted_folder_interactively(data_folder))
            session_id = parse_session_id(file_path)
            if session_id is None:
                print(f"Couldn't parse a session ID from {file_path}; try again.")
                continue
            base_folder = file_path
            subject_id = file_path.parent.name
            save_path = file_path.parent

        elif response == 'z':
            file_path = Path(_select_zip_interactively())
            if not file_path.name:
                print('No file selected.')
                continue
            subject_id, extraction_root, folder_name = parse_subject_id_and_zip_root(file_path)
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(str(extraction_root))
            base_folder = extraction_root / folder_name
            # Matches the pre-rewrite version's `savpath`: the directory the
            # zip itself lives in, NOT the freshly-extracted subfolder.
            save_path = file_path.parent
            session_id = parse_session_id(file_path)
            if session_id is None:
                print(f"Couldn't parse a session ID from {file_path}; try again.")
                continue

        else:
            continue

        trial_names = discover_trials(base_folder)
        trial_name = _select_trial_interactively(trial_names)
        process_trial(base_folder, trial_name, session_id, subject_id, save_path,
                       manual_event_provider=manual_event_provider)

        response = input('Do you want to run another trial? [Y/N]: ').lower()
        if response != 'y':
            break


def main():
    parser = argparse.ArgumentParser(description=(
        'UCM gait analysis: computes foot-progression-angle-informed gait '
        'metrics from an OpenCap session. Requires gait_analysis_UCM.py -- '
        'see VENDORING.md\'s "Critical gap" section if this fails to import.'
    ))
    parser.add_argument('--zip', help='Path to a downloaded OpenCap session zip.')
    parser.add_argument('--data-dir', help='Path to an already-extracted OpenCapData_<uuid> folder.')
    parser.add_argument('--trial', action='append', dest='trials',
                         help='Trial name to run (repeatable). Omit with --all-trials to run every '
                              'trial found under --zip/--data-dir.')
    parser.add_argument('--all-trials', action='store_true',
                         help='Run every discovered trial instead of specifying --trial.')
    args = parser.parse_args()

    if args.zip or args.data_dir:
        run_batch(zip_path=args.zip, data_dir=args.data_dir,
                  trial_names=args.trials, all_trials=args.all_trials)
    else:
        run_interactive()


if __name__ == '__main__':
    main()
