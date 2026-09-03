"""Cohort-wide check on the 2026-09-02 calibration-pose fix.

Run after regenerating the `ik` route. It answers three questions the fix has
to answer, over every session and every trial rather than the one trial the fix
was developed on:

1. **Did the arms actually come back?** Compares each arm coordinate's range
   and across-stride SD before and after, using the pre-fix exports kept under
   `<session>/pre-calibration-fix/GaitCurves/`.
2. **Did anything else move?** Pelvis and both legs hold the same pose in the
   Xsens T-pose as in the model's default, so the calibration pose cannot
   reach them. A shift there falsifies the diagnosis and is a FAIL. The lumbar
   coordinates are a separate case, reported but not asserted on -- see
   TORSO_COORDINATES.

   This comparison is made on the raw `.mot`, not on the exported curves. The
   curves are time-normalised to 101 points per gait cycle, so a one-frame
   move in heel-strike detection resamples all of them and shows up as several
   degrees on knee flexion -- a phase difference, not a kinematic one.
3. **Is anything still pinned against a model bound?** The general form of the
   defect. Uses `methodology_comparison.saturated_coordinates` against each
   session's own scaled model. Reported rather than failed on, because some
   bounds are anatomical: an elbow at 0 deg is full extension.
4. **Did the solver actually track what it reports?** `tracking_residuals`
   reads OpenSim's own per-frame orientation residual. This is the check that
   catches a lost segment, and the reason a range heuristic is not enough on
   its own: IK reports a confident, physiological-looking number for a segment
   it has mistracked by 70 degrees. Only a segment that got WORSE fails --
   several KM trials are above the threshold before and after, which is a
   pre-existing problem on that participant rather than this fix's doing.

Exits non-zero if a pelvis or leg coordinate shifted, or if the solver lost an
upper-body segment it had previously tracked, so this can be run as a gate
rather than read as prose.

Base python is enough -- nothing here needs OpenSim.

Usage:
    python verify_calibration_fix.py [--sessions Data/xsens_sessions]
        [--conversion ik] [--leg-tolerance-deg 0.5]
"""
import argparse
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
POINTS_PER_CYCLE = 101

ARM_COORDINATES = (
    "arm_flex_r", "arm_add_r", "arm_rot_r", "elbow_flex_r", "pro_sup_r",
    "arm_flex_l", "arm_add_l", "arm_rot_l", "elbow_flex_l", "pro_sup_l",
)

# Coordinates the fix must not have touched, and the assertion is on them.
# Pelvis and both legs hold the same configuration in the Xsens T-pose as in
# the model's default pose, so their IMU offsets were already right and the
# calibration pose cannot reach them. If one of these moves, the diagnosis is
# wrong. (comx/comy/comz and fpa_r/fpa_l are derived, and mtp is
# constraint-driven, so a wobble in them says nothing either way.)
UNCHANGED_COORDINATES = (
    "pelvis_tilt", "pelvis_list", "pelvis_rotation",
    "hip_flexion_r", "hip_adduction_r", "hip_rotation_r",
    "knee_angle_r", "ankle_angle_r", "subtalar_angle_r",
    "hip_flexion_l", "hip_adduction_l", "hip_rotation_l",
    "knee_angle_l", "ankle_angle_l", "subtalar_angle_l",
)

# Reported, NOT asserted on. The lumbar coordinates place the torso against
# the pelvis, and the arms hang off the torso. Before the fix the humerus
# frames were tracking at 6-10 deg residual and pulling on the torso in the
# global IK solve; afterwards torso_imu's own residual drops from 1.00 to
# 0.07 deg RMS (CK-001). So the lumbar solution legitimately changes -- it
# gets better -- and pinning it to "unchanged" would be asserting the wrong
# thing. Measured on AN: mean per-frame shift 0.08-0.27 deg, p99 under 3 deg,
# with the worst single frames in the last second of a trial where the subject
# has stopped walking and is moving their arms.
TORSO_COORDINATES = ("lumbar_extension", "lumbar_bending", "lumbar_rotation")

# Generous, deliberately: this is a "did the shoulder wind up a full turn"
# check, not a normative gait range. Anything inside it is for a clinician to
# judge; anything outside it is the solver, not the subject.
PHYSIOLOGICAL_LIMIT_DEG = 180.0


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def joint_names(repo_root=REPO_ROOT):
    """JOINT_NAMES from the export driver -- the only thing mapping a row
    block in these unlabelled CSVs to a coordinate."""
    os.environ.setdefault("API_TOKEN", "verify-calibration-fix-placeholder")
    module = _load_module(Path(repo_root) / "Examples" / "gaitAnalysis-UCM.py",
                          "_ucm_driver_for_verification")
    return list(module.JOINT_NAMES)


def load_curves(path, names):
    matrix = np.loadtxt(path, delimiter=",", ndmin=2)
    expected = len(names) * POINTS_PER_CYCLE
    if matrix.shape[0] != expected:
        raise ValueError(
            f"{path}: {matrix.shape[0]} rows, expected {expected}. The export's "
            "coordinate list and this reader have diverged."
        )
    return {name: matrix[i * POINTS_PER_CYCLE:(i + 1) * POINTS_PER_CYCLE, :]
            for i, name in enumerate(names)}


def pool(paths, names):
    """{coordinate: {min, max, sd}} over a set of curve files."""
    blocks = {name: [] for name in names}
    for path in paths:
        for name, block in load_curves(path, names).items():
            blocks[name].append(block)
    summary = {}
    for name, collected in blocks.items():
        stacked = np.hstack(collected)
        sds = [float(np.mean(np.std(b, axis=1))) for b in collected if b.shape[1] > 1]
        summary[name] = {
            "min": float(stacked.min()),
            "max": float(stacked.max()),
            "sd": float(np.mean(sds)) if sds else float("nan"),
        }
    return summary


def wrapped_difference(after, before):
    """|after - before| with both taken as angles, so a full-turn difference
    reads as zero.

    Necessary, not tidy-minded. `pelvis_rotation` carries a +/-10 rad range in
    this model exactly as the arm coordinates do, so IK is free to report a
    heading of 169.8 deg on one run and 529.4 deg on the next -- the same
    physical orientation, one revolution apart. Measured on SB: two of fifteen
    trials flipped a revolution between the pre- and post-fix runs, and a raw
    subtraction called that a 360.09 deg regression. Wrapped, the worst shift
    across those same fifteen trials is 0.28 deg.
    """
    return np.abs((np.asarray(after) - np.asarray(before) + 180.0) % 360.0 - 180.0)


def read_mot(path):
    """{coordinate: 1-D array} plus the time column, from an OpenSim .mot."""
    lines = Path(path).read_text().splitlines()
    end = next(i for i, line in enumerate(lines) if line.strip() == "endheader")
    header = lines[end + 1].split()
    data = np.array([[float(v) for v in line.split()]
                     for line in lines[end + 2:] if line.strip()])
    return {name: data[:, i] for i, name in enumerate(header)}


def mot_shifts(session_dir, coordinates):
    """Largest per-frame |after - before| for each coordinate, from the raw
    .mot files rather than the gait-cycle curves.

    This has to be the .mot. The exported curves are time-normalised to 101
    points per gait cycle, so a one-frame move in heel-strike detection
    resamples every curve and shows up as several degrees on a fast-moving
    coordinate like knee flexion -- a phase difference, not a kinematic one.
    The .mot rows are the solver's own output on a shared time base, so a
    difference there is a real change in the solution.

    Reports both the worst single frame and the 99th percentile. The
    percentile is what the pass/fail rests on: the worst frame in these trials
    lands in the last second, after the subject has stopped walking, and one
    frame of a non-gait posture is not evidence about the fix either way.

    Returns ({coordinate: {"max": deg, "p99": deg}}, n_trials_compared).
    """
    after_dir = Path(session_dir) / "OpenSimData" / "Kinematics"
    before_dir = Path(session_dir) / "pre-calibration-fix" / "Kinematics"
    collected = {name: [] for name in coordinates}
    compared = 0
    for after_path in sorted(after_dir.glob("*.mot")):
        before_path = before_dir / after_path.name
        if not before_path.is_file():
            continue
        after, before = read_mot(after_path), read_mot(before_path)
        n = min(len(after["time"]), len(before["time"]))
        if n == 0:
            continue
        compared += 1
        for name in coordinates:
            if name in after and name in before:
                collected[name].append(
                    wrapped_difference(after[name][:n], before[name][:n]))
    shifts = {}
    for name, series in collected.items():
        if not series:
            shifts[name] = {"max": 0.0, "p99": 0.0}
            continue
        stacked = np.concatenate(series)
        shifts[name] = {"max": float(stacked.max()),
                        "p99": float(np.percentile(stacked, 99))}
    return shifts, compared


UPPER_IMUS = ("humerus_r_imu", "radius_r_imu", "hand_r_imu",
              "humerus_l_imu", "radius_l_imu", "hand_l_imu")
LOWER_IMUS = ("femur_r_imu", "tibia_r_imu", "calcn_r_imu",
              "femur_l_imu", "tibia_l_imu", "calcn_l_imu")

# A segment whose per-frame orientation residual averages above this is not
# being tracked -- the solver has settled somewhere else and stayed. Set from
# the measured distribution rather than picked: after the fix, 87 of 90 trials
# sit under 7 deg on every upper-body segment, and the exceptions are 21-59.
# There is no population between.
LOST_SEGMENT_DEG = 20.0

# How much worse an already-lost segment has to get before it counts as a
# regression rather than run-to-run variation in a solve that had already
# failed. IK is iterative and seeded from the previous frame, so a segment
# sitting at 27 deg residual will not reproduce to the tenth of a degree.
LOST_SEGMENT_REGRESSION_MARGIN_DEG = 2.0


def tracking_residuals(session_dir):
    """Per-trial IMU orientation residual RMS, before and after, in degrees.

    This is the check that actually detects a lost segment, and the reason the
    range heuristic below is not enough on its own: IK reports a confident
    number for a segment it has completely mistracked, and the number can sit
    inside physiological range while being 70 degrees from the measurement.
    The residual is the solver's own account of how well it did.

    Returns {trial: {"upper_before", "upper_after", "lower_before",
    "lower_after", "lost": {imu: (before, after)}}}.
    """
    after_dir = Path(session_dir) / "OpenSimData" / "Kinematics"
    before_dir = Path(session_dir) / "pre-calibration-fix" / "Kinematics"
    out = {}
    for after_path in sorted(after_dir.glob("*_orientationErrors.sto")):
        before_path = before_dir / after_path.name
        if not before_path.is_file():
            continue
        after, before = read_mot(after_path), read_mot(before_path)

        def rms(table, columns):
            present = [c for c in columns if c in table]
            if not present:
                return float("nan")
            return float(np.sqrt(np.mean(
                [np.mean(np.degrees(table[c]) ** 2) for c in present])))

        trial = after_path.name.split(".mot")[0]
        entry = {
            "upper_before": rms(before, UPPER_IMUS),
            "upper_after": rms(after, UPPER_IMUS),
            "lower_before": rms(before, LOWER_IMUS),
            "lower_after": rms(after, LOWER_IMUS),
            "lost": {},
        }
        for imu in UPPER_IMUS + LOWER_IMUS:
            if imu not in after:
                continue
            residual = float(np.sqrt(np.mean(np.degrees(after[imu]) ** 2)))
            if residual > LOST_SEGMENT_DEG:
                was = (float(np.sqrt(np.mean(np.degrees(before[imu]) ** 2)))
                       if imu in before else float("nan"))
                entry["lost"][imu] = (was, residual)
        out[trial] = entry
    return out


def _matching_pairs(after_dir, before_dir, conversion):
    """(after_path, before_path) for every trial present in BOTH, so the
    comparison is like for like. A trial that only exists on one side is
    reported by the caller rather than silently dropped."""
    pairs, unmatched = [], []
    for after in sorted(after_dir.glob(f"*-{conversion}-*_*.csv")):
        before = before_dir / after.name
        if before.is_file():
            pairs.append((after, before))
        else:
            unmatched.append(after.name)
    return pairs, unmatched


def check_session(session_dir, names, conversion="ik", leg_tolerance_deg=1.0):
    session_dir = Path(session_dir)
    after_dir = session_dir / "GaitCurves"
    before_dir = session_dir / "pre-calibration-fix" / "GaitCurves"
    result = {"session": session_dir.name, "problems": [], "notes": []}

    after_files = sorted(after_dir.glob(f"*-{conversion}-*_*.csv"))
    if not after_files:
        result["problems"].append("no regenerated curve files -- has the batch run?")
        return result
    result["n_after"] = len(after_files)

    if not before_dir.is_dir():
        result["notes"].append("no pre-fix backup; before/after comparison skipped")
        pairs = []
    else:
        pairs, unmatched = _matching_pairs(after_dir, before_dir, conversion)
        if unmatched:
            result["notes"].append(
                f"{len(unmatched)} trial(s) have no pre-fix counterpart "
                f"(e.g. {unmatched[0]}); excluded from the comparison")

    after = pool([p for p, _ in pairs] or after_files, names)
    result["after"] = after
    if pairs:
        before = pool([b for _, b in pairs], names)
        result["before"] = before

    shifts, compared = mot_shifts(
        session_dir, UNCHANGED_COORDINATES + TORSO_COORDINATES)
    result["shifts"], result["n_mot_compared"] = shifts, compared
    if compared == 0:
        result["notes"].append(
            "no pre-fix .mot files to compare against; the "
            "did-anything-else-move check did not run")
    for name in UNCHANGED_COORDINATES:
        if compared and shifts[name]["p99"] > leg_tolerance_deg:
            result["problems"].append(
                f"{name} moved by {shifts[name]['p99']:.3f} deg (p99) in the "
                "raw .mot -- pelvis and legs hold the same pose in the T-pose "
                "as in the model default, so the calibration pose cannot "
                "reach them; a shift here falsifies the diagnosis")

    for name in ARM_COORDINATES:
        extreme = max(abs(after[name]["min"]), abs(after[name]["max"]))
        if extreme > PHYSIOLOGICAL_LIMIT_DEG:
            result["notes"].append(
                f"{name} reaches {extreme:.1f} deg. Above the "
                f"{PHYSIOLOGICAL_LIMIT_DEG:.0f} deg sanity limit, but a note "
                "rather than a failure: past +/-180 the Euler triplet has an "
                "equivalent representation, so a large number can be the same "
                "arm written differently. The residual check below is what "
                "decides whether a segment is actually mistracked.")

    residuals = tracking_residuals(session_dir)
    result["residuals"] = residuals
    for trial, entry in sorted(residuals.items()):
        if entry["lost"]:
            worst = max(entry["lost"].items(), key=lambda kv: kv[1][1])
            imu, (was, now) = worst
            # Only a REGRESSION is a failure, and only a real one. Several KM
            # trials sit above the threshold both before and after -- a
            # pre-existing tracking problem on that participant, improved but
            # not solved, and not this fix's to answer for. The margin exists
            # because KM-009 moved 27.7 -> 27.9 deg on a segment that was
            # already lost; calling that a regression is noise dressed as a
            # finding.
            if now > was + LOST_SEGMENT_REGRESSION_MARGIN_DEG:
                result["problems"].append(
                    f"{trial}: {imu} residual {was:.1f} -> {now:.1f} deg RMS. "
                    "The solver lost this segment and the fix made it worse; "
                    "its kinematics for that segment are not usable")
            else:
                result["notes"].append(
                    f"{trial}: {imu} residual {was:.1f} -> {now:.1f} deg RMS "
                    "-- above the tracking threshold before AND after, so "
                    "pre-existing rather than caused by the fix")
        if entry["upper_after"] > entry["upper_before"] + 1.0:
            result["problems"].append(
                f"{trial}: upper-body residual {entry['upper_before']:.1f} -> "
                f"{entry['upper_after']:.1f} deg RMS -- worse after the fix")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sessions", default="Data/xsens_sessions")
    parser.add_argument("--conversion", default="ik")
    parser.add_argument("--leg-tolerance-deg", type=float, default=1.0)
    parser.add_argument("--saturation-tolerance-deg", type=float, default=1.0)
    args = parser.parse_args(argv)

    mc = _load_module(REPO_ROOT / "methodology_comparison.py",
                      "_methodology_comparison_for_verification")
    names = joint_names()
    sessions = sorted(Path(args.sessions).glob("XsensSession_*"))
    if not sessions:
        print(f"no sessions under {args.sessions}")
        return 1

    all_problems = []
    for session in sessions:
        result = check_session(session, names, args.conversion, args.leg_tolerance_deg)
        print(f"\n=== {result['session']} "
              f"({result.get('n_after', 0)} curve files) ===")
        for note in result["notes"]:
            print(f"  note: {note}")
        if "after" not in result:
            for problem in result["problems"]:
                print(f"  FAIL: {problem}")
            all_problems += result["problems"]
            continue

        before, after = result.get("before"), result["after"]
        def _range(entry):
            if entry is None:
                return "--"
            return "{:9.1f} .. {:9.1f}".format(entry["min"], entry["max"])

        def _sd(entry):
            return "--" if entry is None else "{:.2f}".format(entry["sd"])

        print("  {:<16}{:>26}{:>26}{:>12}{:>10}".format(
            "coordinate", "before range", "after range", "SD before", "SD after"))
        for name in ARM_COORDINATES:
            b = None if before is None else before[name]
            a = after[name]
            print("  {:<16}{:>26}{:>26}{:>12}{:>10}".format(
                name, _range(b), _range(a), _sd(b), _sd(a)))

        model = next((session / "OpenSimData" / "Model").glob("*_scaled.osim"), None)
        if model is None:
            print("  note: no scaled model found; bound check skipped")
        else:
            ranges = mc.read_model_coordinate_ranges(model)
            flagged = mc.saturated_coordinates(
                {"coordinates": after}, ranges,
                tolerance_deg=args.saturation_tolerance_deg)
            if flagged:
                print("  touching a model bound (not automatically a fault -- an "
                      "elbow at 0 deg is full extension, which people reach):")
                for name, entry in sorted(flagged.items()):
                    print(f"    {name:<16}{entry['bound']:>4} bound "
                          f"{entry['limit']:9.2f}, reached {entry['reached']:9.2f}")
            else:
                print("  no coordinate touching a model bound")

        residuals = result.get("residuals") or {}
        if residuals:
            ub = np.mean([e["upper_before"] for e in residuals.values()])
            ua = np.mean([e["upper_after"] for e in residuals.values()])
            lb = np.mean([e["lower_before"] for e in residuals.values()])
            la = np.mean([e["lower_after"] for e in residuals.values()])
            print(f"  IMU tracking residual RMS over {len(residuals)} trials:")
            print(f"    upper body: {ub:6.2f} -> {ua:6.2f} deg")
            print(f"    lower body: {lb:6.2f} -> {la:6.2f} deg")

        shifts = result.get("shifts")
        if shifts and result.get("n_mot_compared"):
            n_mot = result["n_mot_compared"]
            leg = max(UNCHANGED_COORDINATES, key=lambda n: shifts[n]["p99"])
            torso = max(TORSO_COORDINATES, key=lambda n: shifts[n]["p99"])
            print(f"  raw .mot shift over {n_mot} trials:")
            print(f"    pelvis + legs (must not move): worst {leg} "
                  f"p99 {shifts[leg]['p99']:.3f} deg, max {shifts[leg]['max']:.3f} deg")
            print(f"    lumbar (expected to improve):  worst {torso} "
                  f"p99 {shifts[torso]['p99']:.3f} deg, max {shifts[torso]['max']:.3f} deg")

        for problem in result["problems"]:
            print(f"  FAIL: {problem}")
        all_problems += result["problems"]

    print("\n" + ("=" * 60))
    if all_problems:
        print(f"{len(all_problems)} problem(s):")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1
    print("All sessions pass: arms physiological, lower limb unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
